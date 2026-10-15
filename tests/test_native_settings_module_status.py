from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import settings_module_status as native_status
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie
from oneirodex.runtime_native.settings_module_status import create_settings_module_status_router


class FakeModuleStatusData:
    def __init__(self):
        self.calls = 0
        self.payload = {
            'arr': {'on': True, 'label': 'On'},
            'ai': {'on': False, 'label': 'Off'},
            'storage': {'on': True, 'label': 'On', 'detail': 'Apply off'},
        }

    def status(self, *, config=None):
        self.calls += 1
        return self.payload


def make_client(*, role='admin', authenticated=True, data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-settings-status-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=41, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_settings_module_status_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 41 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '41' else None,
        login_manager=manager,
        data_access=data or FakeModuleStatusData(),
    )
    app = FastAPI()
    app.include_router(router)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '41:fp'}, 'native-settings-status-secret')
        )
    return client


def test_admin_get_returns_exact_bare_json_payload():
    data = FakeModuleStatusData()
    response = make_client(data=data).get('/api/settings/module-status')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == data.payload
    assert 'ok' not in response.json()
    assert data.calls == 1


def test_head_keeps_status_headers_and_content_length_without_body():
    data = FakeModuleStatusData()
    client = make_client(data=data)
    get_response = client.get('/api/settings/module-status')
    head_response = client.head('/api/settings/module-status')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert data.calls == 2


def test_anonymous_request_gets_login_redirect_and_flash_without_data_access():
    data = FakeModuleStatusData()
    response = make_client(authenticated=False, data=data).get(
        '/api/settings/module-status?from=hub', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fapi%2Fsettings%2Fmodule-status%3Ffrom%3Dhub'
    )
    session = load_session_cookie(
        response.cookies['session'], 'native-settings-status-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == 0


def test_non_admin_gets_admin_flash_redirect_without_next_or_data_access():
    data = FakeModuleStatusData()
    response = make_client(role='user', data=data).get(
        '/api/settings/module-status?from=hub', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    session = load_session_cookie(
        response.cookies['session'], 'native-settings-status-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('danger', 'You must be an admin to access this page.')]
    assert data.calls == 0


def test_admin_token_without_admin_scope_gets_forbidden_envelope(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_status, 'request_auth_context', lambda *_args, **_kwargs: context)
    data = FakeModuleStatusData()
    response = make_client(data=data).get('/api/settings/module-status')
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'This token does not have the admin scope',
        'error_code': 'forbidden',
        'message': 'This token does not have the admin scope',
        'success': False,
    }
    assert data.calls == 0
