from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import rom_translate as native_rom_translate
from oneirodex.runtime_native.rom_translate import create_rom_translate_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


def make_client(*, role='admin', authenticated=True, forbid_app_context=True):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-rom-translate-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    if forbid_app_context:
        flask_app.app_context = lambda: (_ for _ in ()).throw(
            AssertionError('ROM translate route pushed a Flask app context')
        )
    user = SimpleNamespace(
        id=217, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_rom_translate_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 217 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '217' else None,
        login_manager=manager,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '217:fp'}, 'native-rom-translate-secret')
        )
    return client


def test_admin_capabilities_keep_bare_payload_and_head():
    client = make_client()
    response = client.get('/api/rom-translate/capabilities')
    assert response.status_code == 200
    assert response.json()['offline_enabled'] is False
    assert response.json()['platforms']
    assert 'ok' not in response.json()
    assert response.headers['X-Content-Type-Options'] == 'nosniff'

    head = client.head('/api/rom-translate/capabilities')
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_anonymous_redirect_keeps_next_and_signed_login_flash():
    response = make_client(authenticated=False).get(
        '/api/rom-translate/capabilities?source=admin', follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fapi%2From-translate%2Fcapabilities%3Fsource%3Dadmin'
    )
    session = load_session_cookie(
        response.cookies['session'], 'native-rom-translate-secret', max_age=31_536_000,
    )
    assert session['_flashes'][-1] == ('message', 'Please log in to access this page.')


def test_non_admin_keeps_danger_flash_and_admin_tokens_need_scope(monkeypatch):
    response = make_client(role='user').get(
        '/api/rom-translate/capabilities', follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    session = load_session_cookie(
        response.cookies['session'], 'native-rom-translate-secret', max_age=31_536_000,
    )
    assert session['_flashes'][-1] == ('danger', 'You must be an admin to access this page.')

    context = SimpleNamespace(
        user=SimpleNamespace(role='admin', is_authenticated=True),
        token=object(), has_scope=lambda scope: scope != 'admin', session_data={},
        should_set_session_cookie=False,
    )
    monkeypatch.setattr(native_rom_translate, 'request_auth_context', lambda *_a, **_kw: context)
    denied = make_client().get('/api/rom-translate/capabilities')
    assert denied.status_code == 403
    assert denied.json()['error_code'] == 'forbidden'
