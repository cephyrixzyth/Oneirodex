"""What is actually running here, and is it what was shipped?

After a deploy that question had no answer from inside the product. The version
was a literal in ``__init__.py``; the Alembic revision was never read back (only
the table's *existence* was checked); and no git SHA or build timestamp reached
the process at all -- the image tag was the only build identity and it is not
readable from within the container.

So an operator could redeploy, watch the container come up healthy, and still
not know whether the code was new or whether the migration had run. That is the
gap this closes.

Every field degrades to ``None`` and nothing here raises, which is the contract
``system_stats.get_gpu_usage`` (INSP-44) already set for ops collectors: a tile
that reads *n/a* is honest, and one that takes the Ops poll down with it is not.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ['build_identity', 'reset_build_identity_cache']

# Set at image build time from the deploying commit; absent for a hand-built
# image, which is a supported state rather than an error.
_SHA_ENV = 'ONEIRODEX_BUILD_SHA'
_BUILT_AT_ENV = 'ONEIRODEX_BUILT_AT'

_cached: dict[str, Any] | None = None


def reset_build_identity_cache() -> None:
    """Drop the memo. For tests; nothing in the app needs it."""
    global _cached
    _cached = None


def _env(name: str) -> str | None:
    value = (os.environ.get(name) or '').strip()
    return value or None


def _safe(fn) -> str | None:
    """Belt to the helpers' braces.

    Each helper already swallows its own failures, but the guarantee this
    module makes is that *nothing here raises* -- and a guarantee that depends
    on every future helper remembering to catch is not a guarantee.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.debug('build identity: %s failed (%s)', getattr(fn, '__name__', fn), exc)
        return None


def _schema_revision() -> str | None:
    """The revision the database is actually stamped at."""
    try:
        from alembic.runtime.migration import MigrationContext

        from oneirodex.runtime_native.db_session import current_native_engine

        # FastAPI binds its engine for the request scope. Prefer it so the Ops
        # build card remains useful in the Flask-free runtime. During legacy
        # Flask calls there is no native engine, so preserve the old fallback.
        engine = current_native_engine()
        if engine is None:
            from oneirodex import db

            engine = db.engine

        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    except Exception as exc:  # noqa: BLE001 -- an ops tile never takes the poll down
        logger.debug('build identity: schema revision unavailable (%s)', exc)
        return None


def _schema_head() -> str | None:
    """The revision this *code* expects, read from the migration scripts.

    Comparing the two is the whole point: equal means the deploy is complete,
    different means a migration is pending and something is about to behave
    strangely in a way nobody would connect back to the deploy.
    """
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        config = Config(os.path.join(root, 'alembic.ini'))
        config.set_main_option('script_location', os.path.join(root, 'alembic'))
        heads = ScriptDirectory.from_config(config).get_heads()
        # More than one head means the migration chain has branched, which is a
        # real problem worth surfacing rather than papering over with heads[0].
        return heads[0] if len(heads) == 1 else None
    except Exception as exc:  # noqa: BLE001
        logger.debug('build identity: schema head unavailable (%s)', exc)
        return None


def build_identity() -> dict[str, Any]:
    """Version, build and schema state, memoised for the process lifetime.

    Memoised because none of it can change while the process runs: the version
    is a module constant, the build stamp is baked into the image, and
    ``init_manager`` runs ``alembic upgrade head`` at startup -- so a migration
    implies a restart. Re-querying ``alembic_version`` every 15 s for a value
    that cannot move would be waste on the Ops poll.
    """
    global _cached
    if _cached is not None:
        return dict(_cached)

    from oneirodex import app_version
    from oneirodex.utils.preset_themes import GENERATOR_VERSION

    revision = _safe(_schema_revision)
    head = _safe(_schema_head)
    identity: dict[str, Any] = {
        'version': app_version,
        'commit': _env(_SHA_ENV),
        'built_at': _env(_BUILT_AT_ENV),
        'schema_revision': revision,
        'schema_head': head,
        # None, not False: "we could not tell" and "nothing is pending" are
        # different answers and the tile says so differently.
        'migration_pending': None if (revision is None or head is None) else revision != head,
        'generator_version': GENERATOR_VERSION,
    }
    _cached = identity
    return dict(identity)
