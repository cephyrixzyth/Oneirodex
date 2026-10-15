from datetime import datetime, timedelta, timezone
from time import perf_counter
from urllib.parse import urlparse

from sqlalchemy import func, or_, select, text

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import (
    ClientDevice,
    DownloadRequest,
    Game,
    GameServer,
    Library,
    ScanJob,
    SystemEvents,
    UnmatchedFolder,
    User,
)
from oneirodex.utils.build_identity import build_identity
from oneirodex.utils.game_servers import probe_server_health
from oneirodex.utils.health_probes import build_readiness
from oneirodex.utils.livekit_rtc import livekit_config, livekit_enabled
from oneirodex.utils.malware_scan import malware_scan_enabled, module_status
from oneirodex.utils.ops_issues import derive_issues
from oneirodex.utils.ops_network import get_network_stats
from oneirodex.utils.scan_job_timing import compute_scan_job_timing
from oneirodex.utils.scan_queue import maybe_drain_scan_queue
from oneirodex.utils.status import get_config_values, get_system_info
from oneirodex.utils.system_stats import (
    get_cpu_usage,
    get_gpu_usage,
    get_disk_usage,
    get_games_folder_usage,
    get_load_average,
    get_memory_usage,
    get_process_memory,
)
from oneirodex.utils.uptime import (
    get_formatted_app_uptime,
    get_formatted_system_uptime,
)

# Companions are "online" if they heartbeated within this window.
_COMPANION_ONLINE_MINUTES = 3

# Compose/Unraid mounts games (and the base folder that contains them) RO at
# /storage — write is not required for scans, only for uploads/image paths.
_READ_ONLY_OK_PATH_KEYS = frozenset({
    'DATA_FOLDER_GAMES',
    'BASE_FOLDER_POSIX',
    'BASE_FOLDER_WINDOWS',
})


def _write_required(key):
    """Extra scan locations are read-only for the same reason /storage is."""
    from oneirodex.utils.status import LIBRARY_ROOT_KEY_PREFIX

    return key not in _READ_ONLY_OK_PATH_KEYS and not key.startswith(LIBRARY_ROOT_KEY_PREFIX)


def _path_problems(config_values):
    """Return configured paths that are missing, unreadable, or wrongly unwritable.

    Games scan root (and its base folder) may be read-only (Unraid
    ``/storage:ro``); only missing / unreadable counts as a problem for those
    keys. Uploads / image paths still require write.
    """
    problems = []
    for key, details in (config_values or {}).items():
        if not details.get('exists', False):
            problems.append({'key': key, 'reason': 'missing'})
        elif not details.get('read', False):
            problems.append({'key': key, 'reason': 'not readable'})
        elif _write_required(key) and not details.get('write', False):
            problems.append({'key': key, 'reason': 'not writable'})
    return problems


def _library_pulse():
    """Return counts that describe the state of the game library."""
    from oneirodex.utils.library_health import build_library_health_pulse

    pulse = {
        'libraries': db.session.execute(select(func.count(Library.uuid))).scalar(),
        'games': db.session.execute(select(func.count(Game.id))).scalar(),
        'unmatched_folders': db.session.execute(
            select(func.count(UnmatchedFolder.id))
        ).scalar(),
        'download_requests_open': db.session.execute(
            select(func.count(DownloadRequest.id)).where(
                DownloadRequest.status.in_(('pending', 'processing'))
            )
        ).scalar(),
    }
    try:
        pulse['health'] = build_library_health_pulse()
    except Exception as exc:
        # Keep pulse usable when health SQL fails — never tank Ops poll.
        pulse['health'] = {
            'score': None,
            'grade': None,
            'factors': [],
            'games': pulse.get('games') or 0,
            'thin': True,
            'note': f'library health unavailable: {exc}',
            'checked_at': datetime.now(timezone.utc).isoformat(),
        }
    return pulse


def _scan_job_payload(job):
    """Serialize a ScanJob for Ops glance (~15s poll) — honest folder counters + timing."""
    total = job.total_folders or 0
    success = job.folders_success or 0
    failed = job.folders_failed or 0
    timing = compute_scan_job_timing(job)
    completed = timing['folders_processed']
    progress = round(completed * 100 / total) if total > 0 else 0
    job_id = job.id or ''
    last_update = job.last_progress_update
    return {
        'id': job_id,
        'id_short': job_id[:8] if job_id else None,
        'library': job.library.name if job.library else None,
        # Preserve ScanJob enum casing (Running / Stopping / Cancelled / Completed / …)
        'status': job.status,
        'folders_success': success,
        'folders_failed': failed,
        'folders_processed': completed,
        'total_folders': total,
        'current_processing': job.current_processing,
        # Why a job failed (GT-B38).
        #
        # This payload already carried every other thing an operator needs to
        # read a scan — counts, current folder, elapsed, ETA, stalled — and
        # dropped the one that explains a job that stopped. So the Ops console
        # could show that a scan failed and never why, including when the
        # ownership sweep reclaimed it. Third surface with the same gap; see
        # ui-debt-log UID-031.
        #
        # Not a new disclosure: /api/scan_jobs_status has always returned this
        # field to the same admin-only audience.
        'error_message': job.error_message or None,
        'last_progress_update': last_update.isoformat() if last_update else None,
        # Wave 18 timing (started_at == last_run; created_at always null)
        'started_at': timing['started_at'],
        'created_at': timing['created_at'],
        'elapsed_seconds': timing['elapsed_seconds'],
        'eta_seconds': timing['eta_seconds'],
        'stalled': timing['stalled'],
        'elapsed_label': timing['elapsed_label'],
        'eta_label': timing['eta_label'],
        # Backward-compatible aliases for existing Ops / Dashboard tiles
        'progress': progress,
        'errors': failed,
    }


def _scan_snapshot(app=None):
    """Return active + queued + recent scan jobs (with live counters) and failure count."""
    # Safety drain only when idle+Queued. Skip while Running so a 15s Ops poll
    # does not contend with the live worker (same gate as scan_jobs_status).
    if app is None:
        # Preserve the Flask route's historical queue-drain behavior while
        # keeping native FastAPI callers independent of a current_app proxy.
        try:
            from flask import current_app

            app = current_app._get_current_object()
        except (ImportError, RuntimeError):
            app = None
    if app is not None:
        try:
            maybe_drain_scan_queue(app)
        except Exception:
            pass

    active_jobs = db.session.execute(
        select(ScanJob)
        .where(ScanJob.status.in_(('Running', 'Stopping')))
        .order_by(ScanJob.last_progress_update.desc())
    ).scalars().all()

    queued_jobs = db.session.execute(
        select(ScanJob)
        .where(ScanJob.status == 'Queued')
        .order_by(ScanJob.last_run.asc().nullsfirst(), ScanJob.id.asc())
    ).scalars().all()

    jobs = [_scan_job_payload(job) for job in active_jobs]
    for idx, job in enumerate(queued_jobs, start=1):
        payload = _scan_job_payload(job)
        payload['queue_position'] = idx
        jobs.append(payload)
    active_ids = {job.id for job in active_jobs}
    queued_ids = {job.id for job in queued_jobs}

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    # Recent terminal jobs so Unraid testing can report progress after a scan ends.
    recent_jobs = db.session.execute(
        select(ScanJob)
        .where(
            ScanJob.status.in_(('Completed', 'Cancelled', 'Failed')),
            or_(
                ScanJob.last_progress_update >= since,
                ScanJob.last_run >= since,
            ),
        )
        .order_by(
            func.coalesce(ScanJob.last_progress_update, ScanJob.last_run).desc()
        )
        .limit(5)
    ).scalars().all()

    for job in recent_jobs:
        if job.id in active_ids or job.id in queued_ids:
            continue
        jobs.append(_scan_job_payload(job))

    failure_count = db.session.execute(
        select(func.count(ScanJob.id)).where(
            or_(
                (ScanJob.status == 'Failed') & (ScanJob.last_run >= since),
                (ScanJob.status == 'Running') & ScanJob.error_message.isnot(None),
                ScanJob.status.in_(('Running', 'Stopping'))
                & (ScanJob.folders_failed > 0),
            )
        )
    ).scalar()

    return {
        'active_count': len(active_jobs),
        'queued_count': len(queued_jobs),
        'jobs': jobs,
        'failure_count': failure_count,
    }


def _recent_errors():
    """Return recent error events and their count over the last day."""
    error_filter = or_(
        SystemEvents.event_level.in_(('error', 'critical')),
        SystemEvents.event_type == 'error',
    )
    events = db.session.execute(
        select(SystemEvents)
        .where(
            error_filter,
            SystemEvents.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24),
        )
        .order_by(SystemEvents.timestamp.desc())
        .limit(10)
    ).scalars().all()

    recent_error_count = db.session.execute(
        select(func.count(SystemEvents.id)).where(
            error_filter,
            SystemEvents.timestamp >= datetime.now(timezone.utc) - timedelta(hours=24),
        )
    ).scalar()

    return (
        [
            {
                'id': event.id,
                'timestamp': event.timestamp.isoformat() if event.timestamp else None,
                'event_type': event.event_type,
                'text': event.event_text,
            }
            for event in events
        ],
        recent_error_count,
    )


def _section(section_name, getter):
    """Return a dashboard section or a safe error for failed collection."""
    try:
        return getter(), None
    except Exception as exc:
        print(f'Unable to collect operations {section_name} section: {exc}')
        return None, f'{section_name.replace("_", " ").title()} data unavailable'


def _livekit_pulse():
    """Flag + config presence + best-effort TCP reachability (no Discord)."""
    import socket

    enabled = livekit_enabled()
    cfg = livekit_config()
    url = cfg.get('url') or ''
    keys_set = bool(cfg.get('api_key') and cfg.get('api_secret'))
    host = None
    port = None
    reachable = None
    error = None
    if url:
        parsed = urlparse(url if '://' in url else f'ws://{url}')
        host = parsed.hostname
        port = parsed.port or (7880 if parsed.scheme in ('ws', 'http', '') else 443)
        if host:
            try:
                with socket.create_connection((host, int(port)), timeout=1.5):
                    reachable = True
            except OSError as exc:
                reachable = False
                error = str(exc)
    configured = bool(enabled and url and keys_set)
    return {
        'enabled': enabled,
        'configured': configured,
        'url_set': bool(url),
        'keys_set': keys_set,
        'reachable': reachable,
        'error': error,
        'note': (
            None
            if configured
            else 'Enable LiveKit + set LIVEKIT_URL/API_KEY/SECRET; use compose --profile livekit'
        ),
    }


def _malware_pulse():
    """Reuse malware module_status (ClamAV ping + heuristics flags)."""
    status = module_status()
    clam = status.get('clamav') or {}
    clamav_reachable = clam.get('reachable')
    if clamav_reachable is None:
        clamav_reachable = clam.get('available')
    return {
        'enabled': status.get('enabled'),
        'block_on_hit': status.get('block_on_hit'),
        'clamav_reachable': clamav_reachable,
        'clamav_version': clam.get('version'),
        'clamav_error': clam.get('error'),
        'heuristics': status.get('heuristics') or {},
    }


def list_client_devices(*, limit: int = 200) -> dict:
    """Per-device rows behind the Ops "Companions" tile (TC-4, v11 H-T).

    ``_companion_pulse`` answers "how many"; this answers "which" -- the
    operator's device list. One row per ``ClientDevice`` (companion, thin
    seat, browser shell), newest heartbeat first, with the owning user's name
    and an ``online`` flag on the same window the tile uses, so the two never
    disagree. A device shows up after its first heartbeat with a
    ``device_kind``; a seat that never sent one is not a device here.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=_COMPANION_ONLINE_MINUTES)
    rows = db.session.execute(
        select(ClientDevice, User.name)
        .join(User, User.id == ClientDevice.user_id)
        .order_by(ClientDevice.last_seen_at.desc())
        .limit(max(1, min(int(limit or 200), 1000)))
    ).all()
    devices = []
    for device, user_name in rows:
        seen = device.last_seen_at
        if seen is not None and seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        row = device.to_dict()
        row.update({
            'user_id': device.user_id,
            'user_name': user_name,
            'online': bool(seen and seen >= since),
        })
        devices.append(row)
    return {
        'devices': devices,
        'count': len(devices),
        'window_minutes': _COMPANION_ONLINE_MINUTES,
    }


def _companion_pulse():
    """Count companion devices seen recently via heartbeat + last-seen buckets."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=_COMPANION_ONLINE_MINUTES)
    since_1h = now - timedelta(hours=1)
    since_24h = now - timedelta(hours=24)

    online = db.session.execute(
        select(func.count(ClientDevice.id)).where(ClientDevice.last_seen_at >= since)
    ).scalar() or 0
    total = db.session.execute(select(func.count(ClientDevice.id))).scalar() or 0
    within_1h = db.session.execute(
        select(func.count(ClientDevice.id)).where(ClientDevice.last_seen_at >= since_1h)
    ).scalar() or 0
    within_24h = db.session.execute(
        select(func.count(ClientDevice.id)).where(ClientDevice.last_seen_at >= since_24h)
    ).scalar() or 0
    newest = db.session.execute(select(func.max(ClientDevice.last_seen_at))).scalar()

    registered_by_kind = dict(
        db.session.execute(
            select(ClientDevice.device_kind, func.count(ClientDevice.id)).group_by(
                ClientDevice.device_kind
            )
        ).all()
    )
    online_by_kind = dict(
        db.session.execute(
            select(ClientDevice.device_kind, func.count(ClientDevice.id))
            .where(ClientDevice.last_seen_at >= since)
            .group_by(ClientDevice.device_kind)
        ).all()
    )
    by_kind = {}
    for kind in sorted({*(registered_by_kind.keys()), *(online_by_kind.keys())}):
        label = kind or 'companion'
        by_kind[label] = {
            'registered': int(registered_by_kind.get(kind) or 0),
            'online': int(online_by_kind.get(kind) or 0),
        }

    return {
        'online': online,
        'registered': total,
        'window_minutes': _COMPANION_ONLINE_MINUTES,
        'by_kind': by_kind,
        'last_seen': {
            'newest': newest.isoformat() if newest else None,
            'within_1h': within_1h,
            'within_24h': within_24h,
            'stale': max(0, total - online),
        },
    }


def _db_ping_ms():
    """Cheap SELECT 1 latency in milliseconds; None when DB unreachable."""
    try:
        started = perf_counter()
        db.session.execute(text('SELECT 1'))
        return round((perf_counter() - started) * 1000, 2)
    except Exception:
        return None


def _awake_pulse():
    """Reuse readiness probe payload + wall-clock check_ms (no HTTP hop)."""
    try:
        started = perf_counter()
        payload, status = build_readiness()
        check_ms = round((perf_counter() - started) * 1000, 2)
        return {
            'status': payload.get('status'),
            'http_status': status,
            'checks': payload.get('checks'),
            'check_ms': check_ms,
        }
    except Exception:
        return None


def _queue_pulse():
    """Scan + download queue depths for near-realtime ops."""
    scans = _scan_snapshot()
    open_downloads = db.session.execute(
        select(func.count(DownloadRequest.id)).where(
            DownloadRequest.status.in_(('pending', 'processing'))
        )
    ).scalar() or 0
    scheduled_scans = db.session.execute(
        select(func.count(ScanJob.id)).where(ScanJob.status == 'Scheduled')
    ).scalar() or 0
    queued_scans = scans.get('queued_count')
    if queued_scans is None:
        queued_scans = db.session.execute(
            select(func.count(ScanJob.id)).where(ScanJob.status == 'Queued')
        ).scalar() or 0
    return {
        'scans_active': scans['active_count'],
        # Prefer FIFO Queued depth; keep Scheduled visible for schedule honesty.
        'scans_pending': int(queued_scans) + int(scheduled_scans),
        'scans_queued': int(queued_scans),
        'scans_scheduled': int(scheduled_scans),
        'scans_failures_24h': scans['failure_count'],
        'downloads_open': open_downloads,
    }


def _game_servers_pulse():
    """Registered household servers with best-effort health."""
    servers = db.session.execute(
        select(GameServer).order_by(GameServer.display_name.asc())
    ).scalars().all()
    rows = []
    for server in servers:
        health = probe_server_health(
            server.connect_string,
            server.health_url,
            timeout=1.5,
        )
        rows.append({
            'uuid': server.uuid,
            'display_name': server.display_name,
            'reachable': health.get('reachable'),
            'method': health.get('method'),
            'error': health.get('error'),
        })
    reachable = sum(1 for row in rows if row.get('reachable') is True)
    return {
        'count': len(rows),
        'reachable': reachable,
        'servers': rows,
    }


def _library_watch_pulse():
    """Optional root-folder incremental watch (ONEIRODEX_LIBRARY_WATCH)."""
    try:
        from oneirodex.utils.library_watch import get_library_watch_status

        return get_library_watch_status()
    except Exception as exc:
        return {
            'enabled': False,
            'running': False,
            'roots': 0,
            'pending_libraries': 0,
            'debounce_seconds': None,
            'last_event_at': None,
            'last_enqueue_at': None,
            'note': f'library watch status unavailable: {exc}',
        }


def _services_snapshot():
    """Sidecar / companion / queue pulse for Admin Ops."""
    return {
        'livekit': _livekit_pulse(),
        'malware': _malware_pulse(),
        'companions': _companion_pulse(),
        'queues': _queue_pulse(),
        'game_servers': _game_servers_pulse(),
        'awake': _awake_pulse(),
        'malware_module_enabled': malware_scan_enabled(),
        'library_watch': _library_watch_pulse(),
    }


def build_ops_summary(app_start_time, *, app=None, config=None):
    """Build a single snapshot for the admin operations dashboard."""
    def get_host_section():
        cpu = get_cpu_usage()
        memory = get_memory_usage()
        disk_base = get_disk_usage()
        disk_games = get_games_folder_usage()
        system_info = get_system_info()
        config_values = get_config_values(config=config)
        return {
            'host': {
                'os': system_info.get('Operating System'),
                'hostname': system_info.get('Hostname'),
                'ip': system_info.get('IP Address'),
                'python': system_info.get('Python Version'),
                'cpu': cpu,
                'memory': memory,
                # INSP-44: NVML or a BYO sensor reader; None when neither answers
                'gpu': get_gpu_usage(),
                'load_avg': get_load_average(),
                'process': get_process_memory(),
                'db_ping_ms': _db_ping_ms(),
                'disk_base': disk_base,
                'disk_games': disk_games,
                'uptime_system': get_formatted_system_uptime(),
                'uptime_app': get_formatted_app_uptime(app_start_time),
            },
            'config_values': config_values,
            'disk_base': disk_base,
            'disk_games': disk_games,
        }

    host_data, host_error = _section('host', get_host_section)
    network, network_error = _section('network', get_network_stats)
    scans, scans_error = _section('scans', lambda: _scan_snapshot(app=app))
    library, library_error = _section('library', _library_pulse)
    recent_errors_data, recent_errors_error = _section('recent errors', _recent_errors)
    services, services_error = _section('services', _services_snapshot)
    build, build_error = _section('build', build_identity)

    host = host_data['host'] if host_data else None
    disk_base = host_data['disk_base'] if host_data else None
    disk_games = host_data['disk_games'] if host_data else None
    config_values = host_data['config_values'] if host_data else {}
    scan_failures = scans['failure_count'] if scans else 0
    recent_errors, recent_error_count = recent_errors_data or (None, 0)

    # Stability signals for issues (optional kwargs on derive_issues).
    db_reachable = None
    if host is not None:
        db_reachable = host.get('db_ping_ms') is not None
    awake_ok = None
    companions_stale = None
    livekit = None
    if services:
        livekit = services.get('livekit')
        awake = services.get('awake')
        if awake is None:
            awake_ok = False
        elif isinstance(awake, dict):
            status = (awake.get('status') or '').lower()
            http_status = awake.get('http_status')
            awake_ok = status in ('ok', 'ready', 'pass') or http_status == 200
        companions = services.get('companions') or {}
        last_seen = companions.get('last_seen') or {}
        stale = last_seen.get('stale')
        if isinstance(stale, int) and stale > 0:
            companions_stale = stale

    summary = {
        'as_of': datetime.now(timezone.utc).isoformat(),
        'host': host,
        'network': network,
        'issues': derive_issues(
            disk_base_percent=disk_base.get('percent') if disk_base else None,
            disk_games_percent=disk_games.get('percent') if disk_games else None,
            path_problems=_path_problems(config_values),
            scan_failures=scan_failures,
            recent_error_count=recent_error_count,
            db_reachable=db_reachable,
            awake_ok=awake_ok,
            companions_stale=companions_stale,
            livekit=livekit,
        ),
        'scans': {
            'active_count': scans['active_count'],
            'jobs': scans['jobs'],
        } if scans else None,
        'library': library,
        'services': services,
        # What is actually running, and whether the migration that shipped with
        # it has run. Before this there was no way to answer either from inside
        # the product after a deploy.
        'build': build,
        'recent_errors': recent_errors,
    }
    for section_name, error in (
        ('host', host_error),
        ('network', network_error),
        ('scans', scans_error),
        ('library', library_error),
        ('services', services_error),
        ('build', build_error),
        ('recent_errors', recent_errors_error),
    ):
        if error:
            summary[f'{section_name}_error'] = error

    return summary
