from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask

from oneirodex.runtime_native.oidc_auth import create_oidc_auth_router
from oneirodex.runtime_native.session_compat import load_session_cookie


class FakeOidcClient:
    def __init__(self):
        self.authorize = None
        self.access = None
        self.nonce = None
        self.userinfo_claims = None

    async def create_authorization_url(self, **kwargs):
        self.authorize = kwargs
        return {'url': 'https://idp.example/authorize?state=' + kwargs['state']}

    async def fetch_access_token(self, **kwargs):
        self.access = kwargs
        return {'id_token': 'opaque-id-token'}

    async def parse_id_token(self, token, *, nonce):
        self.nonce = nonce
        return {'sub': 'subject-1', 'email': 'user@example.test', 'email_verified': True}

    async def userinfo(self, *, token):
        return self.userinfo_claims or {}


class FakeOidcData:
    def __init__(self):
        self.client = FakeOidcClient()
        self.provisioned = []
        self.logged = []
        self.user = SimpleNamespace(name='User', get_id=lambda: '7:fingerprint')

    def settings(self):
        return SimpleNamespace(
            oidc_enabled=True, oidc_issuer_url='https://idp.example',
            oidc_client_id='client', oidc_client_secret='secret',
            oidc_redirect_uri='https://app.example/login/oidc/callback',
            oidc_scopes='openid email profile', oidc_role_claim='groups',
            oidc_role_map=None, oidc_display_name='SSO',
        )

    def provision(self, claims, config, app):
        self.provisioned.append((claims, config.issuer_url))
        return self.user

    def rollback(self):
        pass

    def log_login(self, user):
        self.logged.append(user.name)


@pytest.fixture
def native_client(monkeypatch):
    from oneirodex.utils import oidc

    monkeypatch.setenv('OIDC_ENABLED', 'true')
    monkeypatch.setattr(oidc, 'AUTHLIB_AVAILABLE', True)
    app = Flask('native-oidc-tests')
    app.config.update(
        SECRET_KEY='oidc-secret', SESSION_PROTECTION='none',
        SESSION_COOKIE_SAMESITE='Lax', OIDC_LOCK_ROLES=True,
    )
    data = FakeOidcData()
    user = SimpleNamespace(id=7, name='User', role='user', state=True, is_active=True)
    runtime = FastAPI()
    runtime.include_router(create_oidc_auth_router(
        app, find_user=lambda _id: user, find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: user if user_id == '7:fingerprint' else None,
        data_access=data, database_scope=lambda _app: nullcontext(),
        client_factory=lambda _config: data.client,
    ))
    return runtime, data


def test_native_oidc_pkce_flow_sets_state_nonce_and_remember_session(native_client):
    runtime, data = native_client

    async def flow():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='https://app.example',
        ) as client:
            start = await client.get('/login/oidc?next=%2Flibraries')
            assert start.status_code == 302
            assert start.headers['location'].startswith('https://idp.example/authorize?state=')
            assert start.headers.get('set-cookie')
            state_cookie = client.cookies.get('session')
            session = load_session_cookie(state_cookie, 'oidc-secret', max_age=31_536_000)
            assert session['oidc_auth_state'] == data.client.authorize['state']
            assert session['oidc_code_verifier']
            assert session['oidc_nonce'] == data.client.authorize['nonce']
            callback = await client.get(
                '/login/oidc/callback?code=auth-code&next=%2Flibraries&state='
                + session['oidc_auth_state']
            )
            return callback

    callback = asyncio.run(flow())
    assert callback.status_code == 302
    assert callback.headers['location'] == '/libraries'
    assert data.client.access['code'] == 'auth-code'
    assert data.client.access['code_verifier']
    assert data.client.nonce
    assert data.provisioned[0][0]['sub'] == 'subject-1'
    assert data.logged == ['User']
    assert 'remember_token=' in callback.headers.get('set-cookie', '')


def test_native_oidc_client_does_not_require_flask_authlib(monkeypatch):
    from oneirodex.runtime_native.oidc_auth import _make_oidc_client
    from oneirodex.utils import oidc

    monkeypatch.setattr(oidc, 'OAuth', None)
    monkeypatch.setattr(oidc, 'AUTHLIB_FLASK_AVAILABLE', False)
    assert oidc.AUTHLIB_NATIVE_AVAILABLE
    config = SimpleNamespace(
        scopes='openid email', client_secret='secret', client_id='client',
        issuer_url='https://idp.example',
    )

    client = _make_oidc_client(config)

    assert client is not None
    assert client.client_id == 'client'


def test_native_session_cookie_preserves_configured_samesite_spelling():
    from starlette.responses import Response
    from oneirodex.runtime_native.oidc_status import _set_session_cookie

    app = Flask('native-session-cookie-test')
    app.config.update(
        SECRET_KEY='session-cookie-secret',
        SESSION_COOKIE_SAMESITE='Lax',
    )
    response = Response()

    _set_session_cookie(response, app, SimpleNamespace(session_data={'_fresh': True}))

    cookie = response.headers['set-cookie']
    assert 'session=' in cookie
    assert 'SameSite=Lax' in cookie


def test_native_oidc_rejects_state_mismatch_and_clears_state(native_client):
    runtime, data = native_client

    async def flow():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='https://app.example',
        ) as client:
            await client.get('/login/oidc')
            return await client.get('/login/oidc/callback?code=auth-code&state=wrong')

    callback = asyncio.run(flow())
    assert callback.status_code == 302
    assert callback.headers['location'] == '/login'
    assert not data.provisioned
    session = load_session_cookie(
        callback.cookies.get('session'), 'oidc-secret', max_age=31_536_000,
    )
    assert 'oidc_auth_state' not in session


@pytest.mark.parametrize('userinfo_subject, expected_status', [
    ('subject-1', 302),
    ('different-subject', 302),
])
def test_native_oidc_sparse_id_token_userinfo_is_subject_bound(
    native_client, monkeypatch, userinfo_subject, expected_status,
):
    runtime, data = native_client
    data.client.userinfo_claims = {
        'sub': userinfo_subject,
        'email': 'profile@example.test',
        'preferred_username': 'profile-user',
        'groups': ['OneirodexAdmins'],
    }
    async def sparse_id_token(_token, *, nonce):
        data.client.nonce = nonce
        return {'sub': 'subject-1'}

    monkeypatch.setattr(data.client, 'parse_id_token', sparse_id_token)

    async def flow():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='https://app.example',
        ) as client:
            await client.get('/login/oidc')
            session = load_session_cookie(
                client.cookies.get('session'), 'oidc-secret', max_age=31_536_000,
            )
            return await client.get(
                '/login/oidc/callback?code=auth-code&state=' + session['oidc_auth_state']
            )

    callback = asyncio.run(flow())
    assert callback.status_code == expected_status
    if userinfo_subject == 'subject-1':
        assert callback.headers['location'] == '/discover'
        claims = data.provisioned[0][0]
        assert claims['sub'] == 'subject-1'
        assert claims['email'] == 'profile@example.test'
        assert claims['preferred_username'] == 'profile-user'
        assert claims['groups'] == ['OneirodexAdmins']
    else:
        assert callback.headers['location'] == '/login'
        assert not data.provisioned
