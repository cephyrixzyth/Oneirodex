"""Alembic environment for Oneirodex.

Wired for the modernization program (wave A3.1): the schema used to be built by
``db.create_all()`` + the idempotent raw-DDL pass in
``oneirodex/updateschema.py``. Alembic now owns forward schema change; the
baseline revision in ``alembic/versions/`` is a squash of everything
``updateschema.py`` had accumulated.

Design notes:

* ``target_metadata`` is ``oneirodex.models`` ``db.metadata`` -- importing the
  models module registers every table on the shared Flask-SQLAlchemy metadata.
  No app context is required; the models import only needs ``.env`` loaded so
  ``config.Config`` can read ``SECRET_KEY`` etc.
* The URL resolves the same way the running app does: ``DATABASE_URL`` first
  (Compose / systemd set it), then ``TEST_DATABASE_URL`` (what ``conftest.py``
  maps onto ``DATABASE_URL`` for the suite), then
  ``Config.SQLALCHEMY_DATABASE_URI`` as the final fallback. An explicit
  ``-x db_url=...`` on the alembic command line overrides all of it.
* ``compare_type`` / ``compare_server_default`` are on so ``alembic check``
  is meaningful. The one unavoidable gap -- perf/uniqueness indexes that
  ``updateschema.py`` created but ``models.py`` never declared -- is handled
  by ``_include_object`` below (a named allow-list) so ``alembic check`` comes
  back clean. Each excluded index is catalogued in
  ``docs/dev/alembic-baseline-notes.md``; promoting one into a model's
  ``__table_args__`` means deleting it from that set in the same change.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Alembic may be invoked with a CWD that is not the repo root (init_manager
# stamps the baseline during boot, under uvicorn/Docker). Put the repo root --
# the directory that holds this alembic/ tree -- on sys.path so `oneirodex`
# and `config` import regardless of where alembic was launched from.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Load .env before importing config -- config.Config reads SECRET_KEY and the
# DB URL at class-body evaluation time and raises if SECRET_KEY is unset.
load_dotenv(os.path.join(_REPO_ROOT, ".env"))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing the framework-independent models module registers every table on
# the shared declarative metadata. Alembic runs in the production image, where
# the legacy Flask compatibility runtime (and its Jinja dependency) is absent.
from oneirodex import models  # noqa: E402,F401  (import for side effect)
from oneirodex.models.orm import ModelBase  # noqa: E402
from config import Config  # noqa: E402

target_metadata = ModelBase.metadata

# Indexes the pre-Alembic raw-DDL pass (oneirodex/updateschema.py) created that
# are NOT re-declared on models.py metadata. The baseline revision builds them
# (see its "squashed from updateschema.py" tail); models.py has never carried
# them. Without this exclusion every `alembic check` / autogenerate would want
# to drop them. Catalogued in docs/dev/alembic-baseline-notes.md -- when one is
# promoted into a model's __table_args__, delete it from this set in the same
# change.
_BASELINE_ONLY_INDEXES = frozenset({
    "idx_user_game_status_lookup",
    "ix_client_devices_last_seen_at",
    "ix_duplicate_fix_logs_created_at",
    "ix_duplicate_fix_logs_matched_game",
    "ix_games_library_uuid",
    "ix_games_name",
    "ix_games_date_created",
    "ix_games_rating",
    "ix_games_item_kind",
    "ix_games_path_status",
    "ix_user_content_filters_user_id",
    "ix_user_library_access_user_id",
    "ix_user_library_access_library_uuid",
    "unique_game_cover_image",
    "unique_game_box_image",
    "unique_game_cart_image",
    "unique_game_disc_image",
    "unique_game_logo_image",
    "unique_game_hero_image",
    "unique_game_fanart_image",
})


def _include_object(obj, name, type_, reflected, compare_to):
    """Keep the baseline-only updateschema indexes out of autogenerate diffs."""
    if type_ == "index" and name in _BASELINE_ONLY_INDEXES:
        return False
    return True


def _render_item(type_, obj, autogen_context):
    """Render our custom column types as their storage impl in revisions.

    ``oneirodex.models.JSONEncodedDict`` is a ``TypeDecorator`` over ``TEXT``
    (JSON is serialised in Python). Autogenerate would otherwise emit
    ``oneirodex.models.JSONEncodedDict()`` and require importing the app
    package inside every migration; the on-disk column is plain ``TEXT``, so
    render it as ``sa.Text()``.
    """
    if type_ == "type" and obj.__class__.__name__ == "JSONEncodedDict":
        return "sa.Text()"
    return False


def _resolve_url() -> str:
    """Match the app's URL resolution, with an alembic-only escape hatch.

    ``alembic -x db_url=postgresql://...`` wins outright; otherwise fall back
    through the same env vars the rest of the app respects.
    """
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("db_url"):
        return x_args["db_url"]
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("TEST_DATABASE_URL")
        or Config.SQLALCHEMY_DATABASE_URI
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI needed)."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_item=_render_item,
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_item=_render_item,
            include_object=_include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
