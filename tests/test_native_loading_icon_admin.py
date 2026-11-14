from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask
from werkzeug.utils import redirect as werkzeug_redirect

from oneirodex.runtime_native import loading_icon_admin as native_loading_icon_admin
from oneirodex.runtime_native.loading_icon_admin import create_loading_icon_admin_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token, load_session_cookie


class FakeLoadingIconData:
    def __init__(self):
        self.payload = {
            'loading_icon_mode': 'rotate', 'loading_icon_id': None, 'resolved_id': None,
            'catalogue': [{'id': 'dpad', 'name': 'D-pad'}],
            'defaults': {'loading_icon_mode': 'rotate', 'loading_icon_id': None},
            'modes': ['lock', 'rotate'], 'stored_mode': 'rotate', 'stored_id': None,
        }
        self.saved = []

    def public(self):
        return {
            'loading_icon_mode': 'rotate', 'loading_icon_id': None,
            'resolved_id': None, 'catalogue': self.payload['catalogue'],
        }

    def get(self):
        return self.payload

    def save(self, body):
        self.saved.append(body)
        if body.get('loading_icon_mode') == 'invalid':
            raise ValueError('Invalid loading icon mode')
        return {**self.payload, 'loading_icon_mode': body.get('loading_icon_mode', 'rotate')}


def make_client(*, role='admin', authenticated=True, data=None):
    secret = 'native-loading-icon-secret'
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY=secret, TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native loading-icon route pushed a Flask app context')
    )
    user = SimpleNamespace(id=218, role=role, is_active=True, state=True, is_authenticated=True)
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.', login_message_category='message',
        localize_callback=None, session_protection='basic',
    )
    adapter = data or FakeLoadingIconData()
    router = create_loading_icon_admin_router(
        flask_app,
        find_user=lambda uid: user if authenticated and uid == 218 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '218' else None,
        login_manager=manager,
        data_access=adapter,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.native_data = adapter
    client.native_secret = secret
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '218:fp', '_fresh': True}, secret),
        )
    return client


def _csrf(client):
    state = {'_user_id': '218:fp', '_fresh': True}
    token = generate_csrf_token(state, client.native_secret)
    client.cookies.clear()
    client.cookies.set(
        'session', dump_session_cookie(state, client.native_secret),
        domain='testserver.local', path='/',
    )
    return token


def test_admin_read_and_head_preserve_bare_payload():
    client = make_client()
    response = client.get('/api/admin/loading-icon/config')
    assert response.status_code == 200
    assert response.json() == client.native_data.payload
    assert 'ok' not in response.json()
    head = client.head('/api/admin/loading-icon/config')
    assert head.status_code == 400 and head.content == b''
    assert head.headers['content-length'] == '118'


def test_admin_theme_loading_icons_alias_preserves_legacy_envelope():
    client = make_client()
    response = client.get('/api/admin/themes/loading-icons')
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['catalogue'] == client.native_data.payload['catalogue']
    head = client.head('/api/admin/themes/loading-icons')
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_public_read_uses_native_scope_and_member_safe_payload():
    client = make_client()
    response = client.get('/api/loading-icon')
    assert response.status_code == 200
    assert response.json() == client.native_data.public()
    assert 'modes' not in response.json()
    assert client.head('/api/loading-icon').content == b''


def test_put_preserves_csrf_order_validation_and_success_envelope():
    client = make_client()
    path = '/api/admin/loading-icon/config'
    missing_csrf = client.put(path, json={'loading_icon_mode': 'lock'})
    assert missing_csrf.status_code == 400
    assert client.native_data.saved == []

    headers = {'X-CSRFToken': _csrf(client)}
    saved = client.put(path, json={'loading_icon_mode': 'lock', 'loading_icon_id': 'dpad'}, headers=headers)
    assert saved.status_code == 200
    assert saved.json()['status'] == 'saved'
    assert saved.json()['ok'] is True
    assert client.native_data.saved == [{'loading_icon_mode': 'lock', 'loading_icon_id': 'dpad'}]

    invalid = client.put(
        path, json={'loading_icon_mode': 'invalid'}, headers={'X-CSRFToken': _csrf(client)},
    )
    assert invalid.status_code == 400
    assert invalid.json()['error'] == 'Invalid loading icon mode'


def test_auth_and_admin_gates_preserve_redirect_and_flash_behavior():
    path = '/api/admin/loading-icon/config'
    anonymous = make_client(authenticated=False).get(path, follow_redirects=False)
    assert anonymous.status_code == 302
    anon_session = load_session_cookie(
        anonymous.cookies['session'], 'native-loading-icon-secret', max_age=31_536_000,
    )
    assert anon_session['_flashes'][-1] == ('message', 'Please log in to access this page.')

    member = make_client(role='user').get(path, follow_redirects=False)
    assert member.status_code == 302 and member.headers['location'] == '/login'
    expected_redirect = werkzeug_redirect('/login')
    assert member.content == expected_redirect.get_data()
    assert member.headers['content-type'] == expected_redirect.headers['Content-Type']
    member_session = load_session_cookie(
        member.cookies['session'], 'native-loading-icon-secret', max_age=31_536_000,
    )
    assert member_session['_flashes'][-1] == ('danger', 'You must be an admin to access this page.')

    member_client = make_client(role='user')
    denied_put = member_client.put(
        path,
        json={'loading_icon_mode': 'rotate'},
        headers={'X-CSRFToken': _csrf(member_client)},
        follow_redirects=False,
    )
    assert denied_put.status_code == 302 and denied_put.headers['location'] == '/login'
    assert denied_put.content == expected_redirect.get_data()
    assert member_client.native_data.saved == []


def test_admin_bearer_requires_admin_scope(monkeypatch):
    context = SimpleNamespace(
        user=SimpleNamespace(role='admin', is_authenticated=True), token=object(),
        has_scope=lambda scope: scope != 'admin', session_data={},
        should_set_session_cookie=False,
    )
    monkeypatch.setattr(native_loading_icon_admin, 'request_auth_context', lambda *_a, **_kw: context)
    response = make_client().get('/api/admin/loading-icon/config')
    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
