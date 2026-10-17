from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_users_read import create_admin_users_read_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeUsers:
    def list(self):
        return {'users': [{
            'id': 2, 'email': '', 'has_email': False, 'name': 'Living Room',
            'role': 'user', 'state': True, 'is_email_verified': False,
            'about': '', 'avatarpath': '',
        }]}

    def detail(self, user_id):
        if user_id != 7:
            return None
        return {'email': '', 'has_email': False, 'allowed_library_uuids': ['lib-a']}


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-admin-users-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=18, user_id='admin-id', role=role, is_active=True, state=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_admin_users_read_router(
        flask_app, find_user=lambda user_id: user if user_id == 18 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '18' else None,
        login_manager=manager, data_access=FakeUsers(),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set(
        'session', dump_session_cookie(
            {'_user_id': '18:fingerprint', '_fresh': True}, flask_app.config['SECRET_KEY'],
        ),
    )
    return client


def test_admin_user_roster_keeps_privacy_projection_and_head():
    client = _client()
    response = client.get('/admin/api/users')
    head = client.head('/admin/api/users')
    assert response.status_code == 200
    assert response.json()['users'][0]['email'] == ''
    assert response.json()['users'][0]['has_email'] is False
    assert head.status_code == 200 and head.content == b''
    assert response.headers['cache-control'] == 'no-store'


def test_admin_user_detail_read_preserves_allowlist_projection():
    client = _client()
    response = client.get('/admin/api/user/7')
    missing = client.get('/admin/api/user/404')
    assert response.status_code == 200
    assert response.json()['allowed_library_uuids'] == ['lib-a']
    assert response.json()['has_email'] is False
    assert missing.status_code == 404 and missing.json()['error_code'] == 'not_found'


def test_admin_user_roster_rejects_member_and_unauthenticated_requests():
    member = _client(role='user').get('/admin/api/users', follow_redirects=False)
    anonymous_client = _client()
    anonymous_client.cookies.clear()
    anonymous = anonymous_client.get('/admin/api/users', follow_redirects=False)
    assert member.status_code == anonymous.status_code == 302
    assert member.headers['location'].startswith('/login')
    assert anonymous.headers['location'].startswith('/login')
    assert anonymous.headers['content-type'] == 'text/html; charset=utf-8'
    assert len(anonymous.headers.get_list('set-cookie')) == 1
