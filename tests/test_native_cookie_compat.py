"""Native session cookie flags must work on Python 3.12 as on Flask."""
from datetime import timedelta
import importlib
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import Response

from tests.cookie_helpers import parse_set_cookies


WRITERS = ['oidc_status', 'browse', 'acquire_status', 'release_calendar', 'trailers']


def _config(partitioned):
    return {
        'TESTING': True,
        'PERSISTENT_SESSIONS_ENABLED': False,
        'SECRET_KEY': 'synthetic-cookie-contract-key',
        'PERMANENT_SESSION_LIFETIME': timedelta(days=30),
        'SESSION_COOKIE_NAME': 'session',
        'SESSION_COOKIE_PATH': '/household',
        'SESSION_COOKIE_DOMAIN': 'example.test',
        'SESSION_COOKIE_SECURE': False,
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SAMESITE': 'Lax',
        'SESSION_COOKIE_PARTITIONED': partitioned,
    }


def _assert_cookie(response, partitioned):
    cookie, flag = parse_set_cookies(response.headers.getlist('set-cookie'))['session']
    assert flag is partitioned
    assert bool(cookie['secure']) is partitioned
    assert cookie['httponly'] is True
    assert cookie['path'] == '/household'
    assert cookie['domain'] == 'example.test'
    assert cookie['samesite'].lower() == 'lax'


@pytest.mark.parametrize('writer', WRITERS)
@pytest.mark.parametrize('partitioned', [False, True])
def test_native_session_writers_preserve_partitioned_policy(writer, partitioned):
    module = importlib.import_module('oneirodex.runtime_native.' + writer)
    response = Response()
    module._set_session_cookie(
        response, SimpleNamespace(config=_config(partitioned)),
        SimpleNamespace(session_data={'notice': 'fixture'}),
    )
    _assert_cookie(response, partitioned)


@pytest.mark.parametrize('path', ['/api/account/sessions', '/api/account/sessions/current'])
@pytest.mark.parametrize('partitioned', [False, True])
def test_session_revocation_clears_cookie_with_matching_flags(monkeypatch, path, partitioned):
    from starlette.testclient import TestClient
    from fastapi import FastAPI
    from oneirodex.runtime_native import account_sessions, db_session
    from oneirodex.utils import persistent_sessions

    config = _config(partitioned) | {'WTF_CSRF_ENABLED': False}
    auth = SimpleNamespace(user=SimpleNamespace(id=7), session_data={})
    monkeypatch.setattr(account_sessions, 'request_auth_context', lambda *a, **kw: auth)
    monkeypatch.setattr(persistent_sessions, 'session_id_from_identity', lambda value: 'current')
    monkeypatch.setattr(persistent_sessions, 'revoke_login_session', lambda *a, **kw: True)
    monkeypatch.setattr(persistent_sessions, 'revoke_all_login_sessions', lambda *a: 1)
    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=SimpleNamespace(commit=lambda: None)))
    app = FastAPI()
    app.include_router(account_sessions.create_account_sessions_router(
        SimpleNamespace(config=config), find_user=lambda value: None,
        find_token=lambda value: None, commit_token_touch=lambda value: None,
    ))
    with TestClient(app, base_url='https://example.test') as client:
        response = client.delete(path)
    assert response.status_code == 200
    wire = SimpleNamespace(headers=SimpleNamespace(getlist=response.headers.get_list))
    _assert_cookie(wire, partitioned)
    cookie, _ = parse_set_cookies(response.headers.get_list('set-cookie'))['session']
    assert cookie['max-age'] == '0'


@pytest.mark.parametrize('partitioned', [False, True])
def test_native_bootstrap_preserves_partitioned_policy(partitioned):
    from oneirodex.runtime_native.auth_runtime_bootstrap import member_auth_runtime_bootstrap

    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []})
    response = member_auth_runtime_bootstrap(
        SimpleNamespace(config=_config(partitioned)), request, auth_fields=lambda: {},
    )
    _assert_cookie(response, partitioned)
