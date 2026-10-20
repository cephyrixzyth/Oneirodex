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
        self.userinfo_calls = 0

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
        self.userinfo_calls += 1
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
                '/login/oidc/callback?code=auth-code&code=untrusted'
                '&next=%2Flibraries&next=https%3A%2F%2Fevil.example&state='
                + session['oidc_auth_state'] + '&state=untrusted'
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


@pytest.mark.parametrize('path', ['/login/oidc', '/login/oidc/callback'])
def test_native_oidc_head_matches_get_redirect_headers_without_body(native_client, path):
    runtime, _data = native_client

    async def request(method):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='https://app.example',
        ) as client:
            return await client.request(method, path)

    get_response, head_response = asyncio.run(
        _gather_requests(request('GET'), request('HEAD'))
    )

    assert head_response.status_code == get_response.status_code == 302
    assert head_response.headers.get('content-type', '').split(';')[0] == 'text/html'
    assert get_response.headers.get('content-type', '').split(';')[0] == 'text/html'
    assert head_response.headers['content-length'] == str(len(get_response.content))
    if path == '/login/oidc':
        assert head_response.headers['location'].startswith('https://idp.example/authorize?state=')
        assert get_response.headers['location'].startswith('https://idp.example/authorize?state=')
        assert head_response.headers.get('set-cookie')
        assert get_response.headers.get('set-cookie')
    else:
        assert head_response.headers['location'] == get_response.headers['location'] == '/login'
    assert head_response.content == b''


async def _gather_requests(*awaitables):
    return await asyncio.gather(*awaitables)


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


@pytest.mark.parametrize('userinfo_source', ['token_response', 'userinfo_endpoint'])
def test_native_oidc_rejects_userinfo_without_validated_id_token(
    native_client, monkeypatch, userinfo_source,
):
    runtime, data = native_client
    claims = {
        'sub': 'subject-without-id-token',
        'email': 'untrusted@example.test',
        'email_verified': True,
        'preferred_username': 'Untrusted',
    }
    data.client.userinfo_claims = claims

    async def fetch_access_token(**kwargs):
        data.client.access = kwargs
        token = {'access_token': 'synthetic-access-token'}
        if userinfo_source == 'token_response':
            token['userinfo'] = claims
        return token

    monkeypatch.setattr(data.client, 'fetch_access_token', fetch_access_token)

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
    assert callback.status_code == 302
    assert callback.headers['location'] == '/login'
    assert not data.provisioned
    assert not data.logged
    assert data.client.userinfo_calls == 0
    assert 'remember_token=' not in callback.headers.get('set-cookie', '')
    session = load_session_cookie(
        callback.cookies.get('session'), 'oidc-secret', max_age=31_536_000,
    )
    assert '_user_id' not in session
    assert 'oidc_auth_state' not in session
    assert data.client.nonce is None


@pytest.mark.parametrize('id_token_value', ['', 7])
def test_native_oidc_rejects_invalid_id_token_before_parsing(
    native_client, monkeypatch, id_token_value,
):
    runtime, data = native_client
    data.client.userinfo_claims = {'sub': 'subject-1', 'email': 'user@example.test'}

    async def fetch_access_token(**kwargs):
        data.client.access = kwargs
        return {'access_token': 'synthetic-access-token', 'id_token': id_token_value}

    monkeypatch.setattr(data.client, 'fetch_access_token', fetch_access_token)

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
    assert callback.headers['location'] == '/login'
    assert data.client.nonce is None
    assert data.client.userinfo_calls == 0
    assert not data.provisioned


@pytest.mark.parametrize('parsed_subject', [None, '', 7])
def test_native_oidc_rejects_missing_or_invalid_parsed_subject_before_userinfo(
    native_client, monkeypatch, parsed_subject,
):
    runtime, data = native_client
    data.client.userinfo_claims = {
        'sub': 'subject-from-userinfo', 'email': 'userinfo@example.test',
    }

    async def parse_id_token(_token, *, nonce):
        data.client.nonce = nonce
        claims = {'email': 'token@example.test'}
        if parsed_subject is not None:
            claims['sub'] = parsed_subject
        return claims

    monkeypatch.setattr(data.client, 'parse_id_token', parse_id_token)

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
    assert callback.headers['location'] == '/login'
    assert data.client.nonce
    assert data.client.userinfo_calls == 0
    assert not data.provisioned


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
    assert data.client.userinfo_calls == 1


def test_native_oidc_successful_callback_matches_checked_in_flask_fallback_contract(
    native_client, monkeypatch,
):
    """Compare the successful callback's claims, navigation and session effects."""
    from flask import Flask
    from flask_login import LoginManager

    from oneirodex import routes_login as legacy_login
    from oneirodex.runtime_native.auth_resolver import decode_remember_cookie

    runtime, data = native_client
    claims = {
        'sub': 'subject-1', 'email': 'user@example.test',
        'email_verified': True, 'preferred_username': 'User',
        'groups': ['OneirodexMembers'],
    }
    data.client.userinfo_claims = claims

    legacy_user = SimpleNamespace(
        name='User', is_active=True, get_id=lambda: '7:fingerprint',
    )
    legacy_events = []
    legacy_provisioned = []
    legacy_client = SimpleNamespace(oidc=SimpleNamespace(
        authorize_access_token=lambda **kwargs: (
            legacy_events.append(('token', kwargs)) or {'userinfo': claims}
        ),
    ))
    monkeypatch.setattr(legacy_login, 'global_settings_row', lambda: object())
    monkeypatch.setattr(
        legacy_login, 'build_oidc_config', lambda _settings: data.settings(),
    )
    monkeypatch.setattr(legacy_login, 'AUTHLIB_FLASK_AVAILABLE', True)
    monkeypatch.setattr(legacy_login, 'init_oauth', lambda _app: None)
    monkeypatch.setattr(legacy_login, 'register_oidc_provider', lambda *_args: None)
    monkeypatch.setattr(legacy_login, 'get_oauth_client', lambda: legacy_client)
    monkeypatch.setattr(
        legacy_login, 'provision_or_update_user',
        lambda _session, received, _config: legacy_provisioned.append(received) or legacy_user,
    )
    monkeypatch.setattr(
        legacy_login, 'log_system_event',
        lambda message, **kwargs: legacy_events.append(('login', message, kwargs)),
    )

    legacy_app = Flask('legacy-oidc-parity')
    legacy_app.config.update(
        SECRET_KEY='oidc-secret', TESTING=True,
        SESSION_PROTECTION='none', SESSION_COOKIE_SAMESITE='Lax',
    )
    manager = LoginManager(legacy_app)
    manager.user_loader(
        lambda identity: legacy_user if identity == legacy_user.get_id() else None,
    )
    legacy_app.register_blueprint(legacy_login.login_bp)
    legacy_app.add_url_rule(
        '/discover', endpoint='discover.discover', view_func=lambda: 'discover',
    )
    legacy_browser = legacy_app.test_client()
    with legacy_browser.session_transaction() as session:
        session['oidc_auth_state'] = 'paired-state'
        session['oidc_code_verifier'] = 'paired-verifier'
    legacy_response = legacy_browser.get(
        '/login/oidc/callback?code=paired-code&state=paired-state&next=%2Flibraries',
        headers={'User-Agent': 'Oneirodex-Parity-Test/1.0'},
    )

    async def native_callback():
        transport = httpx.ASGITransport(app=runtime, client=('127.0.0.1', 50000))
        async with httpx.AsyncClient(
            transport=transport, base_url='https://app.example',
            headers={'User-Agent': 'Oneirodex-Parity-Test/1.0'},
        ) as browser:
            start = await browser.get('/login/oidc')
            assert start.status_code == 302
            session = load_session_cookie(
                browser.cookies.get('session'), 'oidc-secret', max_age=31_536_000,
            )
            return await browser.get(
                '/login/oidc/callback?code=paired-code&state='
                + session['oidc_auth_state'] + '&next=%2Flibraries'
            )

    native_response = asyncio.run(native_callback())

    assert legacy_response.status_code == native_response.status_code == 302
    assert (
        legacy_response.headers['Location']
        == native_response.headers['location']
        == '/libraries'
    )
    assert legacy_events[0] == (
        'token', {'code_verifier': 'paired-verifier'},
    )
    assert data.client.access['code'] == 'paired-code'
    assert data.client.access['code_verifier']
    assert legacy_provisioned == [data.provisioned[0][0]] == [claims]
    assert legacy_events[-1][1] == 'User User logged in via OIDC SSO.'
    assert legacy_events[-1][2] == {
        'event_type': 'login', 'event_level': 'information',
    }
    assert data.logged == ['User']

    legacy_session_cookie = legacy_browser.get_cookie('session').value
    native_session_cookie = native_response.cookies.get('session')
    legacy_session = load_session_cookie(
        legacy_session_cookie, 'oidc-secret', max_age=31_536_000,
    )
    native_session = load_session_cookie(
        native_session_cookie, 'oidc-secret', max_age=31_536_000,
    )
    for key in ('_user_id', '_fresh', '_id'):
        assert legacy_session[key] == native_session[key]
    assert not (
        {'oidc_auth_state', 'oidc_code_verifier', 'oidc_nonce'}
        & native_session.keys()
    )
    legacy_remember = legacy_response.headers.getlist('Set-Cookie')
    native_remember = native_response.headers.get_list('set-cookie')
    legacy_cookie_header = next(
        value for value in legacy_remember if value.startswith('remember_token=')
    )
    native_cookie_header = next(
        value for value in native_remember if value.startswith('remember_token=')
    )
    from http.cookies import SimpleCookie

    parsed_legacy = SimpleCookie()
    parsed_legacy.load(legacy_cookie_header)
    parsed_native = SimpleCookie()
    parsed_native.load(native_cookie_header)
    assert (
        decode_remember_cookie(
            parsed_legacy['remember_token'].value, 'oidc-secret',
        ) == '7:fingerprint'
    )
    assert (
        decode_remember_cookie(
            parsed_native['remember_token'].value, 'oidc-secret',
        ) == '7:fingerprint'
    )
    for key in ('path', 'httponly', 'secure', 'samesite'):
        assert parsed_legacy['remember_token'][key] == parsed_native['remember_token'][key]
