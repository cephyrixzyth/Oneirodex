from __future__ import annotations

import asyncio
import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from werkzeug.utils import redirect as werkzeug_redirect

from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.runtime_native.session_compat import load_session_cookie
from oneirodex.runtime_native.response_compat import flask_redirect_response
from oneirodex.runtime_native.runtime_context import NativeRuntimeContext
from oneirodex.runtime_native.site_redirects import create_site_redirect_router


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
            'PERMANENT_SESSION_LIFETIME': 3600,
            'SESSION_PROTECTION': 'none',
            'SESSION_REFRESH_EACH_REQUEST': True,
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
