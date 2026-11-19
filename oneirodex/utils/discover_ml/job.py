"""The scheduled rebuild.

Everything the recommender needs is materialised here so the request path never
computes any of it. A Discover load should not get slower because the install
has been running for a year.
"""

from __future__ import annotations

from oneirodex.utils.periodic_worker import PeriodicWorker

from sqlalchemy import select

from oneirodex.models import User
from oneirodex.runtime_native.db_session import native_db as db

from . import similarity
from .profile import rebuild_profile

_scheduler = PeriodicWorker('oneirodex-discover-ml')

#: Default gap between rebuilds. Taste moves slowly; a nightly pass is ample and
#: a tighter loop would spend the box's disk for no visible difference.
DEFAULT_INTERVAL_HOURS = 24.0


def rebuild_all() -> dict:
    """Rebuild every member's profile and the similarity graph."""
    user_ids = [row[0] for row in db.session.execute(select(User.id)).all()]

    profiles = 0
    for user_id in user_ids:
        try:
            if rebuild_profile(user_id):
                profiles += 1
        except Exception as exc:  # noqa: BLE001
            # One member's odd data must not cost everyone else their profile.
            db.session.rollback()
            print(f'[DISCOVER ML] Profile rebuild failed for user {user_id}: {exc}')

    graph = similarity.rebuild()
    return {'members': len(user_ids), 'profiles': profiles, **graph}


def _is_enabled(app) -> bool:
    return bool(app.config.get('ENABLE_DISCOVER_ML', True))


def _interval_seconds(app) -> int:
    try:
        hours = float(app.config.get('DISCOVER_ML_REBUILD_HOURS') or DEFAULT_INTERVAL_HOURS)
    except (TypeError, ValueError):
        hours = DEFAULT_INTERVAL_HOURS
    hours = max(1.0, min(hours, 168.0))
    return int(hours * 3600)


def start_discover_ml_scheduler(app):
    """Start the rebuild daemon (idempotent)."""
    if not _is_enabled(app):
        print('[DISCOVER ML] Disabled (ENABLE_DISCOVER_ML=false)')
        return

    interval = _interval_seconds(app)

    def run_once():
        try:
            with app.app_context():
                stats = rebuild_all()
                print(
                    f"[DISCOVER ML] Rebuilt profiles={stats.get('profiles')}"
                    f"/{stats.get('members')} content_pairs={stats.get('content_pairs')}"
                    f" collab={'on' if stats.get('collab_ran') else 'below floor'}"
                )
        except Exception as exc:  # noqa: BLE001
            print(f'[DISCOVER ML] Error: {exc}')

    return _scheduler.start(run_once, interval=interval, delay=60)
