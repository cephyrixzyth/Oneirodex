"""Admin shelves state/actions against mock persistence; no providers or scans."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf
import oneirodex.routes_admin_ext.system as routes


class ReviewUser(UserMixin):
    def __init__(self, role): self.id = role; self.role = role


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__); app.config.update(TESTING=True, SECRET_KEY='shelves-api-test-only')
    manager = LoginManager(app); manager.login_view = 'login.login'; manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login'); app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app); app.register_blueprint(routes.admin2_bp)
    seed = routes.DiscoverySection(id=1, name='Libraries', identifier='libraries', section_type='seed', display_order=0, is_visible=True, layout='shelf')
    custom = routes.DiscoverySection(id=2, name='Review shelf', identifier='custom_review', section_type='custom', display_order=1, is_visible=True, layout='shelf', config={'mode': 'manual', 'game_uuids': ['game-review'], 'private_key': 'secret'})
    sections = {1: seed, 2: custom}
    session = Mock(); session.get.side_effect = lambda model, identity: sections.get(identity)
    session.execute.return_value.scalar.return_value = 1
    session.add.side_effect = lambda row: setattr(row, 'id', 3)
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session)); audit = Mock(); monkeypatch.setattr(routes, 'log_system_event', audit)
    validate = Mock(return_value=({'mode': 'manual', 'game_uuids': ['game-review']}, None))
    monkeypatch.setattr(routes, 'validate_shelf_config', validate); monkeypatch.setattr(routes, 'count_custom_shelf_games', lambda config: 1); monkeypatch.setattr(routes, 'describe_shelf_config', lambda config: 'Manual game list')
    data = {'sections': [seed, custom], 'section_counts': {'libraries': 4, 'custom_review': 1}, 'shelf_descriptions': {2: 'Manual game list'}, 'libraries': [SimpleNamespace(uuid='library-review', name='Review library')], 'genres': [SimpleNamespace(name='Review genre')], 'platforms': [routes.LibraryPlatform.NES]}
    monkeypatch.setattr(routes, 'discovery_sections_data', Mock(return_value=data))
    client = app.test_client()
    with client.session_transaction() as value: value['_user_id'] = 'admin'; value['_fresh'] = True
    return client, seed, custom, session, validate, audit, {'X-CSRFToken': client.get('/csrf').text}


def test_state_has_counts_configs_filters_and_safe_utc(harness):
    client, seed, custom, session, *_ = harness
    seed.starts_at = datetime(2026, 1, 1)
    response = client.get('/admin/api/discovery_sections')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert response.json['sections'][0]['count'] == 4
    assert response.json['sections'][0]['starts_at'] == '2026-01-01T00:00:00Z'
    assert response.json['sections'][1]['description'] == 'Manual game list'
    assert response.json['sections'][1]['config'] == {'mode': 'manual', 'game_uuids': ['game-review']}
    assert 'secret' not in response.text and response.json['max_games'] == 60
    assert response.json['libraries'][0]['uuid'] == 'library-review'
    session.commit.assert_not_called()


def test_admin_page_uses_shared_shell_and_api_for_page_state(harness, monkeypatch):
    client, _, _, _, _, _, _ = harness
    rendered = []
    monkeypatch.setattr(routes, 'render_admin_spa', lambda *, title: rendered.append(title) or '<main>shell</main>')
    response = client.get('/admin/discovery_sections')
    assert response.status_code == 200
    assert response.text == '<main>shell</main>'
    assert rendered == ['Discovery sections · Oneirodex Admin']
    routes.discovery_sections_data.assert_not_called()


def test_custom_create_edit_delete_and_builtin_guards(harness):
    client, _, custom, session, validate, _, headers = harness
    payload = {'name': 'Review changed', 'mode': 'manual', 'game_uuids': ['game-review']}
    assert client.post('/admin/api/discovery_sections', json=payload, headers=headers).status_code == 201
    assert client.put('/admin/api/discovery_sections/2', json=payload, headers=headers).status_code == 200
    assert custom.name == 'Review changed' and custom.config == {'mode': 'manual', 'game_uuids': ['game-review']}
    validate.assert_called_with('manual', game_uuids=['game-review'], filter_type=None, filter_value=None)
    assert client.put('/admin/api/discovery_sections/1', json=payload, headers=headers).status_code == 400
    assert client.delete('/admin/api/discovery_sections/1', headers=headers).status_code == 400
    assert client.delete('/admin/api/discovery_sections/2', headers=headers).status_code == 200
    session.delete.assert_called_once_with(custom)


@pytest.mark.parametrize('filter_type,filter_value', [('library', 'library-review'), ('platform', 'NES'), ('genre', 'Review genre')])
def test_filter_payloads_delegate_validation(harness, filter_type, filter_value):
    client, _, _, _, validate, _, headers = harness
    payload = {'name': 'Review filter', 'mode': 'filter', 'filter_type': filter_type, 'filter_value': filter_value}
    assert client.post('/admin/api/discovery_sections', json=payload, headers=headers).status_code == 201
    validate.assert_called_once_with('filter', game_uuids=None, filter_type=filter_type, filter_value=filter_value)


def test_schedule_normalizes_mixed_timezone_partial_edit_and_clear(harness):
    client, _, custom, session, *_rest, headers = harness
    custom.starts_at = datetime(2026, 1, 1, 12)
    response = client.put('/admin/api/discovery_sections/2/schedule', json={'ends_at': '2026-01-01T15:00:00+02:00', 'layout': 'hero'}, headers=headers)
    assert response.status_code == 200
    assert custom.starts_at == datetime(2026, 1, 1, 12) and custom.ends_at == datetime(2026, 1, 1, 13)
    assert custom.ends_at.tzinfo is None and custom.layout == 'hero'
    assert client.put('/admin/api/discovery_sections/2/schedule', json={'starts_at': None, 'ends_at': None}, headers=headers).status_code == 200
    assert custom.starts_at is None and custom.ends_at is None


@pytest.mark.parametrize('payload', [{'layout': 'hero', 'ends_at': 'bad'}, {'layout': 'hero', 'starts_at': '2026-01-01T10:00:00Z', 'ends_at': '2026-01-01T09:00:00Z'}, {'layout': True}, {'starts_at': True}, [], {}, {'private': 'secret'}])
def test_invalid_schedule_leaves_fields_unmutated(harness, payload):
    client, _, custom, session, *_rest, headers = harness
    response = client.put('/admin/api/discovery_sections/2/schedule', json=payload, headers=headers)
    assert response.status_code == 400
    assert custom.layout == 'shelf' and custom.starts_at is None and custom.ends_at is None
    session.commit.assert_not_called()


def test_order_validates_whole_batch_before_assigning(harness):
    client, seed, custom, session, *_rest, headers = harness
    for second in ({'id': 999, 'order': 0}, {'id': 2, 'order': -1}, {'id': 1, 'order': 0}):
        response = client.post('/admin/api/discovery_sections/order', json={'sections': [{'id': 1, 'order': 5}, second]}, headers=headers)
        assert response.status_code in (400, 404)
        assert seed.display_order == 0 and custom.display_order == 1
    session.commit.assert_not_called()
    assert client.post('/admin/api/discovery_sections/order', json={'sections': [{'id': 1, 'order': 1}, {'id': 2, 'order': 0}]}, headers=headers).status_code == 200
    assert seed.display_order == 1 and custom.display_order == 0


@pytest.mark.parametrize('payload', [{'pin_rank': True}, {'pin_rank': 1.5}, {'pin_rank': '1'}, {'pin_rank': 2 ** 31}, {}, {'pin_rank': 1, 'other': True}])
def test_pin_is_strict_and_does_not_mutate_on_failure(harness, payload):
    client, _, custom, session, *_rest, headers = harness
    assert client.put('/admin/api/discovery_sections/2/pin', json=payload, headers=headers).status_code == 400
    assert custom.pin_rank is None
    session.commit.assert_not_called()


def test_pin_visibility_acl_csrf_and_safe_failure(harness, monkeypatch):
    client, _, custom, session, *_rest, headers = harness
    assert client.put('/admin/api/discovery_sections/2/pin', json={'pin_rank': -1}, headers=headers).status_code == 200
    assert custom.pin_rank == -1
    assert client.put('/admin/api/discovery_sections/2/pin', json={'pin_rank': None}, headers=headers).status_code == 200
    assert custom.pin_rank is None
    assert client.post('/admin/api/discovery_sections/visibility', json={'section_id': 2, 'is_visible': False}, headers=headers).status_code == 200
    assert custom.is_visible is False
    assert client.post('/admin/api/discovery_sections/visibility', json={'section_id': 2, 'is_visible': 'false'}, headers=headers).status_code == 422
    assert client.put('/admin/api/discovery_sections/2/pin', json={'pin_rank': 0}).status_code == 400
    with client.session_transaction() as value: value['_user_id'] = 'member'
    assert client.get('/admin/api/discovery_sections').status_code == 302
    assert client.post('/admin/api/discovery_sections', json={'name': 'x'}, headers=headers).status_code == 302
    with client.session_transaction() as value: value['_user_id'] = 'admin'
    monkeypatch.setattr(routes, 'discovery_sections_data', Mock(side_effect=RuntimeError('secret /private/path')))
    response = client.get('/admin/api/discovery_sections')
    assert response.status_code == 500 and '/private/path' not in response.text
