"""Admin scan-filter API contract with the database session mocked."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf

import oneirodex.routes_admin_ext.filters as routes


class ReviewUser(UserMixin):
    def __init__(self, role):
        self.id = role
        self.role = role


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='scan-filter-api-test-only')
    manager = LoginManager(app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login')
    app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app)
    app.register_blueprint(routes.admin2_bp)
    row = SimpleNamespace(id=9, filter_pattern='dir:OpenVR*', case_sensitive='no')
    scalars = Mock(return_value=SimpleNamespace(all=lambda: [row]))
    session = Mock()
    session.execute.return_value.scalars = scalars
    session.get.return_value = row
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    client = app.test_client()
    with client.session_transaction() as value:
        value['_user_id'] = 'admin'
        value['_fresh'] = True
    headers = {'X-CSRFToken': client.get('/csrf').text}
    return client, session, row, headers


def test_list_is_ordered_envelope_and_no_store(harness):
    client, session, _, _ = harness
    response = client.get('/api/admin/scan-filters')
    assert response.status_code == 200
    assert response.json['filters'] == [{
        'id': 9, 'filter_pattern': 'dir:OpenVR*', 'kind': 'dir', 'case_sensitive': 'no'
    }]
    assert response.headers['Cache-Control'] == 'no-store'
    session.execute.assert_called_once()


@pytest.mark.parametrize(('kind', 'pattern', 'stored'), [
    ('name', 'GOG', 'GOG'),
    ('dir', 'OpenVR*', 'dir:OpenVR*'),
    ('regex', r'\[Demo\s+Build\]', r're:\[Demo\s+Build\]'),
])
def test_add_encodes_kind_and_preserves_case_mode(harness, kind, pattern, stored):
    client, session, row, headers = harness
    response = client.post('/api/admin/scan-filters', json={
        'kind': kind, 'pattern': pattern, 'case_sensitive': True
    }, headers=headers)
    assert response.status_code == 201
    added = session.add.call_args.args[0]
    assert added.filter_pattern == stored
    assert added.case_sensitive == ('yes' if kind == 'name' else 'no')
    assert response.json['filter']['kind'] == kind
    session.commit.assert_called_once()


@pytest.mark.parametrize('body', [
    {'kind': 'unknown', 'pattern': 'GOG'},
    {'kind': 'name', 'pattern': 'dir:Tools'},
    {'kind': 'dir', 'pattern': 'dir:Tools'},
    {'kind': 'regex', 'pattern': '['},
    {'kind': 'name', 'pattern': 'GOG', 'case_sensitive': 'maybe'},
    {'kind': 'name', 'pattern': 'x' * 201},
])
def test_invalid_add_rejected_without_database_write(harness, body):
    client, session, _, headers = harness
    response = client.post('/api/admin/scan-filters', json=body, headers=headers)
    assert response.status_code == 400
    assert response.json['ok'] is False
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize('pattern', [['GOG'], {'name': 'GOG'}, 7, True])
def test_non_string_pattern_rejected_without_database_write(harness, pattern):
    client, session, _, headers = harness
    response = client.post(
        '/api/admin/scan-filters',
        json={'kind': 'name', 'pattern': pattern},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json['ok'] is False
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_delete_and_missing_row(harness):
    client, session, row, headers = harness
    response = client.delete('/api/admin/scan-filters/9', headers=headers)
    assert response.status_code == 200 and response.json['ok'] is True
    session.delete.assert_called_once_with(row)
    session.commit.assert_called_once()
    session.get.return_value = None
    response = client.delete('/api/admin/scan-filters/99', headers=headers)
    assert response.status_code == 404


def test_acl_and_csrf_are_required(harness):
    client, session, _, headers = harness
    assert client.post('/api/admin/scan-filters', json={'kind': 'name', 'pattern': 'GOG'}).status_code == 400
    with client.session_transaction() as value:
        value['_user_id'] = 'member'
    assert client.get('/api/admin/scan-filters').status_code == 302
    assert client.post('/api/admin/scan-filters', json={'kind': 'name', 'pattern': 'GOG'}, headers=headers).status_code == 302
    assert client.delete('/api/admin/scan-filters/9', headers=headers).status_code == 302
    session.add.assert_not_called()
    session.delete.assert_not_called()
