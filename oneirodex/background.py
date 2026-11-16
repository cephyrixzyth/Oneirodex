"""Background-worker lifecycle, lifted out of ``create_app()``.

``create_app()`` used to start six or seven daemon schedulers inline. That
coupled app construction to a running process — every script that called
``create_app()`` to get a configured app also spawned threads, and there was
no shutdown path. The servers run via uvicorn → ``asgi.py``, whose ASGI
lifespan handler is the right owner: it starts the workers once on startup and
stops them on shutdown.

The scheduler-start block below is moved **verbatim** from ``create_app()`` —
same ``try/except`` per scheduler, same ``logger.warning`` on failure, same
``app.app_context()`` push, same ``pytest`` skip. The only additions are the
``ONEIRODEX_ENABLE_BACKGROUND_WORKERS`` env gate and collecting whatever the
``start_*`` functions return so :func:`stop_background_workers` can ask them to
stop.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

#: Handles returned by the ``start_*`` functions (only the library watcher
#: currently returns one — a ``LibraryWatchController`` with ``.stop()``). Kept
#: so :func:`stop_background_workers` can best-effort stop them on lifespan
#: shutdown. Anything falsy is not recorded.
_WORKER_HANDLES: list[object] = []

#: Set once :func:`start_background_workers` has run its body, so a second call
#: (e.g. a re-entered lifespan) is a no-op rather than a double-start. The
#: individual schedulers already guard themselves with module-level flags; this
#: is belt-and-braces at the entry point.
_STARTED = False


def _workers_enabled() -> bool:
    """Env gate. Default on; any of 0/false/no/off (case-insensitive) disables."""
    raw = os.getenv('ONEIRODEX_ENABLE_BACKGROUND_WORKERS', 'true')
    return str(raw).strip().lower() not in ('0', 'false', 'no', 'off')


def start_background_workers(app):
    """Start the background schedulers for a live server process (idempotent).

    No-op under pytest (schedulers were already skipped there) and when
    ``ONEIRODEX_ENABLE_BACKGROUND_WORKERS`` is set to a falsy value.
    """
    global _STARTED

    if 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ:
        return
    if not _workers_enabled():
        logger.info(
            "Background workers disabled (ONEIRODEX_ENABLE_BACKGROUND_WORKERS)"
        )
        return
    if _STARTED:
        return
    _STARTED = True

    with app.app_context():
        # Database initialization is handled by the InitializationManager before workers start
        # Worker processes skip initialization entirely since it's already done
        if ('pytest' not in sys.modules and 'PYTEST_CURRENT_TEST' not in os.environ and
            os.getenv('ONEIRODEX_INITIALIZATION_COMPLETE') != 'true'):
            # This should only happen in development or if initialization wasn't run
            logger.warning("⚠️  Initialization not completed - this may cause issues")

        if ('pytest' not in sys.modules and 'PYTEST_CURRENT_TEST' not in os.environ):
            # Reclaim scans orphaned by whatever ended the last process.
            #
            # InitializationManager already does this, but only on the operator
            # path (startweb*.sh runs it once before workers). Anything else —
            # a dev server, a respawned worker, a container whose entrypoint was
            # bypassed — booted straight past it, leaving 'Running' rows that no
            # thread was working on. is_scan_busy() then reported busy and every
            # new scan queued behind a ghost for STALE_RUNNING_SECONDS (6h),
            # which is what "scanning is broken" looked like from the admin UI.
            #
            # Safe to run in every process, including multi-worker: the sweep
            # only reclaims jobs whose owning process is provably gone, so a
            # sibling worker's live scan is left alone.
            try:
                from oneirodex.utils.scan_queue import reclaim_stale_busy_jobs
                reclaimed = reclaim_stale_busy_jobs()
                if reclaimed:
                    logger.info(f"[SCAN QUEUE] Reclaimed {reclaimed} orphaned scan job(s) at startup")
            except Exception as exc:
                logger.error(f"[SCAN QUEUE] Startup reclaim failed: {exc}")

            try:
                from oneirodex.utils.scan_scheduler import start_scan_scheduler
                _record_handle(start_scan_scheduler(app))
            except Exception as exc:
                logger.warning(f"[SCAN SCHEDULER] Could not start: {exc}")
            try:
                from oneirodex.utils.library_watch import start_library_watch
                _record_handle(start_library_watch(app))
            except Exception as exc:
                logger.warning(f"[LIBRARY WATCH] Could not start: {exc}")
            try:
                from oneirodex.utils.free_games_poller import start_free_games_scheduler
                _record_handle(start_free_games_scheduler(app))

                from oneirodex.utils.discover_ml.job import start_discover_ml_scheduler
                _record_handle(start_discover_ml_scheduler(app))
            except Exception as exc:
                logger.warning(f"[FREE GAMES] Could not start: {exc}")
            try:
                # Linked store accounts synced once at link time and then went
                # stale (GT-B27) — the live call existed, nothing re-ran it.
                from oneirodex.utils.ownership_poller import start_ownership_scheduler
                _record_handle(start_ownership_scheduler(app))
            except Exception as exc:
                logger.warning(f"[OWNERSHIP] Could not start: {exc}")
            try:
                from oneirodex.utils.store_deals_poller import start_store_deals_scheduler
                _record_handle(start_store_deals_scheduler(app))
            except Exception as exc:
                logger.warning(f"[STORE DEALS] Could not start: {exc}")
            try:
                from oneirodex.utils.email_digest_scheduler import start_email_digest_scheduler
                _record_handle(start_email_digest_scheduler(app))
            except Exception as exc:
                logger.warning(f"[EMAIL DIGEST] Could not start: {exc}")
            try:
                # Community anti-cheat list (INSP-35): one fetch a day into the
                # library volume; details read the cache, never the network.
                from oneirodex.utils.anticheat_poller import start_anticheat_scheduler
                _record_handle(start_anticheat_scheduler(app))
            except Exception as exc:
                logger.warning(f"[ANTICHEAT] Could not start: {exc}")
            try:
                # Community save-location manifest (INSP-1): one fetch a day,
                # compact index beside it; details read the index only.
                from oneirodex.utils.save_paths_poller import start_save_paths_scheduler
                _record_handle(start_save_paths_scheduler(app))
            except Exception as exc:
                logger.warning(f"[SAVE PATHS] Could not start: {exc}")
            try:
                from oneirodex.utils.user_deletion import start_file_cleanup_worker
                _record_handle(start_file_cleanup_worker(app))
            except Exception as exc:
                logger.warning(f"[ACCOUNT DELETION] Could not start cleanup worker: {exc}")


def _record_handle(handle) -> None:
    """Keep any non-falsy handle a ``start_*`` returned, for shutdown."""
    if handle:
        _WORKER_HANDLES.append(handle)


def stop_background_workers():
    """Best-effort stop of anything :func:`start_background_workers` started.

    Only handles that expose ``shutdown()`` or ``stop()`` can be stopped — the
    library watcher's ``LibraryWatchController`` does. The plain daemon-thread
    pollers (scan, free-games, discover-ML, ownership, store-deals,
    email-digest) return no handle and expose no stop hook; they are
    ``daemon=True`` and die with the process. Documented no-op for those.
    """
    global _STARTED

    while _WORKER_HANDLES:
        handle = _WORKER_HANDLES.pop()
        stopper = getattr(handle, 'shutdown', None) or getattr(handle, 'stop', None)
        if stopper is None:
            logger.debug("No stop hook on %r; relying on daemon-thread exit", handle)
            continue
        try:
            stopper()
        except Exception as exc:
            logger.warning("Stopping %r failed: %s", handle, exc)

    _STARTED = False
