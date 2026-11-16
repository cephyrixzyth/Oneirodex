from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_policy_settings import create_admin_policy_settings_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeSettings:
    def __init__(self):
        self.saved_remote = None
        self.saved_scan = None

    def remote_read(self):
        return {'enabled': False, 'host': '', 'operator_secret_configured': False}

    def remote_save(self, payload):
        self.saved_remote = payload
        return {'enabled': True, 'operator_secret_configured': True}

    def scan_match_read(self):
        return {'max_depth': 3, 'include_extensions': ['.zip']}

    def scan_match_save(self, payload):
        self.saved_scan = payload
        return {'max_depth': payload['max_depth'], 'success': True}


def make_client(*, data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-admin-settings-secret', TESTING=True, WTF_CSRF_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, role='admin', is_active=True, state=True, is_authenticated=True)
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Please log in.',
        login_message_category='message', localize_callback=None, session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_admin_policy_settings_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '7' else None,
        login_manager=manager, data_access=data or FakeSettings(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-admin-settings-secret'))
    return client


def test_remote_play_read_has_no_store_and_credential_presence_only():
    response = make_client().get('/api/admin/remote-play/config')

    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert 'operator_secret' not in response.json()
    assert response.json()['operator_secret_configured'] is False


def test_remote_play_write_keeps_existing_api_ok_contract():
    data = FakeSettings()
    response = make_client(data=data).put(
        '/api/admin/remote-play/config', json={'enabled': True, 'host': 'moonlight.local'},
    )

    assert response.status_code == 200
    assert response.json()['status'] == 'saved'
    assert response.json()['ok'] is True
    assert data.saved_remote == {'enabled': True, 'host': 'moonlight.local'}


def test_scan_match_config_write_preserves_raw_response_shape():
    data = FakeSettings()
    response = make_client(data=data).put(
        '/api/admin/scan-match/config', json={'max_depth': 5},
    )

    assert response.status_code == 200
    assert response.json() == {'max_depth': 5, 'success': True}
    assert data.saved_scan == {'max_depth': 5}


def test_policy_config_head_preserves_legacy_non_get_validation():
    client = make_client()
    for path in (
        '/api/admin/remote-play/config',
        '/api/admin/scan-match/config',
    ):
        response = client.head(path)
        assert response.status_code == 400
        assert response.content == b''
        assert response.headers['content-length'] == '118'
