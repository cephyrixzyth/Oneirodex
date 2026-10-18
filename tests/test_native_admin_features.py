from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_features import create_admin_features_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token

FEATURES = (
    'enable_arr_module', 'enable_ai_assist', 'enable_malware_scan',
    'enable_game_updates', 'enable_game_extras', 'attract_mode_enabled',
    'allow_children_in_household_lobby',
)


class FakeFeatures:
    def __init__(self):
        self.saved = []
        self.challenge = []
        self.probes = 0

    def read(self, _config):
        return {'preferences': {key: False for key in FEATURES}, 'process': [],
                'challenge': {'enabled': False, 'provider': 'token_api'},
                'scanner': {'enabled': False}}

    def save_preferences(self, body):
        self.saved.append(body)
        return body

    def save_challenge(self, body):
        self.challenge.append(body)
        return {'enabled': body['enabled'], 'provider': body['provider'], 'url': body['url'], 'max_tier': body['max_tier']}

    def test_challenge(self):
        self.probes += 1
        return {'enabled': True, 'reachable': True, 'probe_ok': True}


def make_client(*, data=None, csrf_enabled=False):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-admin-features-secret', WTF_CSRF_ENABLED=csrf_enabled)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(id=12, role='admin', is_active=True, state=True, is_authenticated=True, session_fingerprint=lambda: 'fp')
    manager = SimpleNamespace(login_view='login.login', blueprint_login_views={}, login_message='Please log in.', login_message_category='message', localize_callback=None, session_protection='basic')
    app = FastAPI()
    app.include_router(create_admin_features_router(
        flask_app, find_user=lambda value: user if value == 12 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('12:') else None,
        login_manager=manager, data_access=data or FakeFeatures(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '12:fp', '_fresh': True}, 'native-admin-features-secret'))
    return client


def test_feature_settings_read_and_typed_bulk_save():
    data = FakeFeatures()
    client = make_client(data=data)
    read = client.get('/api/admin/features/settings')
    saved = client.put('/api/admin/features/settings', json={key: True for key in FEATURES})
    invalid = client.put('/api/admin/features/settings', json={'enable_arr_module': True})

    assert read.status_code == 200
    assert len(read.json()['process']) == 0
    assert saved.status_code == 200 and all(saved.json()['preferences'].values())
    assert invalid.status_code == 400
    assert len(data.saved) == 1


def test_challenge_configuration_validation_and_probe_projection():
    data = FakeFeatures()
    client = make_client(data=data)
    body = {'enabled': True, 'url': 'https://solver.invalid', 'provider': 'token_api', 'max_tier': 2}
    saved = client.put('/api/admin/features/challenge', json=body)
    invalid = client.put('/api/admin/features/challenge', json={**body, 'provider': 'unknown'})
    tested = client.post('/api/admin/features/challenge/test')

    assert saved.status_code == 200 and saved.json()['challenge']['provider'] == 'token_api'
    assert invalid.status_code == 400
    assert tested.json()['result']['probe_ok'] is True
    assert data.probes == 1


def test_legacy_feature_form_uses_hidden_csrf_and_saves_all_toggles():
    data = FakeFeatures()
    client = make_client(data=data, csrf_enabled=True)
    session = {'_user_id': '12:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'native-admin-features-secret')
    client.cookies.set('session', dump_session_cookie(session, 'native-admin-features-secret'))
    form = {'csrf_token': csrf}
    form.update({'db_' + key: 'on' for key in FEATURES if key != 'allow_children_in_household_lobby'})

    response = client.post('/admin/features', data=form, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/features'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert data.saved == [{
        'enable_arr_module': True, 'enable_ai_assist': True,
        'enable_malware_scan': True, 'enable_game_updates': True,
        'enable_game_extras': True, 'attract_mode_enabled': True,
        'allow_children_in_household_lobby': False,
    }]
