"""DB-free credential boundary checks; provider transport is always mocked."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf
import oneirodex.routes_admin_ext.igdb as routes


class ReviewUser(UserMixin):
    def __init__(self, role):
        self.id = role; self.role = role


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='igdb-api-test-only')
    manager = LoginManager(app); manager.login_view = 'login.login'
    manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login')
    app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app); app.register_blueprint(routes.admin2_bp)
    row = SimpleNamespace(igdb_client_id='review-client', igdb_client_secret='saved-test-secret', igdb_last_tested=None)
    session = Mock(); transport = Mock(return_value=[])
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(routes, 'cache', Mock())
    monkeypatch.setattr(routes, 'make_igdb_api_request', transport)
    monkeypatch.setattr(routes, 'global_settings_row', lambda: row)
    monkeypatch.setattr(routes, 'global_settings_row_or_create', lambda: row)
    client = app.test_client()
    with client.session_transaction() as value:
        value['_user_id'] = 'admin'; value['_fresh'] = True
    token = client.get('/csrf').text
    return client, row, session, transport, {'X-CSRFToken': token}


def test_read_is_no_store_and_secret_never_echoed(harness):
    client, row, _, transport, _ = harness
    response = client.get('/api/admin/igdb/settings')
    assert response.status_code == 200
    assert response.json['settings'] == {'igdb_client_id': row.igdb_client_id, 'secret_present': True, 'last_tested': None}
    assert row.igdb_client_secret not in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    transport.assert_not_called()


def test_blank_keeps_secret_and_replacement_not_echoed(harness):
    client, row, session, transport, headers = harness
    response = client.put('/api/admin/igdb/settings', json={'igdb_client_id': 'changed-client', 'igdb_client_secret': ''}, headers=headers)
    assert response.status_code == 200
    assert row.igdb_client_secret == 'saved-test-secret'
    assert row.igdb_client_id == 'changed-client'
    response = client.put('/api/admin/igdb/settings', json={'igdb_client_id': '', 'igdb_client_secret': 'replacement-test-secret'}, headers=headers)
    assert response.status_code == 200
    assert row.igdb_client_secret == 'replacement-test-secret'
    assert row.igdb_client_secret not in response.text
    assert row.igdb_client_id == ''
    assert session.commit.call_count == 2
    transport.assert_not_called()


@pytest.mark.parametrize('data', [[], None, {'unknown': True}, {'igdb_client_id': True},
    {'igdb_client_secret': 10}, {'igdb_client_id': 'x' * 256}, {'igdb_client_secret': 'x' * 256},
    {'igdb_client_secret': 'bad\nsecret'}])
def test_bad_shapes_rejected_without_mutation(harness, data):
    client, row, session, _, headers = harness
    assert client.put('/api/admin/igdb/settings', json=data, headers=headers).status_code == 400
    assert row.igdb_client_id == 'review-client'
    session.commit.assert_not_called()


def test_acl_csrf_and_legacy_save_compatibility(harness):
    client, _, session, transport, headers = harness
    assert client.put('/api/admin/igdb/settings', json={}).status_code == 400
    assert client.post('/api/admin/igdb/test').status_code == 400
    assert client.post('/admin/igdb_settings', json={'igdb_client_id': 'legacy-client'}, headers=headers).status_code == 200
    with client.session_transaction() as value:
        value['_user_id'] = 'member'
    assert client.get('/api/admin/igdb/settings').status_code == 302
    assert client.put('/api/admin/igdb/settings', json={}, headers=headers).status_code == 302
    assert client.post('/api/admin/igdb/test', headers=headers).status_code == 302
    session.commit.assert_called_once(); transport.assert_not_called()


def test_test_connection_uses_saved_credentials_updates_timestamp_and_scrubs_errors(harness):
    client, row, session, transport, headers = harness
    response = client.post('/api/admin/igdb/test', headers=headers)
    assert response.status_code == 200
    assert row.igdb_last_tested is not None
    assert response.json['settings']['last_tested'] == row.igdb_last_tested.isoformat()
    assert row.igdb_client_secret not in response.text
    transport.assert_called_once_with('https://api.igdb.com/v4/games', 'fields name; limit 1;')
    transport.return_value = {'error': row.igdb_client_secret}
    response = client.post('/api/admin/igdb/test', headers=headers)
    assert response.status_code == 502
    assert row.igdb_client_secret not in response.text
    transport.side_effect = RuntimeError(row.igdb_client_secret)
    response = client.post('/api/admin/igdb/test', headers=headers)
    assert response.status_code == 502
    assert row.igdb_client_secret not in response.text
    session.rollback.assert_called_once()
    row.igdb_client_secret = ''
    assert client.post('/api/admin/igdb/test', headers=headers).status_code == 400


def test_save_failure_rolls_back_without_echo(harness):
    client, row, session, _, headers = harness
    session.commit.side_effect = RuntimeError(row.igdb_client_secret)
    response = client.put('/api/admin/igdb/settings', json={'igdb_client_id': 'review-client'}, headers=headers)
    assert response.status_code == 500
    assert row.igdb_client_secret not in response.text
    session.rollback.assert_called_once()
