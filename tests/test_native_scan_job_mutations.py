from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, redirect as flask_redirect

from oneirodex.runtime_native.scan_job_mutations import create_scan_job_mutation_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeScanJobs:
    def __init__(self):
        self.calls = []

    def cancel(self, job_id):
        self.calls.append(('cancel', job_id))
        return ('Scan job is stopping.', 'message')

    def delete(self, job_id):
        self.calls.append(('delete', job_id))
        return job_id != 'missing'

    def clear(self, status=None):
        self.calls.append(('clear', status))
        return (3, 'scan jobs')

    def restart(self, job_id, *, queue_policy, app, database_scope):
        self.calls.append(('restart', job_id, queue_policy, app is not None, callable(database_scope)))
        return {'status': 'queued', 'message': 'Scan queued.'}


def _client(*, role='admin'):
    app = Flask('native-scan-job-test')
    app.config.update(
        SECRET_KEY='native-scan-job-secret', CSP_ENABLED=False,
        WTF_CSRF_ENABLED=True,
    )
    app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=9, user_id='scan-user', role=role, is_active=True, state=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Sign in',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '9:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, app.config['SECRET_KEY'])
    data = FakeScanJobs()
    native = FastAPI()
    native.include_router(create_scan_job_mutation_router(
        app,
        find_user=lambda user_id: user if user_id == 9 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '9' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    ))
    client = TestClient(native, follow_redirects=False)
    client.cookies.set('session', dump_session_cookie(session, app.config['SECRET_KEY']))
    return client, data, csrf


def test_scan_job_cancel_requires_csrf_and_keeps_admin_redirect_flash():
    client, data, csrf = _client()
    denied = client.post('/cancel_scan_job/job-1')
    assert denied.status_code == 400
    assert data.calls == []

    accepted = client.post('/cancel_scan_job/job-1', data={'csrf_token': csrf})
    assert accepted.status_code == 302
    assert accepted.headers['location'] == '/scan_management?active_tab=jobs'
    expected = flask_redirect('/scan_management?active_tab=jobs', code=302)
    assert accepted.headers['content-type'] == expected.headers['Content-Type']
    assert accepted.content == expected.get_data()
    assert 'session=' in accepted.headers['set-cookie']
    assert data.calls == [('cancel', 'job-1')]


def test_scan_job_mutations_redirect_non_admin_without_running_action():
    client, data, csrf = _client(role='member')

    cancel_response = client.post(
        '/cancel_scan_job/job-1', data={'csrf_token': csrf},
    )
    delete_response = client.post(
        '/delete_scan_job/job-1', data={'csrf_token': csrf},
    )

    for response in (cancel_response, delete_response):
        assert response.status_code == 302
        assert response.headers['location'] == '/login'
        assert 'session=' in response.headers['set-cookie']
    assert data.calls == []


def test_scan_job_delete_and_clear_preserve_not_found_and_status_rules():
    client, data, csrf = _client()
    deleted = client.post('/delete_scan_job/job-1', data={'csrf_token': csrf})
    missing = client.post('/delete_scan_job/missing', data={'csrf_token': csrf})
    cleared_all = client.post('/clear_all_scan_jobs', data={'csrf_token': csrf})
    invalid_clear = client.post(
        '/clear_scan_jobs', data={'csrf_token': csrf, 'status': 'Running'},
    )
    cleared_status = client.post(
        '/clear_scan_jobs', data={'csrf_token': csrf, 'status': 'Failed'},
    )
    restarted = client.post(
        '/restart_scan_job/job-1',
        data={'csrf_token': csrf, 'queue_policy': 'queue', 'force_parallel': '1'},
    )

    assert deleted.status_code == 302
    assert missing.status_code == 404
    assert cleared_all.status_code == 302
    assert invalid_clear.status_code == 302
    assert cleared_status.status_code == 302
    assert restarted.status_code == 302
    expected_jobs = flask_redirect('/scan_management?active_tab=jobs', code=302)
    for response in (cleared_all, invalid_clear, cleared_status):
        assert response.headers['location'] == expected_jobs.headers['Location']
        assert response.headers['content-type'] == expected_jobs.headers['Content-Type']
        assert response.content == expected_jobs.get_data()
    for response in (deleted, restarted):
        assert response.headers['location'] == expected_jobs.headers['Location']
        assert response.headers['content-type'] == expected_jobs.headers['Content-Type']
        assert response.content == expected_jobs.get_data()
    assert data.calls == [
        ('delete', 'job-1'), ('delete', 'missing'), ('clear', None), ('clear', 'Failed'),
        ('restart', 'job-1', 'force', True, True),
    ]


def test_scan_job_route_matcher_limits_native_dispatch_to_expected_post_paths():
    from asgi import _is_native_scan_job_mutation_path

    assert _is_native_scan_job_mutation_path('/cancel_scan_job/abc', 'POST')
    assert _is_native_scan_job_mutation_path('/delete_scan_job/abc', 'POST')
    assert _is_native_scan_job_mutation_path('/clear_all_scan_jobs', 'POST')
    assert _is_native_scan_job_mutation_path('/clear_scan_jobs', 'POST')
    assert _is_native_scan_job_mutation_path('/restart_scan_job/abc', 'POST')
    assert not _is_native_scan_job_mutation_path('/cancel_scan_job/abc', 'GET')
