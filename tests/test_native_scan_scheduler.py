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
