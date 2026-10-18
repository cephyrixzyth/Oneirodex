from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_attract_mode import create_admin_attract_mode_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeAttractData:
    def __init__(self):
        self.saved = []

    def state(self, settings):
        return {'enabled': bool(settings.get('enabled', False)), 'idle_timeout': settings.get('idle_timeout', 60)}

    def read_settings(self):
        return {'enabled': False, 'idle_timeout': 60}

    def filter_options(self):
        return {'libraries': [], 'genres': [], 'themes': [], 'date_range': {'min_year': None, 'max_year': None}}

    def save(self, user, body):
        self.saved.append((user.id, body))
        return body


def make_client(*, role='admin', data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-attract-admin-secret', WTF_CSRF_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=11, role=role, is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fp', name='Admin',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Please log in.',
        login_message_category='message', localize_callback=None, session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_admin_attract_mode_router(
        flask_app, find_user=lambda value: user if value == 11 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('11:') else None,
        login_manager=manager, data_access=data or FakeAttractData(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(
        {'_user_id': '11:fp', '_fresh': True}, 'native-attract-admin-secret',
    ))
    return client


def test_admin_attract_settings_read_head_and_bounds():
    client = make_client()
    response = client.get('/api/admin/attract-mode/settings')
    head = client.head('/api/admin/attract-mode/settings')

    assert response.status_code == 200
    assert response.json()['settings'] == {'enabled': False, 'idle_timeout': 60}
    assert response.json()['bounds']['idle_timeout'] == {'min': 10, 'max': 300}
    assert head.status_code == 200 and head.content == b''


def test_admin_attract_settings_save_validates_typed_payload():
    data = FakeAttractData()
    client = make_client(data=data)
    body = {
        'enabled': True, 'idle_timeout': 90,
        'filters': {'genres': [], 'themes': []},
        'autoplay': {'enabled': False, 'skipFirst': 0, 'skipAfter': 20},
    }
    saved = client.put('/api/admin/attract-mode/settings', json=body)
    invalid = client.put('/api/admin/attract-mode/settings', json={**body, 'idle_timeout': 999})

    assert saved.status_code == 200
    assert saved.json()['settings']['enabled'] is True
    assert invalid.status_code == 400
    assert len(data.saved) == 1


def test_admin_attract_settings_require_admin():
    response = make_client(role='user').get('/api/admin/attract-mode/settings', follow_redirects=False)

    assert response.status_code == 302


def test_legacy_attract_mode_post_alias_uses_validated_native_adapter():
    data = FakeAttractData()
    body = {
        'enabled': True, 'idle_timeout': 90,
        'filters': {'genres': [], 'themes': []},
        'autoplay': {'enabled': False, 'skipFirst': 0, 'skipAfter': 20},
    }
    response = make_client(data=data).post('/admin/attract_mode_settings', json=body)

    assert response.status_code == 200
    assert response.json()['message'] == 'Attract mode settings saved successfully'
    assert data.saved == [(11, {**body, 'filters': {'library_uuid': None, 'genres': [], 'themes': [], 'date_from': None, 'date_to': None}})]
