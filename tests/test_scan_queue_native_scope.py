from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from oneirodex.utils import scan_queue


def test_scan_worker_uses_native_database_scope_without_flask_app_context(monkeypatch):
    calls = []
    job = SimpleNamespace(
        id='scan-1', scan_folder='/library', library_uuid='lib-1',
        setting_filefolder=False, setting_remove=False,
        setting_download_missing_images=False, setting_force_updates_extras=False,
        schedule=None,
    )

    class FakeSession:
        def get(self, model, job_id):
            calls.append(('get', model.__name__, job_id))
            return job

    class ImmediateThread:
        def __init__(self, *, target, **kwargs):
            self.target = target
            calls.append(('thread', kwargs['name']))

        def start(self):
            self.target()

    app = SimpleNamespace(
        app_context=lambda: (_ for _ in ()).throw(
            AssertionError('native scan worker pushed Flask app context'),
        ),
    )

    @contextmanager
    def database_scope(scope_app):
        assert scope_app is app
        calls.append(('scope_enter',))
        try:
            yield
        finally:
            calls.append(('scope_exit',))

    def scan_and_add_games(*args, **kwargs):
        calls.append(('scan', args[0], kwargs['database_scope'] is database_scope, kwargs['app'] is app))

    monkeypatch.setattr(scan_queue, 'db', SimpleNamespace(session=FakeSession()))
    monkeypatch.setattr(scan_queue, 'Thread', ImmediateThread)
    monkeypatch.setattr(
        'oneirodex.utils.services.scan_orchestration.scan_and_add_games',
        scan_and_add_games,
    )

    scan_queue._start_job_thread(job, app, database_scope=database_scope)

    assert calls == [
        ('thread', 'oneirodex-scan-scan-1'),
        ('scope_enter',),
        ('get', 'ScanJob', 'scan-1'),
        ('scan', '/library', True, True),
        ('scope_exit',),
    ]


def test_native_scan_queue_drain_passes_scope_to_promoted_worker(monkeypatch):
    calls = []
    app = object()
    database_scope = object()

    monkeypatch.setattr(scan_queue, 'reclaim_stale_busy_jobs', lambda: None)
    monkeypatch.setattr(
        scan_queue, 'promote_next_queued_scan',
        lambda selected_app, *, database_scope: calls.append(
            ('promote', selected_app is app, database_scope is not None),
        ) or 'promoted',
    )

    assert scan_queue.drain_scan_queue(app, database_scope=database_scope) == 'promoted'
    assert calls == [('promote', True, True)]


def test_native_scan_start_uses_framework_free_worker_and_preserves_hltb_flags(monkeypatch):
    calls = []
    app = object()
    database_scope = object()
    job = SimpleNamespace(id='scan-started', last_run=None)

    monkeypatch.setattr(scan_queue, '_application_or_current', lambda selected: app)
    monkeypatch.setattr(scan_queue, 'reclaim_stale_busy_jobs', lambda: None)
    monkeypatch.setattr(scan_queue, 'is_scan_busy', lambda: False)
    monkeypatch.setattr(scan_queue, 'create_scan_job_row', lambda **kwargs: job)
    monkeypatch.setattr(scan_queue, '_has_older_busy_scan', lambda _job: False)
    monkeypatch.setattr(
        scan_queue, '_start_job_thread',
        lambda selected, selected_app, **kwargs: calls.append(
            (selected is job, selected_app is app, kwargs),
        ),
    )
    monkeypatch.setattr(
        'oneirodex.utils.event_bus.publish_scan_event',
        lambda *args: calls.append(('event', *args)),
    )

    result = scan_queue.start_or_queue_scan(
        folder_path='/storage', library_uuid='lib-1', app=app,
        database_scope=database_scope, fetch_hltb=True,
        force_hltb_refetch=True,
    )

    assert result['status'] == 'started'
    assert calls[0] == ('event', 'scan-started', 'Running')
    assert calls[1] == (
        True, True, {
            'force_parallel': False, 'database_scope': database_scope,
            'fetch_hltb': True, 'force_hltb_refetch': True,
        },
    )


def test_scan_orchestration_drain_keeps_native_scope(monkeypatch):
    from oneirodex.utils.services import scan_orchestration

    calls = []
    app = object()
    database_scope = object()
    monkeypatch.setattr(
        scan_queue, 'drain_scan_queue',
        lambda selected_app, *, database_scope: calls.append(
            ('drain', selected_app is app, database_scope is not None),
        ),
    )

    scan_orchestration._drain_scan_queue_safe(app, database_scope)

    assert calls == [('drain', True, True)]
