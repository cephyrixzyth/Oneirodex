from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_discovery_sections import (
    create_admin_discovery_sections_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeDiscoverySections:
    def __init__(self):
        self.calls = []

    def state(self):
        return {
            'sections': [{'id': 2, 'identifier': 'custom_fixture'}],
            'libraries': [], 'platforms': [], 'genres': [], 'max_games': 60,
        }

    def create(self, body, actor):
        self.calls.append(('create', body.name, actor))
        return {'section': {'name': body.name}}, None

    def update(self, section_id, body, actor):
        self.calls.append(('update', section_id, body.name, actor))
        return {'section': {'id': section_id, 'name': body.name}}, None

    def schedule(self, section_id, payload, actor):
        self.calls.append(('schedule', section_id, payload, actor))
        return {'section': {'id': section_id, **payload}}, None

    def pin(self, section_id, payload, actor):
        self.calls.append(('pin', section_id, payload, actor))
        return {'section': {'id': section_id, **payload}}, None

    def delete(self, section_id, actor):
        self.calls.append(('delete', section_id, actor))
        return {'message': 'deleted'}, None

    def reorder(self, body, actor):
        self.calls.append(('reorder', body.sections[0].id, actor))
        return {'updated_sections': ['Fixture']}, None

    def visibility(self, body, actor):
        self.calls.append(('visibility', body.section_id, body.is_visible, actor))
        return {'section_name': 'Fixture', 'new_visibility': body.is_visible}, None

    def rollback(self):
        self.calls.append(('rollback',))


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-discovery-sections-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=18, user_id='discovery-user', role=role, is_active=True,
        state=True, is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    data = FakeDiscoverySections()
    router = create_admin_discovery_sections_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 18 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '18' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session = {'_user_id': '18:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    return client, data, csrf


def test_discovery_sections_read_and_head_preserve_admin_projection():
    client, data, _csrf = _client()

    response = client.get('/admin/api/discovery_sections')
    head = client.head('/admin/api/discovery_sections')

    assert response.status_code == 200
    assert response.json()['sections'][0]['identifier'] == 'custom_fixture'
    assert response.headers['cache-control'] == 'no-store'
    assert head.status_code == 200 and head.content == b''
    assert data.calls == []


def test_discovery_section_mutations_keep_csrf_and_admin_gates():
    client, data, csrf = _client()
    denied = client.post('/admin/api/discovery_sections', json={'name': 'New shelf'})
    assert denied.status_code == 400
    assert data.calls == []

    create = client.post(
        '/admin/api/discovery_sections', json={'name': 'New shelf', 'mode': 'manual'},
        headers={'X-CSRFToken': csrf},
    )
    update = client.put(
        '/admin/api/discovery_sections/2', json={'name': 'Edited shelf', 'mode': 'manual'},
        headers={'X-CSRFToken': csrf},
    )
    schedule = client.put(
        '/admin/api/discovery_sections/2/schedule',
        json={'layout': 'hero', 'starts_at': None}, headers={'X-CSRFToken': csrf},
    )
    pin = client.put(
        '/admin/api/discovery_sections/2/pin', json={'pin_rank': 1},
        headers={'X-CSRFToken': csrf},
    )
    reordered = client.post(
        '/admin/api/discovery_sections/order', json={'sections': [{'id': 2, 'order': 1}]},
        headers={'X-CSRFToken': csrf},
    )
    visibility = client.post(
        '/admin/api/discovery_sections/visibility',
        json={'section_id': 2, 'is_visible': False}, headers={'X-CSRFToken': csrf},
    )
    deleted = client.delete('/admin/api/discovery_sections/2', headers={'X-CSRFToken': csrf})

    assert create.status_code == 201 and create.json()['section']['name'] == 'New shelf'
    assert update.status_code == 200 and update.json()['section']['name'] == 'Edited shelf'
    assert schedule.status_code == 200 and schedule.json()['section']['layout'] == 'hero'
    assert pin.status_code == 200 and pin.json()['section']['pin_rank'] == 1
    assert reordered.status_code == 200
    assert visibility.status_code == 200 and visibility.json()['new_visibility'] is False
    assert deleted.status_code == 200
    assert [call[0] for call in data.calls] == [
        'create', 'update', 'schedule', 'pin', 'reorder', 'visibility', 'delete',
    ]
    assert all(call[-1] == 18 for call in data.calls)


def test_discovery_section_validation_and_member_gate_do_not_mutate():
    client, data, csrf = _client()
    invalid = client.post(
        '/admin/api/discovery_sections', json={'mode': 'manual'},
        headers={'X-CSRFToken': csrf},
    )
    assert invalid.status_code == 422
    assert invalid.json()['error_code'] == 'unprocessable'
    assert invalid.json()['detail'] == {'name': 'Field required'}

    blank_name = client.post(
        '/admin/api/discovery_sections', json={'name': '   ', 'mode': 'manual'},
        headers={'X-CSRFToken': csrf},
    )
    assert blank_name.status_code == 422
    assert blank_name.json()['error_code'] == 'unprocessable'
    assert blank_name.json()['detail'] == {
        'name': 'String should have at least 1 character',
    }

    malformed = client.post(
        '/admin/api/discovery_sections', data='{not-json',
        headers={'X-CSRFToken': csrf, 'content-type': 'application/json'},
    )
    non_object = client.post(
        '/admin/api/discovery_sections', json=[], headers={'X-CSRFToken': csrf},
    )
    root_error = {
        '__root__': 'Input should be a valid dictionary or instance of DiscoveryShelfBody',
    }
    empty_object_errors = [
        client.post(
            '/admin/api/discovery_sections',
            headers={'X-CSRFToken': csrf, 'content-type': 'application/json'},
        ),
        client.post('/admin/api/discovery_sections', json=None, headers={'X-CSRFToken': csrf}),
        client.post('/admin/api/discovery_sections', json='scalar', headers={'X-CSRFToken': csrf}),
        client.post('/admin/api/discovery_sections', json=7, headers={'X-CSRFToken': csrf}),
        client.post('/admin/api/discovery_sections', json=True, headers={'X-CSRFToken': csrf}),
    ]
    assert malformed.status_code == 422
    assert malformed.json()['detail'] == {'name': 'Field required'}
    assert non_object.status_code == 422
    assert non_object.json()['detail'] == root_error
    assert all(response.status_code == 422 for response in empty_object_errors)
    assert all(response.json()['detail'] == {'name': 'Field required'} for response in empty_object_errors[:2])
    assert all(response.json()['detail'] == root_error for response in empty_object_errors[2:])
    assert data.calls == []

    member, member_data, _member_csrf = _client(role='user')
    response = member.get('/admin/api/discovery_sections', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
    assert member_data.calls == []
