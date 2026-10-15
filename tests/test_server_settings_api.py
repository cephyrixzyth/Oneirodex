"""Server controls, safe projection and partial updates without shared persistence."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf
import oneirodex.routes_admin_ext.settings as routes


class ReviewUser(UserMixin):
    def __init__(self, role): self.id = role; self.role = role


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__); app.config.update(TESTING=True, SECRET_KEY='server-api-test-only')
    manager = LoginManager(app); manager.login_view = 'login.login'; manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login'); app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app); app.register_blueprint(routes.admin2_bp)
    settings = SimpleNamespace(settings={**routes.DEFAULT_SETTINGS, 'private_token': 'private-secret', 'unrelated': {'nested': [1, 2]}, 'matchHighThreshold': 0.87}, **{field: routes.DEFAULT_SETTINGS[key] for key, field in routes.FIELD_MAPPINGS.items()}, oidc_enabled=False, igdb_client_secret='hidden-secret', last_updated=None)
    session = Mock(); audit = Mock(); cache = Mock()
    monkeypatch.setattr(routes, 'global_settings_row', lambda: settings); monkeypatch.setattr(routes, 'global_settings_row_or_create', lambda: settings)
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session)); monkeypatch.setattr(routes, 'log_system_event', audit); monkeypatch.setattr(routes, 'cache', cache)
    client = app.test_client()
    with client.session_transaction() as value: value['_user_id'] = 'admin'; value['_fresh'] = True
    return client, settings, session, audit, cache, {'X-CSRFToken': client.get('/csrf').text}


def test_get_only_28_controls_with_bounds_and_safe_default(harness):
    client, _, session, *_ = harness
    response = client.get('/api/admin/server-settings')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert set(response.json['settings']) == routes.SERVER_FIELDS and len(response.json['settings']) == 28
    assert response.json['settings']['allowUsersToInviteOthers'] is False
    assert response.json['bounds']['turboDownloadThreads']['max'] == 20
    assert response.json['bounds']['turboDownloadBatchSize']['max'] == 1000
    assert 'private-secret' not in response.text and 'hidden-secret' not in response.text
    session.commit.assert_not_called()


def test_server_settings_document_uses_shared_shell_and_defers_state_to_api(harness, monkeypatch):
    client, *_ = harness
    rendered = []
    monkeypatch.setattr(routes, 'global_settings_row', Mock(side_effect=AssertionError('page GET must use the API')))
    monkeypatch.setattr(routes, 'render_admin_spa', lambda *, title: rendered.append(title) or '<main>shell</main>')
    response = client.get('/admin/new_server_settings')
    assert response.status_code == 200 and response.text == '<main>shell</main>'
    assert rendered == ['Server settings · Oneirodex Admin']


def test_partial_save_preserves_all_unrelated_json_and_columns(harness):
    client, settings, session, audit, cache, headers = harness
    response = client.put('/api/admin/server-settings', json={'updateFolderName': 'patches', 'showHelpButton': False}, headers=headers)
    assert response.status_code == 200
    assert settings.update_folder_name == 'patches'
    assert settings.settings['showHelpButton'] is False
    assert settings.settings['unrelated'] == {'nested': [1, 2]}
    assert settings.settings['matchHighThreshold'] == 0.87 and settings.settings['private_token'] == 'private-secret'
    assert settings.enable_delete_game_on_disk is True and settings.write_local_metadata is True
    assert settings.oidc_enabled is False and settings.igdb_client_secret == 'hidden-secret'
    assert settings.last_updated is not None
    session.commit.assert_called_once(); audit.assert_called_once(); cache.delete.assert_called_once_with('global_settings')


def test_all_28_explicit_changes_map_only_page_owned_fields(harness):
    client, settings, _, _, _, headers = harness
    values = routes.public_server_settings(settings)
    values.update(turboDownloadThreads=20, turboDownloadBatchSize=1000, scanThreadCount=4, hltbRateLimitDelay=0.5, enableDeleteGameOnDisk=False, writeLocalMetadata=False)
    response = client.put('/api/admin/server-settings', json=values, headers=headers)
    assert response.status_code == 200 and response.json['settings'] == values
    for key, field in routes.FIELD_MAPPINGS.items():
        assert getattr(settings, field) == values[key]
    assert settings.settings['unrelated'] == {'nested': [1, 2]}


@pytest.mark.parametrize('payload', [None, [], {}, {'OIDC_ENABLED': True}, {'private_token': 'change'},
    {'showVersion': 'false'}, {'showVersion': 1}, {'scanThreadCount': True}, {'scanThreadCount': 1.5},
    {'scanThreadCount': 0}, {'turboDownloadThreads': 21}, {'turboDownloadBatchSize': 1001},
    {'hltbRateLimitDelay': True}, {'hltbRateLimitDelay': float('nan')}, {'hltbRateLimitDelay': float('inf')},
    {'siteUrl': 'ftp://host'}, {'siteUrl': 'https://user:secret@host'}, {'siteUrl': 'https://host:bad'},
    {'siteUrl': 'x' * 256}, {'updateFolderName': ''}, {'updateFolderName': '../updates'},
    {'updateFolderName': '/updates'}, {'updateFolderName': 'C:\\updates'}, {'extrasFolderName': '\\\\server\\share'}, {'extrasFolderName': 'C:extras'},
    {'extrasFolderName': 'folder\nsecret'}, {'localMetadataFilename': 'file.txt'}, {'localMetadataFilename': '../file.json'}])
def test_invalid_strict_payloads_do_not_persist(harness, payload):
    client, _, session, audit, cache, headers = harness
    response = client.put('/api/admin/server-settings', json=payload, headers=headers)
    assert response.status_code == 400
    session.commit.assert_not_called(); audit.assert_not_called(); cache.delete.assert_not_called()


@pytest.mark.parametrize('folders', [
    {'updateFolderName': 'content/updates', 'extrasFolderName': 'content/extras'},
    {'updateFolderName': 'content\\updates', 'extrasFolderName': 'content\\extras'},
])
def test_safe_nested_relative_folder_configuration_is_preserved(harness, folders):
    client, settings, _, _, _, headers = harness
    response = client.put('/api/admin/server-settings', json=folders, headers=headers)
    assert response.status_code == 200
    assert settings.update_folder_name == folders['updateFolderName']
    assert settings.extras_folder_name == folders['extrasFolderName']


def test_historical_url_credentials_are_redacted_and_not_changed_by_other_save(harness):
    client, settings, _, _, _, headers = harness
    settings.site_url = 'http://user:historical-secret@localhost:5006/base'
    response = client.get('/api/admin/server-settings')
    assert response.json['settings']['siteUrl'] == 'http://localhost:5006/base'
    assert 'historical-secret' not in response.text
    response = client.put('/api/admin/server-settings', json={'showVersion': False}, headers=headers)
    assert response.status_code == 200 and settings.site_url == 'http://user:historical-secret@localhost:5006/base'


def test_malformed_historical_url_never_leaks_credentials(harness):
    client, settings, _, _, _, headers = harness
    original = 'http://user:historical-secret@[bad'
    settings.site_url = original
    response = client.get('/api/admin/server-settings')
    assert response.status_code == 200 and 'historical-secret' not in response.text
    assert response.json['settings']['siteUrl'] == routes.DEFAULT_SETTINGS['siteUrl']
    response = client.put('/api/admin/server-settings', json={'showVersion': False}, headers=headers)
    assert response.status_code == 200 and 'historical-secret' not in response.text
    assert settings.site_url == original


def test_acl_csrf_safe_failure_and_rollback(harness, monkeypatch):
    client, _, session, audit, cache, headers = harness
    session.commit.side_effect = RuntimeError('private-secret /private/path')
    response = client.put('/api/admin/server-settings', json={'showVersion': False}, headers=headers)
    assert response.status_code == 500 and '/private/path' not in response.text and 'private-secret' not in response.text
    session.rollback.assert_called_once(); audit.assert_not_called(); cache.delete.assert_not_called()
    assert client.put('/api/admin/server-settings', json={'showVersion': False}).status_code == 400
    with client.session_transaction() as value: value['_user_id'] = 'member'
    assert client.get('/api/admin/server-settings').status_code == 302
    assert client.put('/api/admin/server-settings', json={'showVersion': False}, headers=headers).status_code == 302
    with client.session_transaction() as value: value['_user_id'] = 'admin'
    monkeypatch.setattr(routes, 'global_settings_row', Mock(side_effect=RuntimeError('private-secret')))
    response = client.get('/api/admin/server-settings')
    assert response.status_code == 500 and 'private-secret' not in response.text
