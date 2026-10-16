"""DB-free SMTP form contract checks; all connection transport is mocked."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf

import oneirodex.routes_smtp as routes


class ReviewUser(UserMixin):
    def __init__(self, role):
        self.id = role
        self.role = role


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='smtp-api-test-only')
    manager = LoginManager(app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login')
    app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app)
    app.register_blueprint(routes.smtp_bp)
    row = SimpleNamespace(smtp_enabled=True, smtp_server='smtp.example.com', smtp_port=587,
                          smtp_username='review@example.com', smtp_password='saved-test-secret',
                          smtp_use_tls=True, smtp_default_sender='review@example.com', smtp_last_tested=None)
    session = Mock()
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(routes, 'global_settings_row', lambda: row)
    monkeypatch.setattr(routes, 'global_settings_row_or_create', lambda: row)
    monkeypatch.setattr(routes, 'cache', Mock())
    client = app.test_client()
    with client.session_transaction() as value:
        value['_user_id'] = 'admin'
        value['_fresh'] = True
    token = client.get('/csrf').text
    return client, row, session, {'X-CSRFToken': token}


def payload():
    return dict(smtp_enabled=True, smtp_server='smtp.example.com', smtp_port='587',
                smtp_username='review@example.com', smtp_password='', smtp_use_tls=True,
                smtp_default_sender='review@example.com')


def test_document_route_uses_shared_shell_without_reading_settings(harness, monkeypatch):
    client, _, _, _ = harness
    rendered = []
    monkeypatch.setattr(routes, 'render_admin_spa', lambda *, title: rendered.append(title) or '<main>admin shell</main>')
    monkeypatch.setattr(routes, 'global_settings_row', lambda: (_ for _ in ()).throw(AssertionError('document GET must defer state to API')))
    response = client.get('/admin/smtp_settings')
    assert response.status_code == 200 and b'admin shell' in response.data
    assert rendered == ['SMTP - Oneirodex Admin']


def test_read_never_returns_password_and_is_no_store(harness):
    client, row, _, _ = harness
    response = client.get('/api/admin/smtp/settings')
    assert response.status_code == 200
    assert response.json['settings']['password_saved'] is True
    assert 'smtp_password' not in response.json['settings']
    assert row.smtp_password not in response.text
    assert response.headers['Cache-Control'] == 'no-store'


def test_save_keeps_blank_password_and_accepts_disabled_port(harness):
    client, row, session, headers = harness
    data = payload()
    data.update(smtp_enabled=False, smtp_port='2525')
    response = client.put('/api/admin/smtp/settings', json=data, headers=headers)
    assert response.status_code == 200
    assert row.smtp_password == 'saved-test-secret'
    assert row.smtp_port == 2525
    assert row.smtp_enabled is False
    session.commit.assert_called_once()


def test_replace_password_never_echoes_it(harness):
    client, row, _, headers = harness
    data = payload()
    data['smtp_password'] = 'replacement-test-secret'
    response = client.put('/api/admin/smtp/settings', json=data, headers=headers)
    assert response.status_code == 200
    assert row.smtp_password == data['smtp_password']
    assert data['smtp_password'] not in response.text


@pytest.mark.parametrize('key,value', [
    ('smtp_enabled', 'false'), ('smtp_use_tls', None), ('smtp_port', True),
    ('smtp_port', 0), ('smtp_port', 65536), ('smtp_port', '2.5'),
    ('smtp_server', ['bad']), ('smtp_server', 'bad\nhost'),
    ('smtp_server', 'https://smtp.example.com'), ('smtp_default_sender', 'bad email'),
    ('smtp_username', ''), ('smtp_password', 'x' * 256),
])
def test_invalid_fields_rejected_before_mutation(harness, key, value):
    client, row, session, headers = harness
    data = payload()
    data[key] = value
    response = client.put('/api/admin/smtp/settings', json=data, headers=headers)
    assert response.status_code == 400
    assert response.json['error_code'] == 'bad_request'
    assert row.smtp_server == 'smtp.example.com'
    session.commit.assert_not_called()


def test_non_object_and_missing_password_rejected(harness):
    client, row, _, headers = harness
    assert client.put('/api/admin/smtp/settings', json=[], headers=headers).status_code == 400
    row.smtp_password = ''
    assert client.put('/api/admin/smtp/settings', json=payload(), headers=headers).status_code == 400


def test_csrf_and_acl(harness):
    client, _, session, headers = harness
    assert client.put('/api/admin/smtp/settings', json=payload()).status_code == 400
    assert client.post('/api/admin/smtp/test').status_code == 400
    with client.session_transaction() as value:
        value['_user_id'] = 'member'
    assert client.get('/api/admin/smtp/settings').status_code == 302
    assert client.put('/api/admin/smtp/settings', json=payload(), headers=headers).status_code == 302
    assert client.post('/api/admin/smtp/test', headers=headers).status_code == 302
    session.commit.assert_not_called()


def test_connection_success_and_failure_are_scrubbed(harness, monkeypatch):
    client, row, _, headers = harness
    tester = Mock()
    tester.test_connection.return_value = (True, {'secret': row.smtp_password})
    factory = Mock(return_value=tester)
    monkeypatch.setattr(routes, 'SMTPTester', factory)
    response = client.post('/api/admin/smtp/test', headers=headers)
    assert response.status_code == 200
    assert row.smtp_password not in response.text
    tester.test_connection.assert_called_once_with(host=row.smtp_server, port=587,
        username=row.smtp_username, password=row.smtp_password, use_tls=True, timeout=10)
    tester.test_connection.return_value = (False, row.smtp_password)
    response = client.post('/api/admin/smtp/test', headers=headers)
    assert response.status_code == 502
    assert row.smtp_password not in response.text
    tester.test_connection.side_effect = RuntimeError(row.smtp_password)
    assert client.post('/api/admin/smtp/test', headers=headers).status_code == 502
    row.smtp_enabled = False
    assert client.post('/api/admin/smtp/test', headers=headers).status_code == 400


def test_failed_commit_rolls_back_without_echo(harness):
    client, row, session, headers = harness
    session.commit.side_effect = RuntimeError(row.smtp_password)
    response = client.put('/api/admin/smtp/settings', json=payload(), headers=headers)
    assert response.status_code == 500
    assert row.smtp_password not in response.text
    session.rollback.assert_called_once()
