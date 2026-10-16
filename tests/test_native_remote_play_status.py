from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.remote_play_status import create_remote_play_status_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeRemotePlayData:
    def __init__(self):
        self.calls = 0
        self.payload = {
            'enabled': True,
            'configured': True,
            'provider': 'sunshine',
            'moonlight_host': '192.168.1.50',
            'moonlight_port': 47989,
            'host_label': 'Gaming PC',
            'app_hint': 'Steam',
            'pin_hint': 'Pair first',
            'token_hint': 'member-safe masked hint',
            'copy_hint': 'Gaming PC — 192.168.1.50:47989 — App: Steam',
        }

    def status(self, *, config=None):
        self.calls += 1
        return self.payload


def make_client(*, authenticated=True, data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-remote-play-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=31, role='user', is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_remote_play_status_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 31 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '31' else None,
        login_manager=manager,
        data_access=data or FakeRemotePlayData(),
    )
    app = FastAPI()
    app.include_router(router)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '31:fp'}, 'native-remote-play-secret')
        )
    return client


def test_member_status_returns_existing_safe_payload_without_admin_config_or_secrets():
    data = FakeRemotePlayData()
    response = make_client(data=data).get('/api/remote-play/status')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    body = response.json()
    assert body == data.payload
    assert data.calls == 1
    forbidden_keys = {
        'remote_play_token', 'token', 'token_set', 'sunshine_base_url',
        'wolf_base_url', 'remote_play_settings', 'client_secret', 'admin_config',
    }
    assert forbidden_keys.isdisjoint(body)
    assert 'remote_play_token' not in response.text
    assert 'client_secret' not in response.text


def test_disabled_member_status_keeps_the_minimal_legacy_payload():
    data = FakeRemotePlayData()
    data.payload = {'enabled': False, 'configured': False}
    response = make_client(data=data).get('/api/remote-play/status')
    assert response.status_code == 200
    assert response.json() == {'enabled': False, 'configured': False}


def test_head_preserves_headers_and_content_length_but_has_no_body():
    data = FakeRemotePlayData()
    client = make_client(data=data)
    get_response = client.get('/api/remote-play/status')
    head_response = client.head('/api/remote-play/status')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert data.calls == 2


def test_anonymous_status_redirects_with_login_flash_and_next_without_reading_data():
    data = FakeRemotePlayData()
    response = make_client(authenticated=False, data=data).get(
        '/api/remote-play/status?from=member', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fapi%2Fremote-play%2Fstatus%3Ffrom%3Dmember'
    )
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    session = load_session_cookie(
        response.cookies['session'], 'native-remote-play-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == 0


def test_member_status_config_projection_does_not_need_flask_context(monkeypatch):
    from oneirodex.utils.remote_play import member_remote_play_status, remote_play_enabled
    from oneirodex.utils import remote_play

    assert remote_play_enabled(config={'ENABLE_REMOTE_PLAY': True}) is True
    monkeypatch.setattr(remote_play, '_settings_row', lambda: None)
    assert member_remote_play_status(config={'ENABLE_REMOTE_PLAY': False}) == {
        'enabled': False, 'configured': False,
    }
