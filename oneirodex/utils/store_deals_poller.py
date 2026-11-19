"""Background refresh of CheapShark deep discounts.

Discover must not wait on outbound HTTPS. The poller warms
``store_deals.cached_deep_discounts`` shortly after boot and again each TTL.
The request path still fetches on a cold cache so the first member after a
restart is not staring at an empty shelf for 15 seconds.
"""

from __future__ import annotations

import logging
from oneirodex.utils.periodic_worker import PeriodicWorker

from oneirodex.utils.store_deals import CACHE_TTL_SEC, refresh_deep_discounts

logger = logging.getLogger(__name__)

_scheduler = PeriodicWorker('oneirodex-store-deals')


def start_store_deals_scheduler(app):
    """Start a daemon that refreshes CheapShark deals (idempotent)."""
    interval = CACHE_TTL_SEC

    def run_once():
        try:
            with app.app_context():
                count = refresh_deep_discounts()
                logger.info('CheapShark deep discounts refreshed (%s deals)', count)
        except Exception:
            logger.exception('CheapShark deep-discount refresh failed')

    return _scheduler.start(run_once, interval=interval, delay=15)
