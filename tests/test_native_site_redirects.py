from __future__ import annotations

import asyncio
import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from oneirodex.runtime_native.session_compat import dump_session_cookie
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
    runtime_app = type('RuntimeConfig', (), {
        'config': {
            'SECRET_KEY': 'site-redirect-secret',
            'SESSION_COOKIE_NAME': 'session',
            'PERMANENT_SESSION_LIFETIME': 3600,
            'SESSION_PROTECTION': 'none',
            'SESSION_REFRESH_EACH_REQUEST': True,
            'CSP_ENABLED': False,
        },
        'login_manager': SimpleNamespace(
            login_view='/login',
            login_message='Please log in to access this page.',
            login_message_category='message',
        ),
    })()
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


def _request(app, method, path, cookie=None):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://localhost',
        ) as client:
            headers = {'Cookie': f'session={cookie}'} if cookie else None
            return await client.request(method, path, headers=headers)

    return asyncio.run(run())


def test_entry_redirects_to_login_or_discover_for_get_post_and_head(monkeypatch):
    user = User()
    app, cookie = _client(monkeypatch, user=user)
    assert _request(app, 'GET', '/', cookie).headers['location'] == '/discover'
    assert _request(app, 'POST', '/index', cookie).headers['location'] == '/discover'
    assert _request(app, 'HEAD', '/', cookie).headers['location'] == '/discover'

    anonymous, _ = _client(monkeypatch)
    assert _request(anonymous, 'GET', '/').headers['location'] == '/login'
    assert _request(anonymous, 'POST', '/index').headers['location'] == '/login'


def test_entry_redirects_to_current_setup_step_before_auth(monkeypatch):
    app, cookie = _client(monkeypatch, user=User(), setup_in_progress=True)
    assert _request(app, 'GET', '/', cookie).headers['location'] == '/setup/features'


def test_restricted_redirect_preserves_login_next_and_authenticated_welcome(monkeypatch):
    anonymous, _ = _client(monkeypatch)
    response = _request(anonymous, 'GET', '/restricted')
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Frestricted'
    )
    assert response.headers['cache-control'] == 'no-store'

    authenticated, cookie = _client(monkeypatch, user=User())
    response = _request(authenticated, 'GET', '/restricted', cookie)
    assert response.status_code == 302
    assert response.headers['location'] == '/welcome'


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
