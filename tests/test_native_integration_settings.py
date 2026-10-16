from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.integration_settings import create_integration_settings_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeSettings:
    def __init__(self):
        self.oidc_saved = None
        self.community_saved = None

    def oidc_read(self):
        return {'settings': {'oidc_client_secret_configured': True}, 'readiness': {'ready': True}}

    def oidc_save(self, payload):
        self.oidc_saved = payload
        return {'settings': {'oidc_client_secret_configured': bool(payload['oidc_client_secret'])}, 'readiness': {}}

    def community_read(self):
        return {'community_chat_url': '', 'community_chat_label': 'Open community'}

    def community_save(self, url, label):
        self.community_saved = (url, label)
        return {'community_chat_url': url, 'community_chat_label': label.strip() or 'Open community'}


def make_client(*, role='admin', data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-integration-settings-secret', TESTING=True,
        WTF_CSRF_ENABLED=False,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=7, role=role, is_active=True, state=True, is_authenticated=True)
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None, session_protection='basic',
    )
    router = create_integration_settings_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '7' else None,
        login_manager=manager, data_access=data or FakeSettings(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-integration-settings-secret'))
    return client


def test_oidc_read_is_no_store_and_never_returns_a_secret_value():
    response = make_client().get('/api/admin/integrations/oidc')

    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['settings'] == {'oidc_client_secret_configured': True}


def test_oidc_write_validates_https_and_passes_complete_payload_to_adapter():
    data = FakeSettings()
    payload = {
        'oidc_enabled': True, 'oidc_display_name': 'Household SSO',
        'oidc_issuer_url': 'https://id.example.test', 'oidc_client_id': 'client',
        'oidc_client_secret': '', 'oidc_redirect_uri': 'https://app.example.test/callback',
        'oidc_scopes': 'openid email profile', 'oidc_role_claim': 'groups',
        'oidc_role_map': {'admins': 'admin'},
    }
    response = make_client(data=data).put('/api/admin/integrations/oidc', json=payload)

    assert response.status_code == 200
    assert data.oidc_saved == payload
    assert response.json()['settings']['oidc_client_secret_configured'] is False

    payload['oidc_issuer_url'] = 'http://id.example.test'
    response = make_client(data=data).put('/api/admin/integrations/oidc', json=payload)
    assert response.status_code == 400
    assert data.oidc_saved['oidc_issuer_url'] == 'https://id.example.test'


def test_community_write_validates_and_normalizes_url(monkeypatch):
    from oneirodex.utils import security

    monkeypatch.setattr(security, 'validate_community_chat_url', lambda value: (True, value.rstrip('/')))
    data = FakeSettings()
    response = make_client(data=data).put(
        '/api/admin/integrations/community',
        json={'community_chat_url': 'https://community.example.test/', 'community_chat_label': 'Chat'},
    )

    assert response.status_code == 200
    assert data.community_saved == ('https://community.example.test', 'Chat')
    assert response.json()['community_chat_url'] == 'https://community.example.test'


def test_integration_settings_denies_non_admin_before_read():
    data = FakeSettings()
    response = make_client(role='user', data=data).get(
        '/api/admin/integrations/community', follow_redirects=False,
    )

    assert response.status_code == 302
    assert data.community_saved is None


def test_oidc_payload_limit_is_enforced_before_json_parse():
    response = make_client().put(
        '/api/admin/integrations/oidc', content=b' ' * (16 * 1024 + 1),
        headers={'content-type': 'application/json'},
    )

    assert response.status_code == 400


def test_legacy_integration_post_aliases_use_native_validators(monkeypatch):
    from oneirodex.utils import security

    monkeypatch.setattr(security, 'validate_community_chat_url', lambda value: (True, value.rstrip('/')))
    data = FakeSettings()
    client = make_client(data=data)
    oidc = {
        'oidc_enabled': True, 'oidc_display_name': 'SSO',
        'oidc_issuer_url': 'https://id.example.test', 'oidc_client_id': 'client',
        'oidc_client_secret': '', 'oidc_redirect_uri': 'https://app.example.test/callback',
        'oidc_scopes': 'openid email profile', 'oidc_role_claim': 'groups',
        'oidc_role_map': {'admins': 'admin'},
    }
    oidc_response = client.post(
        '/admin/integrations/oidc/save', json=oidc,
        headers={'X-CSRFToken': 'test-token'},
    )
    community_response = client.post(
        '/admin/integrations/community',
        json={'community_chat_url': 'https://community.example.test/', 'community_chat_label': 'Chat'},
        headers={'X-CSRFToken': 'test-token'},
    )

    assert oidc_response.status_code == 200
    assert data.oidc_saved == oidc
    assert community_response.status_code == 200
    assert data.community_saved == ('https://community.example.test', 'Chat')


def test_legacy_integration_post_aliases_validate_csrf_before_body():
    response = make_client().post(
        '/admin/integrations/oidc/save', json={}, follow_redirects=False,
    )
    assert response.status_code == 400
