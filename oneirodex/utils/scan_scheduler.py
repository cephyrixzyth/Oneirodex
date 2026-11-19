"""Background poller for scheduled library scans."""

from __future__ import annotations

from oneirodex.utils.periodic_worker import PeriodicWorker
from datetime import datetime, timezone

from sqlalchemy import select

_scheduler = PeriodicWorker('oneirodex-scan-scheduler')
_POLL_SECONDS = 60


def start_scan_scheduler(app):
    """Start a daemon that runs due ScanJobs (idempotent)."""

    def run_once():
        try:
            with app.app_context():
                database_scope = lambda _app: app.app_context()
                _run_due_jobs(app, database_scope=database_scope)
        except Exception as exc:
            print(f"[SCAN SCHEDULER] Error: {exc}")

    return _scheduler.start(run_once, interval=_POLL_SECONDS)


def _run_due_jobs(app, *, database_scope=None):
    from oneirodex.models import ScanJob
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.utils.scan_queue import drain_scan_queue, is_scan_busy

    # Prefer explicit FIFO Queued requests over recurring Scheduled jobs.
    # Also reclaim stale Stopping/Running so idle+Queued cannot stick forever.
    promoted = drain_scan_queue(app, database_scope=database_scope)
    if promoted:
        return

    if is_scan_busy():
        return

    now = datetime.now(timezone.utc)
    jobs = db.session.execute(
        select(ScanJob).filter(
            ScanJob.is_enabled.is_(True),
            ScanJob.status == 'Scheduled',
            ScanJob.next_run.isnot(None),
        )
    ).scalars().all()

    due = []
    for job in jobs:
        next_run = job.next_run
        if next_run is None:
            continue
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
        if next_run <= now:
            due.append(job)

    if not due:
        return

    job = due[0]
    folder = job.scan_folder
    if not folder:
        print(f'[SCAN SCHEDULER] Job {job.id} has no scan_folder; skipping')
        return

    from oneirodex.utils.scan_queue import restart_or_queue_scan

    restart_or_queue_scan(
        job.id, app=app, scheduled=True, database_scope=database_scope,
    )
