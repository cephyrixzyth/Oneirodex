"""Regressions for recurring/restarted scan ownership and execution parity."""
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from oneirodex.models import AllowedFileType, Game, Library, ScanJob
from oneirodex.platform import LibraryPlatform
from oneirodex.utils import scan_queue, scan_scheduler
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


def test_restart_route_forwards_queue_choice(app, db_session, library, tmp_path, monkeypatch):
    from oneirodex.routes_admin_ext.scan_jobs import restart_scan_job

    target = make_job(db_session, library, tmp_path)
    dispatch = Mock(return_value={'status': 'queued', 'message': 'Queued'})
    monkeypatch.setattr(scan_queue, 'restart_or_queue_scan', dispatch)
    # Authentication is covered by route tests; isolate form-to-policy plumbing.
    handler = restart_scan_job
    while hasattr(handler, '__wrapped__'):
        handler = handler.__wrapped__
    with app.test_request_context(method='POST', data={'queue_policy': 'queue'}):
        assert handler(target.id).status_code == 302
    assert dispatch.call_args.kwargs['queue_policy'] == 'queue'
    assert dispatch.call_args.kwargs['allow_force'] is True


@pytest.fixture
def worker_stubs(monkeypatch, db_session):
    db_session.add(AllowedFileType(value='.exe'))
    db_session.commit()
    monkeypatch.setattr(scans, 'load_scanning_filter_patterns', lambda: ([], []))
    monkeypatch.setattr(scans, 'load_skip_dir_patterns', lambda: [])
    monkeypatch.setattr(scans, 'load_skip_dir_regex_patterns', lambda: [])
    monkeypatch.setattr(scans, 'IGDBRateLimiter', Mock)
    monkeypatch.setattr(scans, '_drain_scan_queue_safe', lambda: None)
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
    monkeypatch.setattr(scans, 'get_game_names_from_folder', lambda *a, **k: [])
    scans.scan_and_add_games(str(tmp_path), library_uuid=library.uuid, existing_job=target)
    db_session.expire_all()
    target = db_session.get(ScanJob, target.id)
    assert target.status == ('Completed' if kind == 'once' else 'Scheduled')
    if kind != 'once':
        assert target.next_run.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


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
    monkeypatch.setattr(scans, 'get_game_names_from_folder', lambda *a, **k: [{'name': game.name, 'full_path': str(game_dir)}])
    updates, extras, hltb = Mock(), Mock(), Mock()
    monkeypatch.setattr(scans, 'process_game_updates', updates)
    monkeypatch.setattr(scans, 'process_game_extras', extras)
    monkeypatch.setattr(scans, 'process_pc_dlc_and_extra_roots', Mock())
    monkeypatch.setattr('oneirodex.utils.hltb.update_game_hltb_sync', hltb)
    monkeypatch.setattr(scans, 'process_game_with_fallback', Mock(side_effect=AssertionError('Existing game must not rematch')))
    scans.scan_and_add_games(str(tmp_path), library_uuid=library.uuid, existing_job=target,
                             force_updates_extras_scan=True, force_hltb_refetch=True)
    updates.assert_called_once()
    extras.assert_called_once()
    hltb.assert_called_once()
