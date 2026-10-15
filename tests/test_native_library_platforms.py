from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import library_platforms as native_platforms
from oneirodex.runtime_native.library_platforms import create_library_platforms_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeLibraryPlatforms:
    def __init__(self):
        self.values = [
            SimpleNamespace(name='PC', value='Windows PC'),
            SimpleNamespace(name='NES', value='Nintendo Entertainment System'),
        ]
        self.calls = 0

    def platforms(self):
        self.calls += 1
        return self.values


def make_client(*, role='admin', authenticated=True, data=None, admin2_login=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-library-platforms-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.add_url_rule('/custom-admin-login', endpoint='custom_admin_login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=127, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={'admin2': admin2_login} if admin2_login else {},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_library_platforms_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 127 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '127' else None,
        login_manager=manager,
        data_access=data or FakeLibraryPlatforms(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '127:fp'}, 'native-library-platforms-secret')
        )
    return client


def test_admin_get_returns_platforms_with_exact_api_ok_envelope():
    data = FakeLibraryPlatforms()
    response = make_client(data=data).get('/api/admin/library_platforms')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == {
        'platforms': [
            {'key': 'PC', 'label': 'Windows PC'},
            {'key': 'NES', 'label': 'Nintendo Entertainment System'},
        ],
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert data.calls == 1


def test_anonymous_redirect_prefers_admin2_blueprint_login_view_and_flashes():
    data = FakeLibraryPlatforms()
    response = make_client(
        authenticated=False, data=data, admin2_login='/custom-admin-login'
    ).get('/api/admin/library_platforms?from=library', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/custom-admin-login?next=%2Fapi%2Fadmin%2Flibrary_platforms%3Ffrom%3Dlibrary'
    )
    session = load_session_cookie(
        response.cookies['session'], 'native-library-platforms-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == 0


def test_non_admin_redirects_to_login_with_admin_flash_without_next():
    data = FakeLibraryPlatforms()
    response = make_client(role='user', data=data).get(
        '/api/admin/library_platforms?from=library', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    session = load_session_cookie(
        response.cookies['session'], 'native-library-platforms-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('danger', 'You must be an admin to access this page.')]
    assert data.calls == 0


def test_admin_token_without_admin_scope_returns_shared_forbidden_error(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_platforms, 'request_auth_context', lambda *_args, **_kwargs: context)
    data = FakeLibraryPlatforms()
    response = make_client(data=data).get('/api/admin/library_platforms')
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'This token does not have the admin scope',
        'error_code': 'forbidden',
        'message': 'This token does not have the admin scope',
        'success': False,
    }
    assert data.calls == 0


def test_head_has_same_status_headers_and_content_length_without_body():
    data = FakeLibraryPlatforms()
    client = make_client(data=data)
    get_response = client.get('/api/admin/library_platforms')
    head_response = client.head('/api/admin/library_platforms')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert head_response.headers['X-Content-Type-Options'] == 'nosniff'
    assert data.calls == 2
