"""Regressions for recurring/restarted scan ownership and execution parity."""
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from oneirodex.models import AllowedFileType, Game, Library, ScanJob
from oneirodex.platform import LibraryPlatform
from oneirodex.utils import scan_queue, scan_scheduler
from oneirodex.utils.library_health import refresh_game_path_status as _real_refresh_path
from oneirodex.utils.services import scan_orchestration as scans


pytestmark = pytest.mark.integration


@pytest.fixture
def library(db_session, tmp_path):
    row = Library(name='Runtime scan regression', platform=LibraryPlatform.PCWIN)
    db_session.add(row)
    db_session.commit()
    return row


def make_job(db_session, library, tmp_path, status='Completed', **extra):
    values = dict(
        library_uuid=library.uuid, scan_folder=str(tmp_path),
        folders={str(tmp_path): True}, content_type='Games', status=status,
        is_enabled=True, last_run=datetime.now(timezone.utc) - timedelta(days=2),
        last_progress_update=datetime.now(timezone.utc) - timedelta(days=2),
        owner_token='old-process:4294967000', folders_success=8,
        folders_failed=2, total_folders=10, removed_count=3,
        current_processing='old game', error_message='old error',
    )
    values.update(extra)
    row = ScanJob(**values)
    db_session.add(row)
    db_session.commit()
    return row


def test_restart_queues_and_does_not_dispatch_when_busy(app, db_session, library, tmp_path, monkeypatch):
    busy = make_job(db_session, library, tmp_path, 'Running', owner_token=scan_queue.PROCESS_TOKEN)
    target = make_job(db_session, library, tmp_path)
    dispatch = Mock()
    monkeypatch.setattr(scan_queue, '_start_job_thread', dispatch)
    result = scan_queue.restart_or_queue_scan(target.id, queue_policy='queue', app=app)
    assert result['status'] == 'queued'
    assert target.status == 'Queued'
    assert target.owner_token is None
    assert busy.status == 'Running'
    dispatch.assert_not_called()


@pytest.mark.parametrize('status', ['Running', 'Stopping', 'Queued'])
def test_restart_rejects_owned_rows(app, db_session, library, tmp_path, monkeypatch, status):
    target = make_job(db_session, library, tmp_path, status, is_enabled=False)
    dispatch = Mock()
    monkeypatch.setattr(scan_queue, '_start_job_thread', dispatch)
    result = scan_queue.restart_or_queue_scan(target.id, queue_policy='force', allow_force=True, app=app)
    assert result['status'] == 'rejected'
    assert target.status == status
    assert target.is_enabled is False
    dispatch.assert_not_called()


@pytest.mark.parametrize('scheduled', [False, True])
def test_run_claim_resets_prior_execution_and_cannot_be_claimed_twice(
    app, db_session, library, tmp_path, monkeypatch, scheduled,
):
    target = make_job(db_session, library, tmp_path, 'Scheduled' if scheduled else 'Completed',
                      schedule_kind='interval', schedule_interval_minutes=60,
                      next_run=datetime.now(timezone.utc) - timedelta(minutes=1))
    dispatch = Mock()
    monkeypatch.setattr(scan_queue, '_start_job_thread', dispatch)
    result = scan_queue.restart_or_queue_scan(target.id, app=app, scheduled=scheduled)
    assert result['status'] == 'started'
    assert target.owner_token == scan_queue.PROCESS_TOKEN
    assert target.last_progress_update == target.last_run
    assert target.folders_success == target.folders_failed == target.removed_count == 0
    assert target.total_folders == 0
    assert target.current_processing is None
    assert target.error_message == ''
    assert target.schedule_interval_minutes == 60
    assert scan_queue.reclaim_stale_busy_jobs() == 0
    assert scan_queue.restart_or_queue_scan(target.id, app=app, scheduled=scheduled)['status'] == 'rejected'
    dispatch.assert_called_once()


def test_scheduler_dispatch_renews_run_state(app, db_session, library, tmp_path, monkeypatch):
    target = make_job(db_session, library, tmp_path, 'Scheduled',
                      next_run=datetime.now(timezone.utc) - timedelta(minutes=1))
    dispatch = Mock()
    monkeypatch.setattr(scan_queue, '_start_job_thread', dispatch)
    scan_scheduler._run_due_jobs(app)
    assert target.status == 'Running'
    assert target.owner_token == scan_queue.PROCESS_TOKEN
    assert target.folders_success == target.folders_failed == 0
    dispatch.assert_called_once()


@pytest.fixture
def worker_stubs(monkeypatch, db_session, app, tmp_path):
    for key in ('DATA_FOLDER_GAMES', 'BASE_FOLDER_POSIX', 'BASE_FOLDER_WINDOWS'):
        monkeypatch.setitem(app.config, key, str(tmp_path))
    db_session.add(AllowedFileType(value='.exe'))
    db_session.commit()
    monkeypatch.setattr('oneirodex.utils.functions.load_scanning_filter_patterns', lambda: ([], []))
    monkeypatch.setattr('oneirodex.utils.functions.load_skip_dir_patterns', lambda: [])
    monkeypatch.setattr('oneirodex.utils.functions.load_skip_dir_regex_patterns', lambda: [])
    monkeypatch.setattr('oneirodex.utils.igdb_api.IGDBRateLimiter', Mock)
    monkeypatch.setattr(scans, '_drain_scan_queue_safe', lambda *_a, **_k: None)
    monkeypatch.setattr(scans, 'cooperative_yield', lambda: None)
    monkeypatch.setattr('oneirodex.utils.notifications.flush_library_add_digest', lambda *_: None)
    monkeypatch.setattr('oneirodex.utils.shutdown.should_continue_processing', lambda: True)
    monkeypatch.setattr('oneirodex.utils.library_health.refresh_game_path_status', lambda _: 'present')
    monkeypatch.setattr('oneirodex.utils.library_health.clear_restored_missing_path_status', lambda *a, **k: False)


@pytest.mark.parametrize('kind', ['once', 'preset', 'interval', 'cron'])
def test_empty_success_preserves_recurring_schedule(
    app, db_session, library, tmp_path, monkeypatch, global_settings, worker_stubs, kind,
):
    target = make_job(db_session, library, tmp_path, 'Running', schedule_kind=kind,
                      schedule='8_hours' if kind == 'preset' else None,
                      schedule_interval_minutes=30 if kind == 'interval' else None,
                      schedule_cron='*/5 * * * *' if kind == 'cron' else None)
    monkeypatch.setattr('oneirodex.utils.gamenames.get_game_names_from_folder', lambda *a, **k: [])
    scans.scan_and_add_games(str(tmp_path), library_uuid=library.uuid, existing_job=target)
    db_session.expire_all()
    target = db_session.get(ScanJob, target.id)
    assert target.status == ('Completed' if kind == 'once' else 'Scheduled')
    if kind != 'once':
        assert target.next_run.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


def test_worker_revalidates_queued_path_against_current_scan_roots(
    app, db_session, library, tmp_path, monkeypatch,
):
    allowed_root = tmp_path / 'currently-allowed'
    allowed_root.mkdir()
    outside_root = tmp_path / 'no-longer-allowed'
    outside_root.mkdir()
    app.config.update({
        'DATA_FOLDER_GAMES': str(allowed_root),
        'BASE_FOLDER_POSIX': str(allowed_root),
        'BASE_FOLDER_WINDOWS': str(allowed_root),
        'LIBRARY_ROOTS': [],
    })
    target = make_job(
        db_session, library, outside_root, 'Running',
        scan_folder=str(outside_root),
        folders={str(outside_root): True},
    )
    body = Mock()
    monkeypatch.setattr(scans, '_scan_and_add_games_body', body)
    monkeypatch.setattr(scans, '_drain_scan_queue_safe', lambda *_a, **_k: None)

    scans.scan_and_add_games(
        str(outside_root), library_uuid=library.uuid, existing_job=target, app=app,
    )

    db_session.expire_all()
    persisted = db_session.get(ScanJob, target.id)
    assert persisted.status == 'Failed'
    assert persisted.error_message == 'Scan location is no longer allowed.'
    body.assert_not_called()


def test_worker_fails_closed_and_drains_on_malformed_scan_root_config(
    app, db_session, library, tmp_path, monkeypatch,
):
    allowed_root = tmp_path / 'configured'
    allowed_root.mkdir()
    app.config.update({
        'DATA_FOLDER_GAMES': str(allowed_root),
        'BASE_FOLDER_POSIX': str(allowed_root),
        'BASE_FOLDER_WINDOWS': str(allowed_root),
        'LIBRARY_ROOTS': [None],
    })
    target = make_job(
        db_session, library, allowed_root, 'Running',
        scan_folder=str(allowed_root),
        folders={str(allowed_root): True},
    )
    body = Mock()
    monkeypatch.setattr(scans, '_scan_and_add_games_body', body)
    monkeypatch.setattr(scans, '_drain_scan_queue_safe', lambda *_a, **_k: None)

    scans.scan_and_add_games(
        str(allowed_root), library_uuid=library.uuid, existing_job=target, app=app,
    )

    db_session.expire_all()
    persisted = db_session.get(ScanJob, target.id)
    assert persisted.status == 'Failed'
    assert persisted.error_message == 'Scan location is no longer allowed.'
    body.assert_not_called()


class InlinePool:
    """Exercise the pool branch without leaking test DB sessions to threads."""
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def submit(self, fn, *args):
        future = Future()
        future.set_result(fn(*args))
        return future


@pytest.mark.parametrize('workers', [1, 2])
def test_existing_game_force_refresh_is_independent_of_worker_count(
    app, db_session, library, tmp_path, monkeypatch, global_settings, worker_stubs, workers,
):
    game_dir = tmp_path / 'Game'
    (game_dir / 'updates').mkdir(parents=True)
    (game_dir / 'extras').mkdir()
    game = Game(name='Existing game', library_uuid=library.uuid, full_disk_path=str(game_dir))
    db_session.add(game)
    global_settings.scan_thread_count = workers
    global_settings.enable_game_updates = True
    global_settings.enable_game_extras = True
    global_settings.enable_hltb_integration = True
    global_settings.update_folder_name = 'updates'
    global_settings.extras_folder_name = 'extras'
    db_session.commit()
    target = make_job(db_session, library, tmp_path, 'Running', folders_success=0, folders_failed=0)
    monkeypatch.setattr(scans, 'ThreadPoolExecutor', InlinePool)
    monkeypatch.setattr('oneirodex.utils.gamenames.get_game_names_from_folder', lambda *a, **k: [{'name': game.name, 'full_path': str(game_dir)}])
    updates, extras, hltb = Mock(), Mock(), Mock()
    monkeypatch.setattr('oneirodex.utils.scanning.process_game_updates', updates)
    monkeypatch.setattr('oneirodex.utils.scanning.process_game_extras', extras)
    monkeypatch.setattr('oneirodex.utils.scanning.process_pc_dlc_and_extra_roots', Mock())
    monkeypatch.setattr('oneirodex.utils.hltb.update_game_hltb_sync', hltb)
    monkeypatch.setattr('oneirodex.utils.scanning.process_game_with_fallback', Mock(side_effect=AssertionError('Existing game must not rematch')))
    scans.scan_and_add_games(str(tmp_path), library_uuid=library.uuid, existing_job=target,
                             force_updates_extras_scan=True, force_hltb_refetch=True)
    updates.assert_called_once()
    extras.assert_called_once()
    hltb.assert_called_once()


def test_reconciliation_keeps_other_roots_and_empty_mounts(app, db_session, library, global_settings,
                                                          worker_stubs, tmp_path, monkeypatch):
    from oneirodex.utils import library_health

    # worker_stubs disables I/O checks for orchestration-only tests. Use the real
    # function here so the stored paths and deletions cross the database boundary.
    monkeypatch.setattr(library_health, 'refresh_game_path_status', _real_refresh_path)
    inside = tmp_path / 'shelf'
    outside = tmp_path / 'shelf-backup'
    inside.mkdir()
    outside.mkdir()
    present = inside / 'keep.exe'
    present.write_bytes(b'game')
    live = Game(name='Present', library_uuid=library.uuid, full_disk_path=str(present))
    gone = Game(name='Missing inside', library_uuid=library.uuid, full_disk_path=str(inside / 'gone.exe'))
    other = Game(name='Missing outside', library_uuid=library.uuid, full_disk_path=str(outside / 'other.exe'))
    db_session.add_all([live, gone, other])
    db_session.commit()
    library_id, gone_id, other_id, live_id = library.uuid, gone.id, other.id, live.id

    def run():
        target = make_job(db_session, db_session.get(Library, library_id), inside, 'Running', removed_count=0)
        target_id = target.id
        scans.scan_and_add_games(str(inside), scan_mode='files', library_uuid=library_id, existing_job=target,
                                 app=app, remove_missing=True)
        db_session.expire_all()
        return db_session.get(ScanJob, target_id)

    assert run().removed_count == 0
    assert db_session.get(Library, library_id).last_scan_folder == str(inside)
    assert run().removed_count == 1
    assert db_session.get(Game, gone_id) is None
    assert db_session.get(Game, other_id).path_status is None
    present.unlink()
    assert run().removed_count == 0
    assert db_session.get(Game, live_id).path_status == 'missing'


@pytest.mark.parametrize('zone', ['UTC', 'America/Chicago'])
def test_scan_claim_is_fresh_in_connection_timezone(db_session, library, tmp_path, zone):
    from sqlalchemy import text

    db_session.execute(text("select set_config('TimeZone', :zone, true)"), {'zone': zone})
    job = scan_queue.create_scan_job_row(folder_path=str(tmp_path), library_uuid=library.uuid, status='Running')
    db_session.expire_all()
    assert scan_queue.reclaim_stale_busy_jobs() == 0
    assert db_session.get(ScanJob, job.id).status == 'Running'


def test_queued_scans_keep_requested_options_and_coalesce_only_equal_work(app, db_session, library, tmp_path,
                                                                        monkeypatch):
    busy = scan_queue.create_scan_job_row(folder_path=str(tmp_path), library_uuid=library.uuid, status='Running')
    kwargs = dict(folder_path=str(tmp_path), library_uuid=library.uuid, app=app, scan_mode='files',
                  fetch_hltb=True, force_hltb_refetch=True)
    queued = scan_queue.start_or_queue_scan(**kwargs)
    repeat = scan_queue.start_or_queue_scan(**kwargs)
    different = scan_queue.start_or_queue_scan(**kwargs, remove_missing=True)
    assert queued['job_id'] == repeat['job_id'] != different['job_id']
    busy.status = 'Completed'
    db_session.commit()
    db_session.expire_all()
    launch = Mock()
    monkeypatch.setattr(scan_queue, '_start_job_thread', launch)
    scanned = scan_queue.drain_scan_queue(app=app)
    assert scanned.id == queued['job_id']
    assert scanned.setting_fetch_hltb and scanned.setting_force_hltb_refetch
    assert scanned.setting_filefolder and not scanned.setting_remove
    launch.assert_called_once()


def test_changed_storage_and_partial_enumeration_preserve_missing_rows(
    app, db_session, library, global_settings, worker_stubs, tmp_path, monkeypatch,
):
    from oneirodex.utils import gamenames, library_health

    monkeypatch.setattr(library_health, 'refresh_game_path_status', _real_refresh_path)
    shelf = tmp_path / 'shelf'
    shelf.mkdir()
    game_path = shelf / 'present.exe'
    game_path.write_bytes(b'game')
    library.last_scan_folder = str(shelf)
    library.last_scan_root_identity = 'old-device:old-inode'
    missing = Game(name='Absent', library_uuid=library.uuid, full_disk_path=str(shelf / 'absent.exe'))
    present = Game(name='Present', library_uuid=library.uuid, full_disk_path=str(game_path))
    db_session.add_all([missing, present])
    db_session.commit()
    library_id, absent_id = library.uuid, missing.id
    for partial in (False, True):
        current = db_session.get(Library, library_id)
        job = make_job(db_session, current, shelf, 'Running', removed_count=0)
        job_id = job.id
        if partial:
            monkeypatch.setattr(gamenames, 'get_game_names_from_files', Mock(side_effect=PermissionError('busy')))
        scans.scan_and_add_games(str(shelf), scan_mode='files', library_uuid=library_id, existing_job=job,
                                 app=app, remove_missing=True)
        completed = db_session.get(ScanJob, job_id)
        assert completed.status == ('Failed' if partial else 'Completed')
        assert completed.removed_count == 0
        assert db_session.get(Game, absent_id) is not None
