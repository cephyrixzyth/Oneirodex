# /oneirodex/routes_apis/scan.py -- scan jobs, library scan/refresh, path handoff.
# The unmatched-folder surface moved to scan_unmatched_rows / scan_unmatched /
# scan_unmatched_edit in the v11 cycle (H-D.4); importing this module still
# registers all of it.
import os

from oneirodex.utils.api_response import api_error, api_ok
from flask import jsonify, current_app, request
from flask_login import login_required
from oneirodex import db
from oneirodex.models import ScanJob, Library
from sqlalchemy import or_, select
from oneirodex.utils.auth import admin_required
from oneirodex.utils.scan_job_timing import (
    compute_scan_job_timing,
    parse_scan_job_status_filter,
)
from oneirodex.utils.scan_queue import maybe_drain_scan_queue, queue_position
from . import apis_bp
from . import scan_unmatched_rows  # noqa: F401  -- registers its routes on apis_bp
from . import scan_unmatched  # noqa: F401  -- registers its routes on apis_bp
from . import scan_unmatched_edit  # noqa: F401  -- registers its routes on apis_bp


def _parse_scan_jobs_list_filters():
    """Query params for GET /api/scan_jobs_status. Returns filters dict."""
    statuses = parse_scan_job_status_filter(request.args.get('status'))
    return {
        'statuses': statuses,
        'library_uuid': (request.args.get('library_uuid') or '').strip(),
        'q': (request.args.get('q') or request.args.get('name') or '').strip(),
    }


def _query_scan_jobs(filters: dict):
    """Filtered ScanJob list (server-side). Outerjoin Library for name substring."""
    query = (
        select(ScanJob)
        .outerjoin(Library, ScanJob.library_uuid == Library.uuid)
        .order_by(ScanJob.last_run.desc().nullslast())
    )
    statuses = filters.get('statuses') or []
    if statuses:
        query = query.where(ScanJob.status.in_(statuses))
    library_uuid = filters.get('library_uuid') or ''
    if library_uuid:
        query = query.where(ScanJob.library_uuid == library_uuid)
    q = filters.get('q') or ''
    if q:
        pattern = f'%{q}%'
        query = query.where(or_(
            ScanJob.scan_folder.ilike(pattern),
            Library.name.ilike(pattern),
        ))
    return db.session.execute(query).scalars().unique().all()


def _scan_job_status_row(job, *, queue_position_fn=None) -> dict:
    folders_success = job.folders_success or 0
    folders_failed = job.folders_failed or 0
    total_folders = job.total_folders or 0
    timing = compute_scan_job_timing(job)
    processed = timing['folders_processed']
    row = {
        'id': job.id,
        'library_name': job.library.name if job.library else 'No Library Assigned',
        'library_uuid': job.library_uuid,
        'folders': job.folders,
        'status': job.status,
        'total_folders': total_folders,
        'folders_success': folders_success,
        'folders_failed': folders_failed,
        'folders_processed': processed,
        'removed_count': job.removed_count or 0,
        'scan_folder': job.scan_folder,
        'setting_remove': bool(job.setting_remove),
        'setting_filefolder': bool(job.setting_filefolder),
        'setting_download_missing_images': bool(job.setting_download_missing_images),
        'current_processing': job.current_processing,
        'error_message': job.error_message or '',
        'last_run': job.last_run.strftime('%Y-%m-%d %H:%M:%S') if job.last_run else 'Not Available',
        'last_update': job.last_progress_update.isoformat() if job.last_progress_update else None,
        'next_run': job.next_run.strftime('%Y-%m-%d %H:%M:%S') if job.next_run else 'Not Scheduled',
        'progress_percentage': round(processed / total_folders * 100, 1) if total_folders > 0 else 0,
        # Wave 18 timing — started_at == last_run (no separate create column)
        'started_at': timing['started_at'],
        'created_at': timing['created_at'],
        'elapsed_seconds': timing['elapsed_seconds'],
        'eta_seconds': timing['eta_seconds'],
        'stalled': timing['stalled'],
        'elapsed_label': timing['elapsed_label'],
        'eta_label': timing['eta_label'],
    }
    if job.status == 'Queued' and queue_position_fn is not None:
        row['queue_position'] = queue_position_fn(job.id)
    return row


@apis_bp.route('/scan_jobs_status', methods=['GET'])
@login_required
@admin_required
def scan_jobs_status():
    # Safety drain only when idle+Queued. A Running scan must not share this
    # lock with a 3s admin poll — see maybe_drain_scan_queue.
    try:
        maybe_drain_scan_queue(current_app._get_current_object())
    except Exception:
        pass

    filters = _parse_scan_jobs_list_filters()
    jobs = _query_scan_jobs(filters)
    jobs_data = [_scan_job_status_row(job, queue_position_fn=queue_position) for job in jobs]
    return jsonify(jobs_data)


@apis_bp.route('/path/open', methods=['GET'])
@login_required
@admin_required
def open_path_info():
    """
    Safe path-string endpoint for Desktop/OS explorer handoff.

    Returns the path only — does not open Auto Scan or mutate filesystem.
    Desktop owns revealing the folder in the host explorer.
    """
    raw = (request.args.get('path') or request.args.get('full_disk_path') or '').strip()
    if not raw:
        return api_error('path required', code='bad_request')
    if len(raw) > 2048:
        return api_error('path too long', code='bad_request')

    exists = False
    try:
        exists = os.path.exists(raw)
    except OSError:
        exists = False

    return jsonify({
        'path': raw,
        'exists': exists,
        'is_dir': os.path.isdir(raw) if exists else False,
        'basename': os.path.basename(raw.rstrip('\\/')) if raw else None,
        'open_via': 'desktop',
        'note': 'Server returns path string only; Desktop companion opens host explorer.',
    })


@apis_bp.route('/admin/libraries/scan', methods=['POST'])
@login_required
@admin_required
def start_library_scan():
    """Start or queue a library scan with an honest JSON response.

    Body/query:
      - library_uuid (required)
      - folder (optional; defaults to library.last_scan_folder)
      - scan_mode: folders|files (default folders)
      - remove_missing, download_missing_images, force_updates_extras (bools)
      - force_parallel / queue_policy=force — admin-only overlap (risk in message)
    """
    from oneirodex.utils.scan_queue import (
        FORCE_PARALLEL_RISK,
        parse_force_parallel,
        parse_queue_policy,
        start_or_queue_scan,
    )

    data = request.get_json(silent=True) or {}
    library_uuid = (
        data.get('library_uuid')
        or request.form.get('library_uuid')
        or request.args.get('library_uuid')
    )
    if not library_uuid:
        return api_error(
            'library_uuid is required',
            code='bad_request',
            body_status='rejected',
            job_id=None,
            position=None,
        )

    library = db.session.execute(
        select(Library).filter_by(uuid=library_uuid)
    ).scalars().first()
    if not library:
        return api_error(
            'Library not found',
            code='not_found',
            body_status='rejected',
            job_id=None,
            position=None,
        )

    use_library_root = data.get('use_library_root') is True
    if 'use_library_root' in data and not isinstance(data.get('use_library_root'), bool):
        return api_error('use_library_root must be a boolean', code='bad_request', body_status='rejected', job_id=None, position=None)
    if use_library_root:
        folder = data.get('folder', '')
    else:
        folder = (
            data.get('folder')
            or request.form.get('folder')
            or request.args.get('folder')
            or library.last_scan_folder
        )
    if not isinstance(folder, str):
        return api_error('folder must be a string', code='bad_request', body_status='rejected', job_id=None, position=None)
    if not folder and not use_library_root:
        return api_error(
            (
                'No folder provided and library has no last_scan_folder. '
                'Run one Auto Scan first or pass folder.'
            ),
            code='bad_request',
            body_status='rejected',
            job_id=None,
            position=None,
        )

    # Match the Auto Scan form's root-relative picker contract while keeping
    # old callers that send an absolute `folder` path byte-for-byte compatible.
    # Resolving and checking the path at the API boundary gives native clients
    # the same allowlist protection as the classic form handler.
    from oneirodex.utils.library_roots import resolve_scan_path
    from oneirodex.utils.security import get_allowed_base_directories, is_safe_path
    folder = folder.strip() if isinstance(folder, str) else ''
    library_root = data.get('library_root')
    if library_root is not None and not isinstance(library_root, str):
        return api_error('library_root must be a string', code='bad_request', body_status='rejected', job_id=None, position=None)
    resolved_folder, root_error = resolve_scan_path(
        folder, library_root, current_app,
    )
    if root_error:
        return api_error('Unknown scan location', code='bad_request', body_status='rejected', job_id=None, position=None)
    allowed_bases = get_allowed_base_directories(current_app)
    if not allowed_bases:
        return api_error('Scan locations are not configured', code='unavailable', body_status='rejected', job_id=None, position=None)
    safe, _path_error = is_safe_path(resolved_folder, allowed_bases)
    if not safe:
        return api_error('Access denied for this scan location', code='forbidden', body_status='rejected', job_id=None, position=None)
    scan_mode = (
        data.get('scan_mode')
        or request.form.get('scan_mode')
        or request.args.get('scan_mode')
        or 'folders'
    )
    if scan_mode not in ('auto', 'folders', 'files'):
        return api_error('scan_mode must be auto, folders, or files', code='bad_request', body_status='rejected', job_id=None, position=None)
    if scan_mode == 'auto':
        from oneirodex.utils.services.scan_orchestration import resolve_scan_mode_for_path
        scan_mode = resolve_scan_mode_for_path(resolved_folder, scan_mode)
    force_raw = (
        data.get('force_parallel')
        if 'force_parallel' in data
        else (request.form.get('force_parallel') or request.args.get('force_parallel'))
    )
    policy_raw = (
        data.get('queue_policy')
        if 'queue_policy' in data
        else (request.form.get('queue_policy') or request.args.get('queue_policy'))
    )
    queue_policy = parse_queue_policy(policy_raw, force_parallel=force_raw)

    from oneirodex.utils.scan_queue import normalize_schedule_fields
    schedule_value = data.get('schedule')
    if schedule_value is not None and not isinstance(schedule_value, str):
        return api_error('schedule must be a string', code='bad_request', body_status='rejected', job_id=None, position=None)
    schedule = (schedule_value or '').strip() or None
    interval_unit = data.get('schedule_interval_unit')
    cron_expr = data.get('schedule_cron')
    if interval_unit is not None and not isinstance(interval_unit, str):
        return api_error('schedule_interval_unit must be a string', code='bad_request', body_status='rejected', job_id=None, position=None)
    if cron_expr is not None and not isinstance(cron_expr, str):
        return api_error('schedule_cron must be a string', code='bad_request', body_status='rejected', job_id=None, position=None)
    schedule_fields = normalize_schedule_fields(
        schedule,
        interval_value=data.get('schedule_interval_value'),
        interval_unit=interval_unit,
        cron_expr=cron_expr,
    )
    if schedule_fields.get('error'):
        return api_error(schedule_fields['error'], code='bad_request', body_status='rejected', job_id=None, position=None)

    def _bool(key, default=False):
        if key in data:
            raw = data.get(key)
        else:
            raw = request.form.get(key) or request.args.get(key)
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw != 0
        if isinstance(raw, str):
            return raw.strip().lower() in ('1', 'true', 'yes', 'on')
        return False

    result = start_or_queue_scan(
        folder_path=resolved_folder,
        library_uuid=library_uuid,
        scan_mode=scan_mode,
        remove_missing=_bool('remove_missing'),
        download_missing_images=_bool('download_missing_images'),
        force_updates_extras_scan=_bool('force_updates_extras', _bool('force_updates_extras_scan')),
        fetch_hltb=_bool('fetch_hltb'),
        force_hltb_refetch=_bool('force_hltb_refetch'),
        schedule=schedule,
        schedule_fields=schedule_fields,
        queue_policy=queue_policy,
        allow_force=True,  # route is @admin_required
        app=current_app._get_current_object(),
    )
    http = 200 if result['status'] in ('started', 'queued') else 409
    if result['status'] == 'started' and parse_force_parallel(force_raw):
        result = dict(result)
        result.setdefault('risk', FORCE_PARALLEL_RISK)
    if result['status'] in ('started', 'queued'):
        return api_ok(result, status=http)
    extras = {
        key: value for key, value in result.items()
        if key not in ('ok', 'error', 'error_code', 'message', 'status')
    }
    return api_error(
        result.get('message') or 'Scan rejected',
        code='conflict',
        status=http,
        body_status='rejected',
        **extras,
    )


@apis_bp.route('/admin/libraries/refresh_all', methods=['POST'])
@login_required
@admin_required
def refresh_all_libraries():
    """Queue a re-scan for each library that has a remembered last_scan_folder.

    Default: enqueue FIFO ``Queued`` jobs (and promote the first when idle).
    Pass ``force_parallel=true`` / ``queue_policy=force`` (admin) to start a
    sequential refresh thread alongside any Running job (NAS CPU risk).
    """
    from threading import Thread
    from oneirodex.utilities import scan_and_add_games
    from oneirodex.utils.scan_queue import (
        FORCE_PARALLEL_RISK,
        enqueue_library_refresh_jobs,
        is_scan_busy,
        parse_queue_policy,
        promote_next_queued_scan,
    )

    data = request.get_json(silent=True) or {}
    force_raw = (
        data.get('force_parallel')
        if 'force_parallel' in data
        else (request.form.get('force_parallel') or request.args.get('force_parallel'))
    )
    policy_raw = (
        data.get('queue_policy')
        if 'queue_policy' in data
        else (request.form.get('queue_policy') or request.args.get('queue_policy'))
    )
    force = parse_queue_policy(policy_raw, force_parallel=force_raw) == 'force'

    libraries = db.session.execute(select(Library).order_by(Library.name.asc())).scalars().all()
    queue = [
        {'uuid': lib.uuid, 'name': lib.name, 'folder': lib.last_scan_folder}
        for lib in libraries
        if lib.last_scan_folder
    ]
    if not queue:
        return api_error(
            'No libraries have a remembered scan folder yet.',
            code='bad_request',
            body_status='rejected',
            body_error=(
                'No libraries have a remembered scan folder yet. '
                'Run one Auto Scan per library first.'
            ),
            queued=[],
        )

    busy = is_scan_busy()

    # Force-parallel: start sequential worker even while another scan is Running.
    if force:
        app = current_app._get_current_object()

        def _run_queue():
            with app.app_context():
                for item in queue:
                    try:
                        scan_and_add_games(
                            item['folder'],
                            scan_mode='folders',
                            library_uuid=item['uuid'],
                            remove_missing=False,
                            force_parallel=True,
                        )
                    except Exception as exc:
                        print(f"[REFRESH ALL] Failed for {item['name']}: {exc}")

        Thread(target=_run_queue, daemon=True, name='oneirodex-refresh-all').start()
        message = (
            f'Refresh-all started for {len(queue)} libraries '
            f'(sequential worker, force_parallel). {FORCE_PARALLEL_RISK}'
        )
        return api_ok({
            'status': 'started',
            'queued': queue,
            'count': len(queue),
            'message': message,
            'risk': FORCE_PARALLEL_RISK,
        })

    # Default: persist FIFO Queued jobs; promote first when idle.
    payload = enqueue_library_refresh_jobs(queue)
    if not busy:
        promoted = promote_next_queued_scan(current_app._get_current_object())
        if promoted:
            payload['status'] = 'started'
            payload['job_id'] = promoted.id
            payload['message'] = (
                f'Refresh-all: started first of {len(queue)} queued library scan(s); '
                'remaining stay Queued (FIFO).'
            )
            # position 1 was promoted; remaining positions shift
            for item in payload.get('jobs') or []:
                if item.get('job_id') == promoted.id:
                    item['position'] = None
                    item['status'] = 'started'
                elif item.get('position'):
                    item['position'] = max(1, int(item['position']) - 1)
    return api_ok(payload)


