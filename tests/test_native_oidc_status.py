from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import oidc_status as native_oidc
from oneirodex.runtime_native.oidc_status import create_oidc_status_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeReport:
    def __init__(self):
        self.calls = 0
        self.payload = {
            'ready': False,
            'live_verified': False,
            'env_enabled': False,
            'db_enabled': False,
            'authlib_available': True,
            'has_issuer': False,
            'has_client_id': False,
            'has_redirect_uri': False,
            'trusted_proxies': 0,
            'missing': ['OIDC_ENABLED env', 'issuer_url'],
            'message': 'OIDC is not ready — missing: OIDC_ENABLED env, issuer_url',
            'runbook': 'docs/runbooks/oidc-sso.md',
        }

    def report(self):
        self.calls += 1
        return self.payload


def make_client(*, role='admin', data=None, login_view='login.login'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-oidc-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=23, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view=login_view,
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_oidc_status_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 23 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '23' else None,
        login_manager=manager,
        data_access=data or FakeReport(),
    )
    app = FastAPI()
    app.include_router(router)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native OIDC status route pushed a Flask app context')
    )
    client = TestClient(app)
    client.cookies.set(
        'session', dump_session_cookie({'_user_id': '23:fp'}, 'native-oidc-secret')
    )
    return client


def test_admin_get_returns_the_exact_readiness_payload_without_envelope():
    data = FakeReport()
    response = make_client(data=data).get('/api/oidc/status')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == data.payload
    assert 'ok' not in response.json()
    assert data.calls == 1


def test_head_preserves_status_headers_and_length_but_omits_body():
    data = FakeReport()
    client = make_client(data=data)
    get_response = client.get('/api/oidc/status')
    head_response = client.head('/api/oidc/status')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert data.calls == 2


def test_non_admin_redirects_with_admin_flash_without_next_and_skips_readiness():
    data = FakeReport()
    response = make_client(role='user', data=data).get(
        '/api/oidc/status', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    session = load_session_cookie(
        response.cookies['session'], 'native-oidc-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('danger', 'You must be an admin to access this page.')]
    assert data.calls == 0


def test_anonymous_request_redirects_with_next_and_login_flash():
    from oneirodex.runtime_native.request_auth import RequestAuthContext

    response_auth = RequestAuthContext(
        session_data={}, original_session={}, resolution=SimpleNamespace(
            user=None, token=None, source='anonymous', session_protected=False,
        ), session_cookie_name='session', remember_cookie_name='remember_token',
        session_refresh_each_request=True,
    )

    def anonymous_context(*_args, **_kwargs):
        return response_auth

    original = native_oidc.request_auth_context
    native_oidc.request_auth_context = anonymous_context
    try:
        response = make_client().get(
            '/api/oidc/status?from=admin', follow_redirects=False
        )
    finally:
        native_oidc.request_auth_context = original
    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Foidc%2Fstatus%3Ffrom%3Dadmin'
    session = load_session_cookie(
        response.cookies['session'], 'native-oidc-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]


def test_admin_bearer_without_admin_scope_gets_shared_forbidden_envelope(monkeypatch):
    user = SimpleNamespace(role='admin', is_authenticated=True)
    context = SimpleNamespace(
        user=user,
        token=object(),
        has_scope=lambda scope: scope != 'admin',
        session_data={},
    )
    monkeypatch.setattr(native_oidc, 'request_auth_context', lambda *_args, **_kwargs: context)
    data = FakeReport()
    response = make_client(data=data).get('/api/oidc/status')
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'This token does not have the admin scope',
        'error_code': 'forbidden',
        'message': 'This token does not have the admin scope',
        'success': False,
    }
    assert data.calls == 0
