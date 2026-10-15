"""DB-free admin attract configuration contracts. No playback/provider calls."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf
from pydantic import ValidationError
from oneirodex.schemas.attract_mode import AttractModeBody
import oneirodex.routes_admin_ext.attract_mode as routes


def payload():
    return {'enabled': False, 'idle_timeout': 70, 'filters': {
        'library_uuid': None, 'genres': [1], 'themes': [2], 'date_from': 2000, 'date_to': 2025},
        'autoplay': {'enabled': True, 'skipFirst': 5, 'skipAfter': 30}}


@pytest.mark.parametrize('path,value', [
    ('enabled', 'false'), ('idle_timeout', True), ('idle_timeout', 10.5), ('idle_timeout', 9),
    ('idle_timeout', 301), ('filters', []), ('filters.library_uuid', 'invalid'),
    ('filters.genres', [True]), ('filters.genres', [-1]), ('filters.themes', ['1']),
    ('filters.genres', [1, 1]), ('filters.date_from', 99999), ('filters.date_from', 2030),
    ('autoplay.enabled', 1), ('autoplay.skipFirst', 301), ('autoplay.skipAfter', 601),
    ('autoplay.skipAfter', -1), ('autoplay.skipFirst', '5'), ('unexpected', True),
])
def test_strict_nested_validation(path, value):
    data = payload()
    keys = path.split('.')
    target = data if len(keys) == 1 else data[keys[0]]
    target[keys[-1]] = value
    with pytest.raises(ValidationError):
        AttractModeBody.model_validate(data)


class ReviewUser(UserMixin):
    def __init__(self, role):
        self.id = role
        self.role = role
        self.name = 'Review admin'


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='attract-api-test-only')
    manager = LoginManager(app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login')
    app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app)
    app.register_blueprint(routes.admin2_bp)
    row = SimpleNamespace(attract_mode_enabled=False, attract_mode_idle_timeout=60,
                          attract_mode_settings={'filters': {'genres': [1]}}, last_updated=None)
    session = Mock()
    cache = Mock()
    audit = Mock()
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(routes, 'cache', cache)
    monkeypatch.setattr(routes, 'log_system_event', audit)
    monkeypatch.setattr(routes, 'global_settings_row', lambda: row)
    monkeypatch.setattr(routes, 'global_settings_row_or_create', lambda: row)
    monkeypatch.setattr(routes, 'attract_filter_options', lambda: {
        'libraries': [], 'genres': [{'id': 1, 'name': 'Review genre'}], 'themes': [],
        'date_range': {'min_year': 2000, 'max_year': 2025}})
    client = app.test_client()
    with client.session_transaction() as value:
        value['_user_id'] = 'admin'; value['_fresh'] = True
    token = client.get('/csrf').text
    return client, row, session, cache, audit, {'X-CSRFToken': token}


def test_disabled_admin_state_retains_filters_and_returns_options_bounds(harness):
    client, row, *_ = harness
    response = client.get('/api/admin/attract-mode/settings')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.json['settings']['enabled'] is False
    assert response.json['settings']['filters']['genres'] == [1]
    assert response.json['settings']['autoplay']['skipFirst'] == 0
    assert response.json['bounds']['idle_timeout'] == {'min': 10, 'max': 300}
    assert response.json['filter_options']['genres'][0]['name'] == 'Review genre'
    assert row.attract_mode_settings == {'filters': {'genres': [1]}}


def test_admin_page_uses_shared_shell_and_defers_settings_to_api(harness, monkeypatch):
    client, _, session, *_ = harness
    rendered = []
    monkeypatch.setattr(routes, 'render_admin_spa', lambda *, title: rendered.append(title) or '<main>shell</main>')
    response = client.get('/admin/attract_mode_settings')
    assert response.status_code == 200 and response.text == '<main>shell</main>'
    assert rendered == ['Attract mode · Oneirodex Admin']
    session.execute.assert_not_called()


def test_persistence_cache_audit_and_member_disabled_compatibility(harness):
    client, row, session, cache, audit, headers = harness
    response = client.put('/api/admin/attract-mode/settings', json=payload(), headers=headers)
    assert response.status_code == 200
    assert response.json['settings'] == payload()
    assert row.attract_mode_idle_timeout == 70
    session.commit.assert_called_once(); cache.clear.assert_called_once(); audit.assert_called_once()
    assert client.get('/api/attract-mode/settings').json['enabled'] is False


def test_invalid_body_is_scrubbed_and_never_mutates(harness):
    client, _, session, _, _, headers = harness
    data = payload(); data['filters']['library_uuid'] = 'offending-private-value'
    response = client.put('/api/admin/attract-mode/settings', json=data, headers=headers)
    assert response.status_code == 400
    assert 'offending-private-value' not in response.text
    assert response.json['error_code'] == 'bad_request'
    session.commit.assert_not_called()
    assert client.put('/api/admin/attract-mode/settings', json=[], headers=headers).status_code == 400


def test_acl_csrf_and_legacy_post_compatibility(harness):
    client, _, session, _, _, headers = harness
    assert client.put('/api/admin/attract-mode/settings', json=payload()).status_code == 400
    assert client.post('/admin/attract_mode_settings', json=payload(), headers=headers).status_code == 200
    with client.session_transaction() as value:
        value['_user_id'] = 'member'
    assert client.get('/api/admin/attract-mode/settings').status_code == 302
    assert client.put('/api/admin/attract-mode/settings', json=payload(), headers=headers).status_code == 302
    session.commit.assert_called_once()


def test_commit_failure_rolls_back_with_generic_error(harness):
    client, _, session, _, _, headers = harness
    session.commit.side_effect = RuntimeError('private failure')
    response = client.put('/api/admin/attract-mode/settings', json=payload(), headers=headers)
    assert response.status_code == 500
    assert 'private failure' not in response.text
    session.rollback.assert_called_once()
