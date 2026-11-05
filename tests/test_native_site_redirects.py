from __future__ import annotations

import asyncio
import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import timedelta
import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager
from starlette.requests import Request
from werkzeug.exceptions import MethodNotAllowed
from werkzeug.utils import redirect as werkzeug_redirect

from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.runtime_native.session_compat import load_session_cookie
from oneirodex.runtime_native.response_compat import flask_redirect_response
from oneirodex.runtime_native.response_compat import flask_http_exception_response
from oneirodex.runtime_native.runtime_context import NativeRuntimeContext
from oneirodex.runtime_native.site_redirects import create_site_redirect_router
from oneirodex.routes_site import site_bp


@dataclass
class User:
    id: int = 7
    role: str = 'user'
    state: bool = True
    is_active: bool = True
    password_hash: str = 'route-test-password'

    def session_fingerprint(self):
        return hashlib.sha256(self.password_hash.encode()).hexdigest()[:16]


def _client(monkeypatch, *, user=None, setup_required=False, setup_in_progress=False):
    from oneirodex.utils import setup

    monkeypatch.setattr(setup, 'is_setup_required', lambda: setup_required)
    monkeypatch.setattr(setup, 'is_setup_in_progress', lambda: setup_in_progress)
    monkeypatch.setattr(setup, 'get_setup_redirect_url', lambda: '/setup/features')
    runtime_app = NativeRuntimeContext(
        {
            'SECRET_KEY': 'site-redirect-secret',
            'SESSION_COOKIE_NAME': 'session',
            'PERMANENT_SESSION_LIFETIME': timedelta(hours=1),
            'SESSION_PROTECTION': 'none',
            'SESSION_REFRESH_EACH_REQUEST': True,
            'SESSION_COOKIE_SAMESITE': 'Lax',
            'CSP_ENABLED': False,
        },
        package_root='.',
    )
    runtime_app.login_manager.login_view = '/login'
    app = FastAPI()
    app.include_router(create_site_redirect_router(
        runtime_app,
        find_user=lambda user_id: user if user and user_id == user.id else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        database_scope=lambda _app: nullcontext(),
    ))
    cookie = None
    if user:
        user_id = f'{user.id}:{user.session_fingerprint()}'
        cookie = dump_session_cookie({'_user_id': user_id, '_fresh': True}, 'site-redirect-secret')
    return app, cookie


def _request(app, method, path, cookie=None, extra_headers=None):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://localhost',
        ) as client:
            headers = dict(extra_headers or {})
            if cookie:
                headers['Cookie'] = f'session={cookie}'
            return await client.request(method, path, headers=headers)

    return asyncio.run(run())


@pytest.mark.parametrize('location', [
    '/login',
    '/login?next=%2Fbrowse%3Fpage%3D2%26sort%3Dname',
    '/login?next=%2Fquoted%3Fx%3D%2522',
])
def test_compat_redirect_response_matches_werkzeug(location):
    current = flask_redirect_response(location)
    legacy = werkzeug_redirect(location)

    assert current.status_code == legacy.status_code
    assert current.headers['location'] == legacy.headers['Location']
    assert current.headers['content-type'] == legacy.headers['Content-Type']
    assert current.headers['content-length'] == legacy.headers['Content-Length']
    assert current.body == legacy.get_data()


def test_entry_redirects_to_login_or_discover_for_get_post_and_head(monkeypatch):
    user = User()
    app, cookie = _client(monkeypatch, user=user)
    assert _request(app, 'GET', '/', cookie).headers['location'] == '/discover'
    missing_csrf = _request(app, 'POST', '/index', cookie)
    assert missing_csrf.status_code == 400
    assert missing_csrf.headers['content-type'] == 'text/html; charset=utf-8'
    assert missing_csrf.headers['x-content-type-options'] == 'nosniff'
    assert missing_csrf.headers['referrer-policy'] == 'strict-origin-when-cross-origin'
    assert missing_csrf.headers['x-frame-options'] == 'SAMEORIGIN'
    assert 'permissions-policy' in missing_csrf.headers
    assert missing_csrf.text == (
        '<!doctype html>\n<html lang=en>\n<title>400 Bad Request</title>\n'
        '<h1>Bad Request</h1>\n<p>The CSRF token is missing.</p>\n'
    )

    session_data = {
        '_user_id': f'{user.id}:{user.session_fingerprint()}',
        '_fresh': True,
    }
    csrf_token = generate_csrf_token(session_data, 'site-redirect-secret')
    valid_cookie = dump_session_cookie(session_data, 'site-redirect-secret')
    assert _request(
        app, 'POST', '/index', valid_cookie, {'X-CSRFToken': csrf_token},
    ).headers['location'] == '/discover'
    assert _request(app, 'HEAD', '/', cookie).headers['location'] == '/discover'

    anonymous, _ = _client(monkeypatch)
    entry = _request(anonymous, 'GET', '/')
    legacy_entry = werkzeug_redirect('/login')
    assert entry.status_code == legacy_entry.status_code
    assert entry.headers['location'] == legacy_entry.headers['Location']
    assert entry.headers['content-type'] == legacy_entry.headers['Content-Type']
    assert entry.headers['content-length'] == legacy_entry.headers['Content-Length']
    assert entry.content == legacy_entry.get_data()
    anonymous_post = _request(anonymous, 'POST', '/index')
    assert anonymous_post.status_code == 400
    assert anonymous_post.text == missing_csrf.text
    head = _request(anonymous, 'HEAD', '/')
    assert head.status_code == 302
    assert head.headers['location'] == '/login'
    assert head.content == b''

    legacy_app = Flask(__name__)
    legacy_app.add_url_rule('/', view_func=lambda: werkzeug_redirect('/login'))
    legacy_head = legacy_app.test_client().head('/')
    assert head.headers['content-type'] == legacy_head.headers['Content-Type']
    assert head.headers['content-length'] == legacy_head.headers['Content-Length']


def test_entry_redirects_to_current_setup_step_before_auth(monkeypatch):
    app, cookie = _client(monkeypatch, user=User(), setup_in_progress=True)
    assert _request(app, 'GET', '/', cookie).headers['location'] == '/setup/features'


@pytest.mark.parametrize('path', ['/', '/index'])
def test_authenticated_permanent_entry_refresh_matches_flask_session_cookie(monkeypatch, path):
    from oneirodex.utils import setup

    user = User()
    user_id = f'{user.id}:{user.session_fingerprint()}'
    secret = 'site-redirect-secret'
    session_data = {
        '_user_id': user_id,
        '_fresh': True,
        '_permanent': True,
    }
    monkeypatch.setattr(setup, 'is_setup_required', lambda: False)
    monkeypatch.setattr(setup, 'is_setup_in_progress', lambda: False)

    native, _ = _client(monkeypatch, user=user)
    native_response = _request(
        native, 'GET', path, dump_session_cookie(session_data, secret),
    )

    class FlaskUser(User):
        @property
        def is_authenticated(self):
            return True

        def get_id(self):
            return user_id

    legacy_user = FlaskUser()
    legacy = Flask('legacy-site-entry-test')
    legacy.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_NAME='session',
        PERMANENT_SESSION_LIFETIME=3600,
        SESSION_PROTECTION='none',
        SESSION_REFRESH_EACH_REQUEST=True,
        SESSION_COOKIE_SECURE=False,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    login_manager = LoginManager(legacy)
    login_manager.user_loader(
        lambda identity: legacy_user if identity == legacy_user.get_id() else None
    )
    legacy.add_url_rule(
        '/discover', endpoint='discover.discover', view_func=lambda: 'discover',
    )
    legacy.register_blueprint(site_bp)
    with legacy.test_client() as client:
        with client.session_transaction() as session:
            session.update(session_data)
        legacy_response = client.get('/')

    assert native_response.status_code == legacy_response.status_code == 302
    assert native_response.headers['location'] == legacy_response.headers['Location'] == '/discover'
    assert native_response.headers['content-type'] == legacy_response.headers['Content-Type']
    assert native_response.headers['content-length'] == legacy_response.headers['Content-Length']
    assert native_response.content == legacy_response.get_data()
    native_set_cookie = native_response.headers.get('set-cookie')
    legacy_set_cookie = legacy_response.headers.get('Set-Cookie')
    assert native_set_cookie and legacy_set_cookie
    for attribute in ('HttpOnly', 'Path=/', 'SameSite=Lax'):
        assert attribute.lower() in native_set_cookie.lower()
        assert attribute.lower() in legacy_set_cookie.lower()
    native_cookie_value = native_set_cookie.split(';', 1)[0].split('=', 1)[1]
    legacy_cookie_value = legacy_set_cookie.split(';', 1)[0].split('=', 1)[1]
    assert load_session_cookie(native_cookie_value, secret, max_age=3600) == (
        load_session_cookie(legacy_cookie_value, secret, max_age=3600)
    )


@pytest.mark.parametrize('path', ['/', '/index'])
@pytest.mark.parametrize('setup_required', [False, True])
def test_entry_options_matches_flask_setup_gate_and_allow_header(
    monkeypatch, path, setup_required,
):
    from flask import redirect
    from oneirodex.utils import setup

    native, _ = _client(monkeypatch, setup_required=setup_required)
    legacy = Flask('legacy-site-options-test')
    legacy.config.update(SECRET_KEY='site-redirect-secret')
    legacy.register_blueprint(site_bp)

    @legacy.before_request
    def setup_gate():
        if setup_required:
            return redirect('/setup/features')
        return None

    monkeypatch.setattr(setup, 'is_setup_required', lambda: setup_required)
    monkeypatch.setattr(setup, 'is_setup_in_progress', lambda: False)
    monkeypatch.setattr(setup, 'get_setup_redirect_url', lambda: '/setup/features')
    native_response = _request(native, 'OPTIONS', path)
    legacy_response = legacy.test_client().options(path)

    assert native_response.status_code == legacy_response.status_code
    assert native_response.headers.get('location') == legacy_response.headers.get('Location')
    assert native_response.headers.get('content-type') == legacy_response.headers.get('Content-Type')
    assert native_response.headers.get('content-length') == legacy_response.headers.get('Content-Length')
    assert native_response.content == legacy_response.get_data()
    native_allow = native_response.headers.get('allow')
    legacy_allow = legacy_response.headers.get('Allow')
    assert (native_allow is None) == (legacy_allow is None)
    if native_allow and legacy_allow:
        assert {method.strip() for method in native_allow.split(',')} == {
            method.strip() for method in legacy_allow.split(',')
        }


@pytest.mark.parametrize('path', ['/', '/index'])
def test_entry_405_allow_header_preserves_legacy_order(monkeypatch, path):
    app, _ = _client(monkeypatch)
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': 'PUT',
        'scheme': 'http',
        'path': path,
        'raw_path': path.encode(),
        'query_string': b'',
        'root_path': '',
        'headers': [],
        'server': ('localhost', 80),
        'client': ('testclient', 50000),
    }
    request = Request(scope)
    response = flask_http_exception_response({}, request, 405, route_app=app)
    expected = MethodNotAllowed(
        valid_methods=['POST', 'HEAD', 'GET', 'OPTIONS'],
    ).get_response()

    assert response.status_code == expected.status_code == 405
    assert response.headers['Allow'] == expected.headers['Allow']
    assert response.body == expected.get_data()


def test_restricted_redirect_preserves_login_next_and_authenticated_landing(monkeypatch):
    anonymous, _ = _client(monkeypatch)
    response = _request(anonymous, 'GET', '/restricted')
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Frestricted'
    )
    assert response.headers['cache-control'] == 'no-store'
    session_cookie = response.cookies.get('session')
    assert session_cookie
    assert len(response.headers.get_list('set-cookie')) == 1
    decoded = load_session_cookie(session_cookie, 'site-redirect-secret', max_age=3600)
    assert decoded['_flashes'] == [('message', 'Please log in to access this page.')]

    authenticated, cookie = _client(monkeypatch, user=User())
    response = _request(authenticated, 'GET', '/restricted', cookie)
    assert response.status_code == 302
    assert response.headers['location'] == '/discover'


@pytest.mark.parametrize(
    ('user', 'setup_required', 'setup_in_progress'),
    [
        (None, True, False),
        (User(), False, True),
    ],
)
def test_restricted_and_account_compat_routes_redirect_to_setup_before_auth(
    monkeypatch, user, setup_required, setup_in_progress,
):
    app, cookie = _client(
        monkeypatch, user=user, setup_required=setup_required,
        setup_in_progress=setup_in_progress,
    )

    for path in (
        '/restricted',
        '/settings_profile_view',
        '/settings_password',
        '/settings_panel',
    ):
        response = _request(app, 'GET', path, cookie)
        assert response.status_code == 302
        assert response.headers['location'] == '/setup/features'
        legacy = werkzeug_redirect('/setup/features')
        assert response.headers['content-type'] == legacy.headers['Content-Type']
        assert response.headers['content-length'] == legacy.headers['Content-Length']
        assert response.content == legacy.get_data()

        head = _request(app, 'HEAD', path, cookie)
        assert head.status_code == 302
        assert head.headers['location'] == '/setup/features'
        assert head.content == b''
        assert head.headers['content-type'] == legacy.headers['Content-Type']
        assert head.headers['content-length'] == legacy.headers['Content-Length']


def test_settings_page_get_redirects_keep_legacy_account_destinations(monkeypatch):
    user = User()
    app, cookie = _client(monkeypatch, user=user)
    expected = {
        '/settings_profile_view': '/library?account=profile',
        '/settings_password': '/library?account=password',
        '/settings_panel': '/library?preferences=1',
    }
    for path, target in expected.items():
        response = _request(app, 'GET', path, cookie)
        assert response.status_code == 302
        assert response.headers['location'] == target
        assert response.headers['cache-control'] == 'no-store'

        assert _request(app, 'HEAD', path, cookie).status_code == 302
