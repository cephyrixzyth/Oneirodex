from __future__ import annotations

from types import SimpleNamespace
from contextlib import nullcontext

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import admin_ops_reads
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token, load_session_cookie,
)


def test_ops_logs_use_native_joinedload_and_return_empty_events(monkeypatch):
    from types import SimpleNamespace

    class Result:
        def scalars(self):
            return self

        def all(self):
            return []

    class NativeSession:
        def execute(self, statement):
            assert statement is not None
            return Result()

    monkeypatch.setattr(
        'oneirodex.runtime_native.db_session.native_db',
        SimpleNamespace(session=NativeSession()),
    )

    assert admin_ops_reads.AdminOpsReadData().logs(50) == {'events': []}


def test_admin_ops_data_uses_injected_configuration_without_flask_context(monkeypatch):
    app = SimpleNamespace(
        config={'SECRET_KEY': 'not-used', 'BASE_FOLDER_POSIX': '/games'},
        root_path='/srv/oneirodex',
        app_context=lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    engine = SimpleNamespace(url=SimpleNamespace(drivername='postgresql', path='/oneirodex'))
    monkeypatch.setattr(
        'oneirodex.runtime_native.db_session.current_native_engine', lambda: engine,
    )
    monkeypatch.setattr(
        'oneirodex.utils.status.get_system_info', lambda: {'Operating System': 'test'},
    )
    monkeypatch.setattr(
        'oneirodex.utils.status.get_database_info', lambda *, engine: {'engine': engine},
    )
    monkeypatch.setattr('oneirodex.utils.status.get_active_users', lambda: 4)
    monkeypatch.setattr(
        'oneirodex.utils.status.get_config_values', lambda *, config: {'config': config},
    )
    monkeypatch.setattr(
        'oneirodex.utils.uptime.get_formatted_system_uptime', lambda: 'system uptime',
    )
    monkeypatch.setattr(
        'oneirodex.utils.uptime.get_formatted_app_uptime', lambda _start: 'app uptime',
    )
    monkeypatch.setattr('oneirodex.utils.status.get_log_info', lambda: {})
    monkeypatch.setattr(
        'oneirodex.utils.ops_projections.log_summary', lambda info: {'count': 0, 'latest': None},
    )
    monkeypatch.setattr(
        'oneirodex.utils.ops_projections.theme_asset_panel', lambda root_path: {'root': root_path},
    )

    payload = admin_ops_reads.AdminOpsReadData().system(app)

    assert payload['database']['engine'] is engine
    assert payload['config']['config'] is app.config
    assert payload['theme_assets'] == {'root': app.root_path}
    assert payload['active_users'] == 4


def test_ops_summary_receives_explicit_config_and_task_owner_without_context(monkeypatch):
    from oneirodex import app_start_time
    from oneirodex.utils import ops_summary

    app = SimpleNamespace(
        config={'BASE_FOLDER_POSIX': '/games'},
        app_context=lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    expected = {'health': 'ok'}
    calls = []
    monkeypatch.setattr(
        ops_summary, 'build_ops_summary',
        lambda start, *, app, config: calls.append((start, app, config)) or expected,
    )

    assert admin_ops_reads.AdminOpsReadData().summary(app) is expected
    assert calls == [(app_start_time, app, app.config)]


def test_image_refresh_poll_preserves_cached_job_status_and_envelopes_missing_jobs():
    app = Flask('ops-image-progress-test')
    app.config.update(SECRET_KEY='ops-image-progress-secret', CSP_ENABLED=False)
    app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=9, user_id='ops-admin', role='admin', is_active=True, state=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint', name='Ops Admin',
    )

    class FakeOps:
        deletion_jobs = {'sse-job': {'status': 'completed', 'message': 'done'}}

        def image_refresh_progress(self, game_uuid):
            return {'status': 'error', 'progress': 0, 'game_uuid': game_uuid}

        def library_delete_progress(self, job_id):
            if job_id == 'job-1':
                return {'status': 'error', 'message': 'worker failed'}
            return None

        def library_deletion_progress(self):
            return self.deletion_jobs

    data = FakeOps()
    router = admin_ops_reads.create_admin_ops_reads_router(
        app, find_user=lambda user_id: user if user_id == 9 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '9' else None,
        login_manager=SimpleNamespace(
            login_view='login.login', blueprint_login_views={}, login_message='Sign in',
            login_message_category='message', localize_callback=None,
            session_protection='basic',
        ),
        data_access=data, database_scope=lambda _app: nullcontext(),
    )
    native_app = FastAPI()
    native_app.include_router(router)
    client = TestClient(native_app)
    session = {'_user_id': '9:fingerprint', '_fresh': True}
    client.cookies.set('session', dump_session_cookie(session, app.config['SECRET_KEY']))

    anonymous = TestClient(native_app).get(
        '/check_deletion_progress/job-1', follow_redirects=False,
    )
    assert anonymous.status_code == 302
    assert anonymous.headers['location'].startswith('/login')

    cached = client.get('/check_image_refresh_progress/game-1')
    assert cached.status_code == 200
    assert cached.json() == {'status': 'error', 'progress': 0, 'game_uuid': 'game-1'}

    class MissingOps:
        def image_refresh_progress(self, _game_uuid):
            return None

    missing_router = admin_ops_reads.create_admin_ops_reads_router(
        app, find_user=lambda user_id: user if user_id == 9 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '9' else None,
        login_manager=SimpleNamespace(
            login_view='login.login', blueprint_login_views={}, login_message='Sign in',
            login_message_category='message', localize_callback=None,
            session_protection='basic',
        ),
        data_access=MissingOps(), database_scope=lambda _app: nullcontext(),
    )
    missing_app = FastAPI()
    missing_app.include_router(missing_router)
    missing_client = TestClient(missing_app)
    missing_client.cookies.set('session', dump_session_cookie(session, app.config['SECRET_KEY']))
    missing = missing_client.get('/check_image_refresh_progress/game-2')
    assert missing.status_code == 200
    assert missing.json()['ok'] is True
    assert missing.json()['status'] == 'not_found'
    assert missing.json()['progress'] == 0

    failed_job = client.get('/check_deletion_progress/job-1')
    missing_job = client.get('/check_deletion_progress/job-2')
    assert failed_job.status_code == 200
    assert failed_job.json() == {'status': 'error', 'message': 'worker failed'}
    assert missing_job.status_code == 404
    assert missing_job.json()['status'] == 'not_found'

    stream = client.get('/delete_library_progress/sse-job')
    assert stream.status_code == 200
    assert stream.headers['content-type'].startswith('text/event-stream')
    assert stream.headers['cache-control'] == 'no-cache'
    assert '"status": "connected"' in stream.text
    assert '\n\n' in stream.text
    assert '"status": "completed"' in stream.text
    assert data.deletion_jobs == {}


def test_clear_system_logs_requires_csrf_and_audits_the_admin_actor():
    app = Flask('ops-clear-test')
    app.config.update(SECRET_KEY='ops-clear-test-secret', CSP_ENABLED=False)
    app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=9, user_id='ops-admin', role='admin', is_active=True, state=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint', name='Ops Admin',
    )

    class FakeOps:
        def __init__(self):
            self.calls = []

        def clear_logs(self, actor):
            self.calls.append(('clear', actor.id))
            return {'message': 'Successfully cleared 3 system logs', 'deleted_count': 3}

        def rollback(self):
            self.calls.append(('rollback',))

    data = FakeOps()
    router = admin_ops_reads.create_admin_ops_reads_router(
        app, find_user=lambda user_id: user if user_id == 9 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '9' else None,
        login_manager=SimpleNamespace(
            login_view='login.login', blueprint_login_views={}, login_message='Sign in',
            login_message_category='message', localize_callback=None,
            session_protection='basic',
        ),
        data_access=data, database_scope=lambda _app: nullcontext(),
    )
    native_app = FastAPI()
    native_app.include_router(router)
    client = TestClient(native_app)
    session = {
        '_user_id': '9:fingerprint', '_fresh': True,
        'permission_check_failed': True, 'permission_errors': ['read-only'],
        'permission_check_path': '/games',
    }
    client.cookies.set('session', dump_session_cookie(session, app.config['SECRET_KEY']))
    csrf = generate_csrf_token(session, app.config['SECRET_KEY'])

    denied = client.delete('/admin/api/system_logs/clear')
    assert denied.status_code == 400 and not data.calls
    accepted_client = TestClient(native_app)
    accepted_client.cookies.set('session', dump_session_cookie(session, app.config['SECRET_KEY']))
    accepted_csrf = generate_csrf_token(session, app.config['SECRET_KEY'])
    accepted = accepted_client.delete(
        '/admin/api/system_logs/clear', headers={'X-CSRFToken': accepted_csrf},
    )
    assert accepted.status_code == 200 and accepted.json()['deleted_count'] == 3
    assert data.calls == [('clear', 9)]

    cleared = accepted_client.post(
        '/admin/clear_permission_errors', headers={'X-CSRFToken': accepted_csrf},
    )
    assert cleared.status_code == 200 and cleared.json()['success'] is True
    assert 'session=' in cleared.headers['set-cookie']
    persisted = load_session_cookie(
        cleared.cookies.get('session'), app.config['SECRET_KEY'], max_age=31 * 24 * 60 * 60,
    )
    assert all(key not in persisted for key in (
        'permission_check_failed', 'permission_errors', 'permission_check_path',
    ))

