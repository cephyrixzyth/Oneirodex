"""Scan job queue vs force-parallel start policy.

Default policy when a scan is already Running/Stopping: **queue** (FIFO).
Admin may opt in to **force parallel** — starts alongside the running job,
still subject to per-job ``scan_thread_count`` / ``worker_caps``.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from threading import Thread

from flask import current_app
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from oneirodex import db
from oneirodex.models import ScanJob

FORCE_PARALLEL_RISK = (
    'Force parallel starts a second library scan while another is still '
    'Running/Stopping. On shared NAS/Unraid hosts this can spike CPU and '
    'freeze the UI. Each job still respects scan_thread_count / worker_caps.'
)

QUEUE_DEFAULT_MESSAGE = (
    'A scan is already running. This request was queued and will start '
    'when the current job finishes (FIFO).'
)

COALESCE_MESSAGE = (
    'A scan for this library folder is already queued. Reusing the existing '
    'Queued job instead of creating another (coalesced).'
)

# Stopping should finish quickly; Running without progress is likely orphaned.
#
# These remain the fallback for a job whose owner process is still alive but has
# stopped making progress — a genuinely stuck thread, which no liveness check can
# detect. A job whose owner process is *gone* no longer waits for them; see
# owner_is_alive and reclaim_stale_busy_jobs.
STALE_STOPPING_SECONDS = 10 * 60
STALE_RUNNING_SECONDS = 6 * 60 * 60

# Identifies this process for the lifetime of the process.
#
# The uuid half matters as much as the pid: pids are recycled, so "pid 4312 is
# alive" does not mean "pid 4312 is still the process that started this scan".
# After a restart the new process can easily be handed the old one's pid, and a
# pid-only check would then call an orphaned job healthy and keep the queue
# wedged — the exact failure this column exists to end.
PROCESS_TOKEN = f'{uuid.uuid4().hex}:{os.getpid()}'


def owner_is_alive(token: str | None, started_at=None) -> bool:
    """Is the process that owns this job still running?

    ``None``/malformed means the job predates the column (or was written by an
    older build). There is nothing to verify, and an unverifiable row is not
    evidence of death, so it counts as alive and the time-based sweep below
    decides its fate exactly as it did before this column existed. Rows written
    from now on all carry a token, so this only ever applies to the backlog
    present at upgrade — which InitializationManager also clears at boot.

    ``started_at`` is when the job went Running. It settles the recycled-pid
    case: a process created *after* the scan began cannot be the one that
    started it, however matching its pid looks. Without that comparison a
    restart that happened to reuse the pid would keep the queue wedged, which is
    the failure this whole column exists to end.

    Errs toward *alive* whenever the answer is genuinely unknown (psutil
    missing, permission denied, no timestamp to compare): a scan wrongly
    reclaimed mid-run would leave two workers writing one job, which is worse
    than a queue that drains late.
    """
    if token == PROCESS_TOKEN:
        return True
    if not token or ':' not in token:
        return True

    _boot_id, _, raw_pid = token.rpartition(':')
    try:
        pid = int(raw_pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True

    try:
        import psutil
    except ImportError:
        # Cannot prove death — leave it to the timeout rather than guess.
        return True

    try:
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return False
        created = proc.create_time()
    except psutil.NoSuchProcess:
        return False
    except (psutil.AccessDenied, OSError):
        return True

    if started_at is None:
        return True

    anchor = started_at
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    # A little slack: create_time and the job's clock come from different
    # sources, and a process that started fractionally after the row was written
    # is still plausibly the owner.
    return created <= anchor.timestamp() + 60


def parse_force_parallel(raw) -> bool:
    """Truthy parse for form/JSON/query ``force_parallel`` flag."""
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    text = str(raw).strip().lower()
    return text in ('1', 'true', 'yes', 'on')


def parse_queue_policy(raw, force_parallel=None) -> str:
    """Return ``queue`` (default) or ``force``.

    Accepts explicit ``queue_policy`` or legacy ``force_parallel`` flag.
    """
    if force_parallel is True or parse_force_parallel(force_parallel):
        return 'force'
    if raw is None:
        return 'queue'
    text = str(raw).strip().lower()
    if text in ('force', 'force_parallel', 'parallel', 'concurrent'):
        return 'force'
    return 'queue'


def _norm_folder(path: str | None) -> str:
    if not path:
        return ''
    try:
        return os.path.normcase(os.path.normpath(str(path).strip()))
    except Exception:
        return str(path).strip().lower()


def is_scan_busy() -> bool:
    """True when a job is Running or Stopping (default queue gate)."""
    busy = db.session.execute(
        select(ScanJob.id).where(ScanJob.status.in_(('Running', 'Stopping'))).limit(1)
    ).first()
    return busy is not None


def count_queued_jobs() -> int:
    return int(
        db.session.execute(
            select(func.count(ScanJob.id)).where(ScanJob.status == 'Queued')
        ).scalar()
        or 0
    )


def list_queued_jobs():
    """FIFO Queued jobs (oldest request first)."""
    return db.session.execute(
        select(ScanJob)
        .where(ScanJob.status == 'Queued')
        .order_by(ScanJob.last_run.asc().nullsfirst(), ScanJob.id.asc())
    ).scalars().all()


def queue_position(job_id: str) -> int | None:
    """1-based FIFO position among Queued jobs, or None if not queued."""
    for idx, job in enumerate(list_queued_jobs(), start=1):
        if job.id == job_id:
            return idx
    return None


def find_queued_for_library(library_uuid: str, folder_path: str) -> ScanJob | None:
    """Return an existing Queued job for the same library root, if any."""
    folder_n = _norm_folder(folder_path)
    rows = db.session.execute(
        select(ScanJob)
        .where(
            ScanJob.library_uuid == library_uuid,
            ScanJob.status == 'Queued',
        )
        .order_by(ScanJob.last_run.asc().nullsfirst(), ScanJob.id.asc())
    ).scalars().all()
    for row in rows:
        if _norm_folder(row.scan_folder) == folder_n:
            return row
    return None


def normalize_schedule_fields(
    schedule_choice,
    *,
    interval_value=None,
    interval_unit='hours',
    cron_expr=None,
):
    """Map Auto form schedule controls onto ScanJob columns.

    Returns dict with keys: schedule (legacy enum or None), schedule_kind,
    schedule_interval_minutes, schedule_cron, next_run (optional precompute).
    """
    from oneirodex.utils.services.scan_orchestration import (
        SCHEDULE_HOURS,
        compute_next_run,
    )

    choice = (schedule_choice or '').strip()
    out = {
        'schedule': None,
        'schedule_kind': 'once',
        'schedule_interval_minutes': None,
        'schedule_cron': None,
        'next_run': None,
        'error': None,
    }
    if not choice:
        return out
    if choice in SCHEDULE_HOURS:
        out['schedule'] = choice
        out['schedule_kind'] = 'preset'
        out['next_run'] = compute_next_run(choice)
        return out
    if choice == 'interval':
        try:
            value = int(interval_value or 0)
        except (TypeError, ValueError):
            value = 0
        unit = (interval_unit or 'hours').strip().lower()
        minutes = value * 60 if unit == 'hours' else value
        if minutes < 1:
            out['error'] = 'Interval must be at least 1 minute.'
            return out
        out['schedule_kind'] = 'interval'
        out['schedule_interval_minutes'] = minutes
        out['next_run'] = compute_next_run(
            schedule_kind='interval', interval_minutes=minutes,
        )
        return out
    if choice == 'cron':
        expr = (cron_expr or '').strip()
        from oneirodex.utils.cron_schedule import validate_cron_expression

        if not expr:
            out['error'] = 'Cron expression is required.'
            return out
        cron_err = validate_cron_expression(expr)
        if cron_err:
            out['error'] = f'Invalid cron expression: {cron_err}'
            return out
        out['schedule_kind'] = 'cron'
        out['schedule_cron'] = expr[:64]
        out['next_run'] = compute_next_run(schedule_kind='cron', cron_expr=expr)
        return out
    # Unknown choice: fail closed like the cron/interval branches above. Falling
    # through to `once` with no error armed nothing while the caller flashed
    # success — a select option added to the template but not here would look
    # like it worked.
    out['error'] = f'Unknown schedule option: {choice}'
    return out


def apply_schedule_to_job(job, schedule_fields, *, arm_scheduled=False):
    """Write normalized schedule fields onto a ScanJob; optionally arm next_run."""
    if not job or not schedule_fields:
        return
    # No hasattr() guards: these are mapped columns, so the attribute exists on
    # the instance whether or not the database has run migration a1c2e3f4b5d6.
    # The guards read as pre-migration safety and provided none.
    job.schedule = schedule_fields.get('schedule')
    job.schedule_kind = schedule_fields.get('schedule_kind')
    job.schedule_interval_minutes = schedule_fields.get('schedule_interval_minutes')
    job.schedule_cron = schedule_fields.get('schedule_cron')
    if arm_scheduled and schedule_fields.get('next_run'):
        job.next_run = schedule_fields['next_run']
        job.status = 'Scheduled'
        job.is_enabled = True


def job_next_run_from_row(job):
    """Compute next_run from whatever schedule columns the job carries."""
    if not job:
        return None
    from oneirodex.utils.services.scan_orchestration import (
        SCHEDULE_HOURS,
        compute_next_run,
    )

    kind = getattr(job, 'schedule_kind', None) or (
        'preset' if getattr(job, 'schedule', None) in SCHEDULE_HOURS else None
    )
    if kind == 'interval':
        return compute_next_run(
            schedule_kind='interval',
            interval_minutes=getattr(job, 'schedule_interval_minutes', None),
        )
    if kind == 'cron':
        return compute_next_run(
            schedule_kind='cron',
            cron_expr=getattr(job, 'schedule_cron', None),
        )
    if getattr(job, 'schedule', None) in SCHEDULE_HOURS:
        return compute_next_run(job.schedule)
    return None



def create_scan_job_row(
    *,
    folder_path: str,
    library_uuid: str,
    scan_mode: str = 'folders',
    remove_missing: bool = False,
    download_missing_images: bool = False,
    force_updates_extras_scan: bool = False,
    schedule=None,
    schedule_fields=None,
    status: str = 'Queued',
) -> ScanJob:
    """Persist a ScanJob row without starting work."""
    now = datetime.now(timezone.utc)
    fields = schedule_fields
    if fields is None:
        fields = normalize_schedule_fields(schedule)
    job = ScanJob(
        folders={folder_path: True},
        content_type='Games',
        status=status,
        is_enabled=True,
        last_run=now,
        library_uuid=library_uuid,
        error_message='',
        total_folders=0,
        folders_success=0,
        folders_failed=0,
        removed_count=0,
        scan_folder=folder_path,
        setting_remove=bool(remove_missing),
        setting_filefolder=(scan_mode == 'files'),
        setting_download_missing_images=bool(download_missing_images),
        setting_force_updates_extras=bool(force_updates_extras_scan),
        schedule=fields.get('schedule') if fields else (
            schedule if schedule in ('8_hours', '24_hours', '48_hours') else None
        ),
        # Only a job that starts Running has a worker in this process. A Queued
        # row is owned by nobody yet, and stamping it here would make the queue
        # look busy to the reclaim sweep.
        owner_token=PROCESS_TOKEN if status == 'Running' else None,
    )
    apply_schedule_to_job(job, fields or {})
    db.session.add(job)
    db.session.commit()
    return job


def _has_older_busy_scan(candidate: ScanJob) -> bool:
    """Whether a Running/Stopping row precedes this one in (last_run, id) order."""
    rows = db.session.execute(
        select(ScanJob.id, ScanJob.last_run)
        .where(
            ScanJob.status.in_(('Running', 'Stopping')),
            ScanJob.id != candidate.id,
        )
        .order_by(ScanJob.last_run.asc().nullsfirst(), ScanJob.id.asc())
    ).all()
    candidate_run = candidate.last_run
    if candidate_run is None:
        candidate_run = datetime.min.replace(tzinfo=timezone.utc)
    elif candidate_run.tzinfo is None:
        candidate_run = candidate_run.replace(tzinfo=timezone.utc)
    for row_id, last_run in rows:
        if last_run is None:
            last_run = datetime.min.replace(tzinfo=timezone.utc)
        elif last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        if (last_run, row_id) < (candidate_run, candidate.id):
            return True
        return False
    return False


def _start_job_thread(job: ScanJob, app, *, force_parallel: bool = False):
    """Spawn daemon thread that runs ``scan_and_add_games`` for an existing job."""
    from oneirodex.utilities import scan_and_add_games

    job_id = job.id
    folder = job.scan_folder
    library_uuid = job.library_uuid
    scan_mode = 'files' if job.setting_filefolder else 'folders'
    remove_missing = bool(job.setting_remove)
    download_missing_images = bool(job.setting_download_missing_images)
    force_updates_extras = bool(job.setting_force_updates_extras)
    schedule = job.schedule

    def _run():
        with app.app_context():
            existing = db.session.get(ScanJob, job_id)
            if not existing:
                return
            scan_and_add_games(
                folder,
                scan_mode=scan_mode,
                library_uuid=library_uuid,
                remove_missing=remove_missing,
                existing_job=existing,
                download_missing_images=download_missing_images,
                force_updates_extras_scan=force_updates_extras,
                schedule=schedule,
                force_parallel=force_parallel,
            )

    Thread(target=_run, daemon=True, name=f'oneirodex-scan-{job_id[:8]}').start()


def start_or_queue_scan(
    *,
    folder_path: str,
    library_uuid: str,
    scan_mode: str = 'folders',
    remove_missing: bool = False,
    download_missing_images: bool = False,
    force_updates_extras_scan: bool = False,
    fetch_hltb: bool = False,
    force_hltb_refetch: bool = False,
    schedule=None,
    schedule_fields=None,
    queue_policy: str = 'queue',
    allow_force: bool = False,
    app=None,
) -> dict:
    """Accept a scan request: start now, queue, force-parallel, or reject.

    Returns ``{status, job_id?, position?, message}`` where status is
    ``started`` | ``queued`` | ``rejected``.
    """
    policy = parse_queue_policy(queue_policy)
    force = policy == 'force'
    if force and not allow_force:
        return {
            'status': 'rejected',
            'job_id': None,
            'position': None,
            'message': (
                'force_parallel / queue_policy=force requires an admin session. '
                'Default policy queues the scan instead.'
            ),
        }

    flask_app = app or current_app._get_current_object()
    if schedule_fields is None:
        schedule_fields = normalize_schedule_fields(schedule)

    # Clear orphans before deciding, so the *first* request after a restart
    # starts instead of queueing. The admin status poll drains too, but only
    # once the scans page is open — a scan kicked off from anywhere else would
    # otherwise sit behind a ghost until something happened to look.
    try:
        reclaim_stale_busy_jobs()
    except Exception as exc:
        print(f'[SCAN QUEUE] Pre-start reclaim failed: {exc}')

    busy = is_scan_busy()

    if busy and not force:
        existing_queued = find_queued_for_library(library_uuid, folder_path)
        if existing_queued:
            # Keep the Queued row's schedule in sync with the latest submit —
            # dropping interval/cron here silently converts a recurring job
            # into a once-only queue entry.
            apply_schedule_to_job(existing_queued, schedule_fields)
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
            position = queue_position(existing_queued.id) or 1
            return {
                'status': 'queued',
                'job_id': existing_queued.id,
                'position': position,
                'coalesced': True,
                'message': f'{COALESCE_MESSAGE} Position {position}.',
            }
        job = create_scan_job_row(
            folder_path=folder_path,
            library_uuid=library_uuid,
            scan_mode=scan_mode,
            remove_missing=remove_missing,
            download_missing_images=download_missing_images,
            force_updates_extras_scan=force_updates_extras_scan,
            schedule=schedule,
            schedule_fields=schedule_fields,
            status='Queued',
        )
        position = queue_position(job.id) or count_queued_jobs()
        return {
            'status': 'queued',
            'job_id': job.id,
            'position': position,
            'message': f'{QUEUE_DEFAULT_MESSAGE} Position {position}.',
        }

    # Start immediately (idle, or admin force parallel).
    job = create_scan_job_row(
        folder_path=folder_path,
        library_uuid=library_uuid,
        scan_mode=scan_mode,
        remove_missing=remove_missing,
        download_missing_images=download_missing_images,
        force_updates_extras_scan=force_updates_extras_scan,
        schedule=schedule,
        schedule_fields=schedule_fields,
        status='Running',
    )

    # is_scan_busy() above is not atomic with this insert: a concurrent starter
    # (second click, or the scheduler poll) can pass the same check and both go
    # Running, silently defeating the queue policy. Re-check now that our row is
    # visible and yield to the older job — same rollback the promote path does.
    if not force:
        if _has_older_busy_scan(job):
            job.status = 'Queued'
            # Back in the queue means back to unowned — a Queued row carrying
            # this process's token would be reclaimed as a dead-owner job the
            # moment the process exits, instead of simply waiting its turn.
            job.owner_token = None
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
            else:
                position = queue_position(job.id) or count_queued_jobs()
                return {
                    'status': 'queued',
                    'job_id': job.id,
                    'position': position,
                    'message': f'{QUEUE_DEFAULT_MESSAGE} Position {position}.',
                }

    try:
        from oneirodex.utils.event_bus import publish_scan_event
        publish_scan_event(job.id, 'Running')
    except Exception:
        pass

    # HLTB flags are request-scoped for the worker thread (not ScanJob columns).
    job_id = job.id

    def _run_with_hltb():
        with flask_app.app_context():
            from oneirodex.utilities import scan_and_add_games

            existing = db.session.get(ScanJob, job_id)
            if not existing:
                return
            scan_and_add_games(
                folder_path,
                scan_mode=scan_mode,
                library_uuid=library_uuid,
                remove_missing=remove_missing,
                existing_job=existing,
                download_missing_images=download_missing_images,
                force_updates_extras_scan=force_updates_extras_scan,
                fetch_hltb=fetch_hltb,
                force_hltb_refetch=force_hltb_refetch,
                schedule=schedule,
                force_parallel=force,
            )

    Thread(
        target=_run_with_hltb,
        daemon=True,
        name=f'oneirodex-scan-{job_id[:8]}',
    ).start()

    if force and busy:
        message = (
            f'Scan started in parallel with a running job (job {job.id[:8]}…). '
            f'{FORCE_PARALLEL_RISK}'
        )
    else:
        message = f'Scan started (job {job.id[:8]}…).'

    return {
        'status': 'started',
        'job_id': job.id,
        'position': None,
        'message': message,
    }


def reclaim_stale_busy_jobs(
    *,
    stopping_after_seconds: int = STALE_STOPPING_SECONDS,
    running_after_seconds: int = STALE_RUNNING_SECONDS,
) -> int:
    """Mark orphaned Running/Stopping jobs Failed so the FIFO queue can drain.

    Returns the number of jobs reclaimed.
    """
    now = datetime.now(timezone.utc)
    stopping_cutoff = now - timedelta(seconds=max(60, int(stopping_after_seconds)))
    running_cutoff = now - timedelta(seconds=max(60, int(running_after_seconds)))

    busy_jobs = db.session.execute(
        select(ScanJob).where(ScanJob.status.in_(('Running', 'Stopping')))
    ).scalars().all()

    reclaimed = 0
    for job in busy_jobs:
        # Ownership first: if the process that was running this job is gone, the
        # job is orphaned no matter how recently it reported progress, and
        # waiting out STALE_RUNNING_SECONDS only keeps the queue wedged. This is
        # the common case — a restart or a kill mid-scan — and it used to cost
        # six hours of "scan queued, nothing happens".
        if not owner_is_alive(job.owner_token, job.last_run):
            job.status = 'Failed'
            job.is_enabled = False
            job.current_processing = None
            job.error_message = (
                (job.error_message or '').strip()
                or 'Scan owner process is no longer running; reclaimed so queued scans can start.'
            )
            reclaimed += 1
            continue

        anchor = job.last_progress_update or job.last_run
        if anchor is None:
            # Never progressed and no last_run — treat as immediately reclaimable Stopping,
            # but give Running a chance unless it has been Queued→Running without a worker.
            if job.status != 'Stopping':
                continue
            anchor = now - timedelta(seconds=stopping_after_seconds + 1)
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)

        if job.status == 'Stopping' and anchor <= stopping_cutoff:
            job.status = 'Failed'
            job.is_enabled = False
            job.current_processing = None
            job.error_message = (
                (job.error_message or '').strip()
                or 'Scan stuck in Stopping; reclaimed so queued scans can start.'
            )
            reclaimed += 1
        elif job.status == 'Running' and anchor <= running_cutoff:
            job.status = 'Failed'
            job.is_enabled = False
            job.current_processing = None
            job.error_message = (
                (job.error_message or '').strip()
                or 'Scan stuck in Running without progress; reclaimed so queued scans can start.'
            )
            reclaimed += 1

    if reclaimed:
        try:
            db.session.commit()
            print(f'[SCAN QUEUE] Reclaimed {reclaimed} stale Running/Stopping job(s)')
        except SQLAlchemyError as exc:
            db.session.rollback()
            print(f'[SCAN QUEUE] Failed to reclaim stale jobs: {exc}')
            return 0
    return reclaimed


def promote_next_queued_scan(app=None) -> ScanJob | None:
    """If no scan is busy, promote the oldest Queued job to Running and start it.

    Safe to call after a job reaches a terminal state. Returns the promoted job
    or None when nothing was started.
    """
    if is_scan_busy():
        return None

    next_job = db.session.execute(
        select(ScanJob)
        .where(ScanJob.status == 'Queued')
        .order_by(ScanJob.last_run.asc().nullsfirst(), ScanJob.id.asc())
        .limit(1)
    ).scalars().first()
    if not next_job:
        return None

    # Conditional claim: only promote if this row is still Queued.
    now = datetime.now(timezone.utc)
    claimed = db.session.execute(
        update(ScanJob)
        .where(
            ScanJob.id == next_job.id,
            ScanJob.status == 'Queued',
        )
        .values(
            status='Running',
            last_run=now,
            error_message='',
            is_enabled=True,
            current_processing=None,
            # This process is about to start the thread, so it owns the job.
            owner_token=PROCESS_TOKEN,
        )
    )
    rowcount = claimed.rowcount or 0
    try:
        db.session.commit()
    except SQLAlchemyError as exc:
        db.session.rollback()
        print(f'[SCAN QUEUE] Failed to promote queued job: {exc}')
        return None

    if rowcount != 1:
        return None

    db.session.expire_all()
    promoted = db.session.get(ScanJob, next_job.id)
    if not promoted or promoted.status != 'Running':
        return None

    # Another worker may have started in parallel — roll back claim if so.
    if _has_older_busy_scan(promoted):
        promoted.status = 'Queued'
        # See the matching rollback in start_or_queue_scan: unowned again.
        promoted.owner_token = None
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
        print(
            f'[SCAN QUEUE] Rolled back promote of {promoted.id} — another job is busy'
        )
        return None

    try:
        from oneirodex.utils.event_bus import publish_scan_event
        publish_scan_event(promoted.id, 'Running')
    except Exception:
        pass

    flask_app = app or current_app._get_current_object()
    print(f'[SCAN QUEUE] Promoting queued job {promoted.id} for {promoted.scan_folder}')
    _start_job_thread(promoted, flask_app, force_parallel=False)
    return promoted


def drain_scan_queue(app=None) -> ScanJob | None:
    """Reclaim stale busy jobs then promote the next Queued scan (safety drain)."""
    try:
        reclaim_stale_busy_jobs()
    except Exception as exc:
        print(f'[SCAN QUEUE] Stale reclaim failed: {exc}')
    try:
        return promote_next_queued_scan(app)
    except Exception as exc:
        print(f'[SCAN QUEUE] Promote failed: {exc}')
        return None


def maybe_drain_scan_queue(app=None) -> ScanJob | None:
    """Safety drain for status / Ops polls — skip while a scan is busy.

    Admin Libraries & scans polls ``GET /api/scan_jobs_status`` every few
    seconds, and Ops hits this on its ~15s summary. Running reclaim+promote on
    every tick SELECT/UPDATEs ``scan_jobs`` against the live worker and is what
    made the admin UI freeze for tens of minutes on Unraid. The scheduler still
    drains ~60s. Idle+Queued still drains here so a missed promote recovers
    without waiting a minute.
    """
    if is_scan_busy():
        return None
    return drain_scan_queue(app)


def enqueue_library_refresh_jobs(libraries_with_folders: list[dict]) -> dict:
    """Create Queued ScanJobs for refresh-all when a scan is already busy.

    ``libraries_with_folders`` items: ``{uuid, name, folder}``.
    Coalesces when the same library folder is already Queued.
    """
    created = []
    coalesced = 0
    for item in libraries_with_folders:
        existing = find_queued_for_library(item['uuid'], item['folder'])
        if existing:
            coalesced += 1
            created.append({
                'uuid': item['uuid'],
                'name': item.get('name'),
                'folder': item['folder'],
                'job_id': existing.id,
                'position': queue_position(existing.id),
                'coalesced': True,
            })
            continue
        job = create_scan_job_row(
            folder_path=item['folder'],
            library_uuid=item['uuid'],
            scan_mode='folders',
            status='Queued',
        )
        created.append({
            'uuid': item['uuid'],
            'name': item.get('name'),
            'folder': item['folder'],
            'job_id': job.id,
            'position': queue_position(job.id),
        })
    msg = (
        f'{len(created)} library refresh scan(s) queued (FIFO). '
        'They start when the current Running/Stopping job finishes.'
    )
    if coalesced:
        msg += f' {coalesced} already-queued library folder(s) coalesced.'
    return {
        'status': 'queued',
        'jobs': created,
        'count': len(created),
        'coalesced_count': coalesced,
        'message': msg,
    }
