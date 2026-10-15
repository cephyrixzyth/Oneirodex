from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.ownership_admin_reads import (
    create_ownership_admin_read_router,
)
from oneirodex.runtime_native import ownership_admin_reads as native_ownership_admin
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, load_session_cookie,
)


class FakeOwnershipAdminReadData:
    def __init__(self):
        self.calls = []
        self.payload = {
            'schema_version': 1,
            'household': {'enabled': True},
            'members': [{
                'user_id': 31,
                'name': 'Example Member',
                'stores': [{
                    'provider': 'steam',
                    'state': 'connected',
                    'credential': {'source': 'member', 'household_available': False},
                    'account': {'connected': True},
                    'records': {'owned': 2, 'matched': 1, 'needs_review': 1},
                    'last_sync': None,
                    'admin_actions': ['sync'],
                }],
            }],
            'next_after_id': None,
            'stale_running_jobs': 0,
        }

    def connections(self, after_id):
        self.calls.append(after_id)
        return self.payload


def make_client(*, role='admin', data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='ownership-admin-read-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=31, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', session_protection='basic',
    )
    router = create_ownership_admin_read_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 31 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '31' else None,
        login_manager=manager,
        data_access=data or FakeOwnershipAdminReadData(),
    )
    app = FastAPI()
    app.include_router(router)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native ownership diagnostics route pushed a Flask app context')
    )
    client = TestClient(app)
    client.cookies.set(
        'session', dump_session_cookie(
            {'_user_id': '31:fp'}, 'ownership-admin-read-secret',
        ),
    )
    return client


def test_admin_get_preserves_redacted_projection_and_cursor():
    data = FakeOwnershipAdminReadData()
    response = make_client(data=data).get(
        '/api/admin/ownership/connections?after_id=12'
    )
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == {
        **data.payload, 'ok': True, 'error': None, 'error_code': None,
        'success': True,
    }
    body = response.json()
    assert body['members'][0]['name'] == 'Example Member'
    assert body['members'][0]['stores'][0]['credential']['source'] == 'member'
    assert data.calls == [12]
    serialized = response.text.lower()
    for forbidden in ('access_token', 'refresh_token', 'password', 'external_account_id'):
        assert forbidden not in serialized


def test_head_keeps_headers_and_suppresses_body():
    data = FakeOwnershipAdminReadData()
    client = make_client(data=data)
    get_response = client.get('/api/admin/ownership/connections')
    head_response = client.head('/api/admin/ownership/connections')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert data.calls == [0, 0]


def test_invalid_cursor_uses_shared_bad_request_without_reading_data():
    data = FakeOwnershipAdminReadData()
    response = make_client(data=data).get(
        '/api/admin/ownership/connections?after_id=-1'
    )
    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert data.calls == []


def test_admin_bearer_without_admin_scope_is_forbidden(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user, token=object(), has_scope=lambda scope: scope != 'admin',
        session_data={}, should_set_session_cookie=False,
    )
    monkeypatch.setattr(
        native_ownership_admin, 'request_auth_context', lambda *_args, **_kwargs: context,
    )
    data = FakeOwnershipAdminReadData()
    response = make_client(data=data).get('/api/admin/ownership/connections')
    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert data.calls == []


def test_non_admin_redirects_and_does_not_read_member_connections():
    data = FakeOwnershipAdminReadData()
    response = make_client(role='user', data=data).get(
        '/api/admin/ownership/connections', follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    session = load_session_cookie(
        response.cookies['session'], 'ownership-admin-read-secret',
        max_age=31_536_000,
    )
    assert session['_flashes'] == [
        ('danger', 'You must be an admin to access this page.'),
    ]
    assert data.calls == []
