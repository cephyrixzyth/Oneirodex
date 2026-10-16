from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_invites import create_admin_invites_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeInvites:
    def __init__(self):
        self.calls = []
        self.quota_result = {'user_id': 'member-id', 'invite_quota': 4}

    def list(self):
        return {'users': [{'id': 7, 'user_id': 'member-id', 'unused_invites': 2}]}

    def adjust_quota(self, body):
        self.calls.append((str(body.user_id), body.invites_number))
        return self.quota_result

    def rollback(self):
        self.calls.append(('rollback',))


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-admin-invites-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=18, user_id='admin-id', role=role, is_active=True, state=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint', name='Admin fixture',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeInvites()
    router = create_admin_invites_router(
        flask_app, find_user=lambda user_id: user if user_id == 18 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '18' else None,
        login_manager=manager, data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session = {'_user_id': '18:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    return client, data, csrf


def test_admin_invite_list_and_head_preserve_raw_projection():
    client, data, _csrf = _client()
    response = client.get('/admin/api/invites')
    head = client.head('/admin/api/invites')
    assert response.status_code == 200
    assert response.json() == {'users': [{'id': 7, 'user_id': 'member-id', 'unused_invites': 2}]}
    assert response.headers['cache-control'] == 'no-store'
    assert head.status_code == 200 and head.content == b''
    assert data.calls == []


def test_quota_adjustment_keeps_csrf_validation_and_unknown_user_results():
    client, data, csrf = _client()
    body = {'user_id': '4c2c4a64-6096-4e0c-b5a3-fd8583c43a64', 'invites_number': -1}
    denied = client.post('/admin/api/invites/quota', json=body)
    assert denied.status_code == 400 and not data.calls
    invalid = client.post(
        '/admin/api/invites/quota', json={**body, 'invites_number': True},
        headers={'X-CSRFToken': csrf},
    )
    accepted = client.post(
        '/admin/api/invites/quota', json=body, headers={'X-CSRFToken': csrf},
    )
    assert invalid.status_code == 422 and invalid.json()['error_code'] == 'unprocessable'
    assert accepted.status_code == 200 and accepted.json()['invite_quota'] == 4
    assert data.calls == [('4c2c4a64-6096-4e0c-b5a3-fd8583c43a64', -1)]

    data.quota_result = None
    missing = client.post(
        '/admin/api/invites/quota', json=body, headers={'X-CSRFToken': csrf},
    )
    assert missing.status_code == 404 and missing.json()['error_code'] == 'not_found'


def test_admin_invites_reject_members():
    client, data, _csrf = _client(role='user')
    response = client.get('/admin/api/invites', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
    assert data.calls == []


def test_legacy_invite_quota_form_uses_hidden_csrf_and_bounds():
    client, data, csrf = _client()
    response = client.post(
        '/admin/manage_invites',
        data={
            'csrf_token': csrf,
            'user_id': '4c2c4a64-6096-4e0c-b5a3-fd8583c43a64',
            'invites_number': '-1',
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/html')
    assert 'id="admin-app-root"' in response.text
    assert 'role="status"' in response.text
    assert 'Invites updated successfully.' in response.text
    assert data.calls == [('4c2c4a64-6096-4e0c-b5a3-fd8583c43a64', -1)]

    invalid, invalid_data, invalid_csrf = _client()
    denied = invalid.post(
        '/admin/manage_invites',
        data={'csrf_token': invalid_csrf, 'user_id': 'bad', 'invites_number': '1001'},
        follow_redirects=False,
    )
    assert denied.status_code == 302
    assert invalid_data.calls == []


def test_legacy_invite_form_renders_updated_shell_when_user_is_missing():
    client, data, csrf = _client()
    data.quota_result = None
    response = client.post(
        '/admin/manage_invites',
        data={
            'csrf_token': csrf,
            'user_id': '4c2c4a64-6096-4e0c-b5a3-fd8583c43a64',
            'invites_number': '1',
        },
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert 'role="alert"' in response.text
    assert 'User not found.' in response.text
    assert data.calls == [('4c2c4a64-6096-4e0c-b5a3-fd8583c43a64', 1)]
