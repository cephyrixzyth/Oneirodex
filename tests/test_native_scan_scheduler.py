from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from oneirodex.runtime_native import db_session
from oneirodex.utils import scan_queue, scan_scheduler


def test_scan_scheduler_passes_native_scope_to_queue_drain(monkeypatch):
    app = SimpleNamespace()
    scope = object()
    calls = []

    def drain(received_app, *, database_scope=None):
        calls.append((received_app, database_scope))
        return object()

    monkeypatch.setattr(scan_queue, 'drain_scan_queue', drain)

    assert scan_scheduler._run_due_jobs(app, database_scope=scope) is None
    assert calls == [(app, scope)]


def test_due_scan_job_passes_native_scope_to_worker(monkeypatch):
    app = SimpleNamespace()
    scope = object()
    due_job = SimpleNamespace(
        id=17,
        scan_folder='C:/library',
        next_run=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    calls = []

    class Result:
        def scalars(self):
            return self

        def all(self):
            return [due_job]

    class Session:
        def execute(self, _statement):
            return Result()

    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=Session()))
    monkeypatch.setattr(scan_queue, 'drain_scan_queue', lambda *_a, **_k: None)
    monkeypatch.setattr(scan_queue, 'is_scan_busy', lambda: False)
    monkeypatch.setattr(
        scan_queue,
        'restart_or_queue_scan',
        lambda job_id, **kwargs: calls.append((job_id, kwargs)),
    )

    scan_scheduler._run_due_jobs(app, database_scope=scope)

    assert calls == [(17, {'app': app, 'scheduled': True, 'database_scope': scope})]


def test_periodic_shutdown_waits_for_active_work_and_allows_restart():
    from threading import Event
    import pytest
    from oneirodex.utils.periodic_worker import PeriodicWorker

    entered, release, restarted = Event(), Event(), Event()
    worker = PeriodicWorker('lifecycle-fixture')

    def cycle():
        entered.set()
        release.wait(3)

    assert worker.start(cycle, interval=3600) is worker
    assert entered.wait(2)
    running = worker.thread
    try:
        assert worker.start(cycle, interval=3600).thread is running
        with pytest.raises(TimeoutError):
            worker.stop(timeout=0.01)
        with pytest.raises(RuntimeError, match='stopping'):
            worker.start(cycle, interval=3600)
    finally:
        release.set()
        worker.stop()
    assert not running.is_alive()
    worker.start(restarted.set, interval=3600)
    try:
        assert restarted.wait(2)
    finally:
        worker.stop()
