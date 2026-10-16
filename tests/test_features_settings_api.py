"""Features contracts without DB persistence, scanner contact, or solver transport."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf
import oneirodex.routes_admin_ext.features as routes


class ReviewUser(UserMixin):
    def __init__(self, role): self.id = role; self.role = role


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__); app.config.update(TESTING=True, SECRET_KEY='features-api-test-only')
    manager = LoginManager(app); manager.login_view = 'login.login'
    manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login'); app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app); app.register_blueprint(routes.admin2_bp)
    settings = SimpleNamespace(**{key: key != 'allow_children_in_household_lobby' for key in routes.FEATURE_DB_FIELDS}, oidc_enabled=False, arr_settings={'preserve': 'value'})
    config = {'enabled': False, 'env_enabled': False, 'db_enabled': False, 'url': 'http://127.0.0.1:8191', 'provider': 'trawl', 'max_tier': 5, 'token_api_key': 'private-token'}
    session = Mock(); save = Mock(return_value=config); probe = Mock(return_value={'enabled': True, 'reachable': False, 'probe_ok': False, 'last_error': 'private-token /private/path'})
    monkeypatch.setattr(routes, 'global_settings_row', lambda: settings)
    monkeypatch.setattr(routes, 'global_settings_row_or_create', lambda: settings)
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(routes, 'get_challenge_config', lambda: config)
    monkeypatch.setattr(routes, 'save_challenge_config', save); monkeypatch.setattr(routes, 'challenge_solver_status', probe)
    scanner = Mock(return_value={'enabled': True, 'block_on_hit': True, 'heuristics': {'enabled': True, 'block_on_match': True}, 'clamav': {'reachable': False, 'error': 'private-token /private/path'}, 'settings': {'host': '127.0.0.1', 'port': 3310, 'socket': '/private/socket'}})
    monkeypatch.setattr(routes, 'malware_module_status', scanner)
    client = app.test_client()
    with client.session_transaction() as value: value['_user_id'] = 'admin'; value['_fresh'] = True
    headers = {'X-CSRFToken': client.get('/csrf').text}
    return client, settings, session, save, probe, scanner, headers


def test_get_inventory_safe_and_no_solver_probe(harness):
    client, _, session, _, probe, scanner, _ = harness
    response = client.get('/api/admin/features/settings')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    body = response.json
    assert set(body['preferences']) == set(routes.FEATURE_DB_FIELDS)
    assert len(body['process']) == len(routes.FEATURE_ENV_TOGGLES) + 4
    assert routes.NEVER_BULK_ENABLE_ENV <= {row['key'] for row in body['process'] if row['opt_in']}
    assert body['scanner']['settings']['socket_configured'] is True
    assert 'private-token' not in response.text and '/private/' not in response.text
    probe.assert_not_called(); scanner.assert_called_once(); session.commit.assert_not_called()


def test_features_page_uses_shared_shell_without_db_read_on_document_get(harness, monkeypatch):
    client, _, _, _, _, _, _ = harness
    rendered = []
    monkeypatch.setattr(routes, 'global_settings_row', Mock(side_effect=AssertionError('page GET must use the API')))
    monkeypatch.setattr(routes, 'render_admin_spa', lambda *, title: rendered.append(title) or '<main>shell</main>')
    response = client.get('/admin/features')
    assert response.status_code == 200 and response.text == '<main>shell</main>'
    assert rendered == ['Features · Oneirodex Admin']


def test_save_only_seven_db_overrides(harness):
    client, settings, session, save, probe, scanner, headers = harness
    values = {key: False for key in routes.FEATURE_DB_FIELDS}
    response = client.put('/api/admin/features/settings', json=values, headers=headers)
    assert response.status_code == 200 and response.json['preferences'] == values
    assert settings.arr_settings == {'preserve': 'value'} and settings.oidc_enabled is False
    session.commit.assert_called_once(); save.assert_not_called(); probe.assert_not_called(); scanner.assert_not_called()


@pytest.mark.parametrize('payload', [None, [], {}, {'ENABLE_REMOTE_PLAY': True},
    {**dict.fromkeys(routes.FEATURE_DB_FIELDS, False), 'OIDC_ENABLED': True},
    {**dict.fromkeys(routes.FEATURE_DB_FIELDS, False), 'enable_ai_assist': 'true'},
    {**dict.fromkeys(routes.FEATURE_DB_FIELDS, False), 'enable_arr_module': 1}])
def test_strict_preferences_reject_unsafe_fields_and_coercion(harness, payload):
    client, _, session, *_rest, headers = harness
    assert client.put('/api/admin/features/settings', json=payload, headers=headers).status_code == 400
    session.commit.assert_not_called()


def test_solver_save_is_separate_explicit_and_never_tests(harness):
    client, _, _, save, probe, _, headers = harness
    values = {'enabled': False, 'url': 'http://127.0.0.1:8191', 'provider': 'trawl', 'max_tier': 5}
    response = client.put('/api/admin/features/challenge', json=values, headers=headers)
    assert response.status_code == 200 and 'private-token' not in response.text
    save.assert_called_once_with(values); probe.assert_not_called()
    tested = client.post('/api/admin/features/challenge/test', headers=headers)
    assert tested.status_code == 200 and tested.json['result']['probe_ok'] is False
    assert 'private-token' not in tested.text and '/private/path' not in tested.text
    probe.assert_called_once_with(probe=True)


@pytest.mark.parametrize('change', [{'enabled': 1}, {'max_tier': True}, {'max_tier': 0}, {'max_tier': 1.5}, {'provider': 'unknown'}, {'token_api_key': 'secret'}, {'url': 'http://host\nsecret'}])
def test_solver_validation(harness, change):
    client, _, _, save, probe, _, headers = harness
    values = {'enabled': False, 'url': '', 'provider': 'trawl', 'max_tier': 5, **change}
    response = client.put('/api/admin/features/challenge', json=values, headers=headers)
    assert response.status_code == 400
    save.assert_not_called(); probe.assert_not_called()


def test_failures_safe_and_drafts_not_committed(harness):
    client, _, session, save, probe, scanner, headers = harness
    session.commit.side_effect = RuntimeError('/private/path token')
    response = client.put('/api/admin/features/settings', json=dict.fromkeys(routes.FEATURE_DB_FIELDS, False), headers=headers)
    assert response.status_code == 500 and '/private' not in response.text
    session.rollback.assert_called_once()
    save.side_effect = ValueError('unsafe private-token')
    response = client.put('/api/admin/features/challenge', json={'enabled': False, 'url': '', 'provider': 'trawl', 'max_tier': 1}, headers=headers)
    assert response.status_code == 400 and 'private-token' not in response.text
    scanner.side_effect = RuntimeError('private-token')
    assert client.get('/api/admin/features/settings').status_code == 500
    probe.side_effect = RuntimeError('private-token')
    response = client.post('/api/admin/features/challenge/test', headers=headers)
    assert response.status_code == 502 and 'private-token' not in response.text


def test_acl_csrf_prevent_all_mutations(harness):
    client, _, session, save, probe, scanner, headers = harness
    assert client.put('/api/admin/features/settings', json={}).status_code == 400
    assert client.put('/api/admin/features/challenge', json={}).status_code == 400
    assert client.post('/api/admin/features/challenge/test').status_code == 400
    with client.session_transaction() as value: value['_user_id'] = 'member'
    for url in ('/api/admin/features/settings', '/api/admin/features/challenge'):
        assert client.put(url, json={}, headers=headers).status_code == 302
    assert client.get('/api/admin/features/settings').status_code == 302
    assert client.post('/api/admin/features/challenge/test', headers=headers).status_code == 302
    save.assert_not_called(); probe.assert_not_called(); scanner.assert_not_called(); session.commit.assert_not_called()
