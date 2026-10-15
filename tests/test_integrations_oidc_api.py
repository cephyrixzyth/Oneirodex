from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf

from oneirodex.routes_apis import apis_bp
from oneirodex.routes_apis import integrations as routes


class Actor(UserMixin):
    id = 'admin'
    role = 'admin'


@pytest.fixture
def oidc_api(monkeypatch):
    app = Flask(__name__)
    app.secret_key = 'oidc-native-test'
    app.config['TESTING'] = True
    manager = LoginManager(app)
    manager.user_loader(lambda identity: Actor())
    CSRFProtect(app)
    app.register_blueprint(apis_bp)
    app.add_url_rule('/csrf', view_func=lambda: generate_csrf())
    row = SimpleNamespace(
        oidc_enabled=False, oidc_display_name='Sign in with SSO', oidc_issuer_url=None,
        oidc_client_id=None, oidc_client_secret='secret-never-return', oidc_redirect_uri=None,
        oidc_scopes='openid email profile', oidc_role_claim='groups', oidc_role_map={'admin': 'admin'},
        last_updated=None, community_chat_url=None, community_chat_label=None,
    )
    session = Mock()
    monkeypatch.setattr(routes, 'global_settings_row', lambda: row)
    monkeypatch.setattr(routes, 'global_settings_row_or_create', lambda: row)
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(routes, 'cache', SimpleNamespace(delete=Mock()))
    monkeypatch.setattr(routes, 'log_system_event', Mock())
    monkeypatch.setattr(routes, 'oidc_readiness_report', lambda value: {'ready': False, 'message': 'Not ready', 'missing': []})
    monkeypatch.setattr(routes, 'is_secure_oidc_issuer', lambda value: value.startswith('https://'))
    client = app.test_client()
    with client.session_transaction() as session_cookie:
        session_cookie['_user_id'] = 'admin'
        session_cookie['_fresh'] = True
    csrf = client.get('/csrf').text
    return client, row, session, {'X-CSRFToken': csrf}


def payload():
    return {
        'oidc_enabled': False, 'oidc_display_name': 'Sign in with SSO',
        'oidc_issuer_url': '', 'oidc_client_id': '', 'oidc_client_secret': '',
        'oidc_redirect_uri': '', 'oidc_scopes': 'openid email profile',
        'oidc_role_claim': 'groups', 'oidc_role_map': {'admin': 'admin'},
    }


def test_get_never_returns_oidc_secret(oidc_api):
    client, row, _, _ = oidc_api
    response = client.get('/api/admin/integrations/oidc')
    assert response.status_code == 200
    assert response.json['settings']['oidc_client_secret_configured'] is True
    assert 'oidc_client_secret' not in response.json['settings']
    assert 'secret-never-return' not in response.text
    assert 'no-store' in response.headers['Cache-Control']


def test_put_preserves_blank_secret_and_persists_complete_form(oidc_api):
    client, row, session, headers = oidc_api
    body = payload()
    body.update(oidc_enabled=True, oidc_issuer_url='https://id.example.test',
                oidc_client_id='client', oidc_redirect_uri='https://app.example.test/callback',
                oidc_role_map={'admins': 'admin'})
    response = client.put('/api/admin/integrations/oidc', json=body, headers=headers)
    assert response.status_code == 200
    assert row.oidc_enabled is True and row.oidc_issuer_url == 'https://id.example.test'
    assert row.oidc_client_secret == 'secret-never-return'
    assert row.oidc_role_map == {'admins': 'admin'}
    assert session.commit.call_count == 1
    assert 'secret-never-return' not in response.text


@pytest.mark.parametrize('patch', [
    {'oidc_enabled': 'true'}, {'oidc_issuer_url': 'http://id.example.test'},
    {'oidc_role_map': {'x': 'owner'}},
    {'oidc_scopes': 'x' * 256}, {'extra': 'field'},
])
def test_put_rejects_invalid_oidc_config_without_writes(oidc_api, patch):
    client, row, session, headers = oidc_api
    body = payload(); body.update(patch)
    response = client.put('/api/admin/integrations/oidc', json=body, headers=headers)
    assert response.status_code == 400
    session.commit.assert_not_called()


def test_put_requires_csrf(oidc_api):
    client, row, session, _ = oidc_api
    assert client.put('/api/admin/integrations/oidc', json=payload()).status_code == 400
    session.commit.assert_not_called()


def test_enabling_oidc_requires_issuer_client_and_redirect(oidc_api):
    client, row, session, headers = oidc_api
    body = payload(); body['oidc_enabled'] = True
    response = client.put('/api/admin/integrations/oidc', json=body, headers=headers)
    assert response.status_code == 400
    session.commit.assert_not_called()


def test_community_settings_get_and_put(oidc_api):
    client, row, session, headers = oidc_api
    response = client.get('/api/admin/integrations/community')
    assert response.status_code == 200
    assert response.json['community_chat_url'] == ''
    assert 'no-store' in response.headers['Cache-Control']

    response = client.put('/api/admin/integrations/community', json={
        'community_chat_url': 'https://chat.example.test/invite',
        'community_chat_label': 'Join chat',
    }, headers=headers)
    assert response.status_code == 200
    assert row.community_chat_url == 'https://chat.example.test/invite'
    assert row.community_chat_label == 'Join chat'
    session.commit.assert_called_once()


@pytest.mark.parametrize('url', ['http://localhost/invite', 'javascript:alert(1)', 'x' * 513])
def test_community_settings_reject_unsafe_or_oversized_urls(oidc_api, url):
    client, _, session, headers = oidc_api
    response = client.put('/api/admin/integrations/community', json={
        'community_chat_url': url, 'community_chat_label': 'Join chat',
    }, headers=headers)
    assert response.status_code == 400
    session.commit.assert_not_called()


def test_community_settings_requires_csrf(oidc_api):
    client, _, session, _ = oidc_api
    response = client.put('/api/admin/integrations/community', json={
        'community_chat_url': '', 'community_chat_label': 'Open community',
    })
    assert response.status_code == 400
    session.commit.assert_not_called()
