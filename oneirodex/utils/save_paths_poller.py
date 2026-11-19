"""Background refresh for the community save-location manifest (INSP-1, H4e).

One daemon, one fetch a day, through :func:`save_paths.refresh_if_stale`,
which also rebuilds the compact index a details request reads.
"""

from __future__ import annotations

import logging
from oneirodex.utils.periodic_worker import PeriodicWorker

logger = logging.getLogger(__name__)

_scheduler = PeriodicWorker('oneirodex-save-paths')
_CHECK_SECONDS = 3600


def start_save_paths_scheduler(app):
    """Start the daemon that keeps the save-path index fresh (idempotent)."""
    from oneirodex.utils.save_paths import fetch_allowed

    if not fetch_allowed():
        logger.info('[SAVE PATHS] Disabled (ENABLE_SAVE_PATHS=false or testing)')
        return None


    def run_once():
        try:
            with app.app_context():
                from oneirodex.utils.save_paths import refresh_if_stale

                refresh_if_stale()
        except Exception as exc:  # noqa: BLE001
            logger.warning('[SAVE PATHS] refresh loop error: %s', exc)

    return _scheduler.start(run_once, interval=_CHECK_SECONDS, delay=40)
