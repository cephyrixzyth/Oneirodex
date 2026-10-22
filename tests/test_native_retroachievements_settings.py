from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.retroachievements_settings import create_retroachievements_settings_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeRetroAchievements:
    def __init__(self):
        self.saved = None
        self.member_saved = None

    def settings(self):
        return {'username': 'household', 'api_key_configured': True}

    def save_settings(self, **kwargs):
        self.saved = kwargs
        return {'username': kwargs['username'], 'api_key_configured': True}

    def status(self):
        return {'configured': True, 'supported_platforms': ['SNES']}

    def configured(self):
        return True

    def member(self, _user):
        return {'ra_username': None, 'configured': True}

    def save_member(self, _user, name):
        self.member_saved = name
        return {'ra_username': name or None, 'configured': True}

    def game(self, game_uuid):
        return SimpleNamespace(uuid=game_uuid) if game_uuid == 'game-1' else None

    def can_access_game(self, _user, _game):
        return True

    def achievement_fields(self, _game):
        return {'supports_achievements': True, 'ra_game_id': 123, 'achievements': []}

    def progress(self, username, game_id):
        return {'username': username, 'game_id': game_id}

    def supported_platforms(self):
        return ['SNES']

    def match_platform(self, platform, *, rehash):
        return {'platform': platform, 'rehash': rehash, 'matched': 0}


def make_client(*, role='admin', data=None, csrf_enabled=False):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-ra-settings-secret', TESTING=True,
        WTF_CSRF_ENABLED=csrf_enabled,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=7, role=role, is_active=True, state=True, is_authenticated=True,
        preferences=SimpleNamespace(ra_username='member_handle'),
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.', login_message_category='message',
        localize_callback=None, session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_retroachievements_settings_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '7' else None,
        login_manager=manager, data_access=data or FakeRetroAchievements(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, 'native-ra-settings-secret'))
    return client


def test_admin_settings_get_never_returns_api_key():
    response = make_client().get('/api/admin/integrations/retroachievements')

    assert response.status_code == 200
    assert response.json()['api_key_configured'] is True
    assert 'api_key' not in response.json()


def test_admin_settings_put_validates_and_delegates_secret_write():
    data = FakeRetroAchievements()
    response = make_client(data=data).put('/api/admin/integrations/retroachievements', json={
        'username': 'household', 'api_key': 'secret-value', 'clear_api_key': False,
    })

    assert response.status_code == 200
    assert data.saved == {'username': 'household', 'api_key': 'secret-value', 'clear_api_key': False}
    assert 'secret-value' not in response.text


def test_member_retroachievements_settings_are_scoped_to_authenticated_member():
    data = FakeRetroAchievements()
    response = make_client(role='user', data=data).put(
        '/api/me/retroachievements', json={'ra_username': 'member_name'},
    )

    assert response.status_code == 200
    assert data.member_saved == 'member_name'
    assert response.json()['ra_username'] == 'member_name'


def test_invalid_member_handle_is_rejected():
    data = FakeRetroAchievements()
    response = make_client(role='user', data=data).put(
        '/api/me/retroachievements', json={'ra_username': 'bad name'},
    )

    assert response.status_code == 400
    assert data.member_saved is None


def test_game_achievements_keeps_acl_scoped_read_projection():
    response = make_client(role='user').get('/api/games/game-1/achievements')

    assert response.status_code == 200
    assert response.json()['me'] == {'username': 'member_handle', 'game_id': 123}
    assert response.json()['unlocks_here'] is False


def test_admin_match_action_validates_platform_before_provider_adapter():
    response = make_client().post(
        '/api/retroachievements/match', json={'platform': 'snes', 'rehash': False},
    )

    assert response.status_code == 200
    assert response.json()['platform'] == 'SNES'


def test_admin_match_empty_body_uses_safe_legacy_validation_envelope():
    response = make_client().post('/api/retroachievements/match', json={})

    assert response.status_code == 422
    assert response.json()['error'] == 'Invalid request.'
    assert response.json()['error_code'] == 'unprocessable'
    assert response.json()['detail'] == {'platform': 'Field required'}
    assert 'input_value' not in response.text
    assert 'pydantic.dev' not in response.text


def test_admin_match_non_object_body_validates_as_missing_fields():
    response = make_client().post('/api/retroachievements/match', json=[])

    assert response.status_code == 422
    assert response.json()['detail'] == {'platform': 'Field required'}


def test_admin_match_requires_csrf_before_body_validation():
    response = make_client(csrf_enabled=True).post('/api/retroachievements/match', json={})

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert 'detail' not in response.json()


def test_admin_match_ignores_json_body_with_non_json_content_type():
    response = make_client().post(
        '/api/retroachievements/match', data='{"platform":"SNES"}',
        headers={'Content-Type': 'text/plain'},
    )

    assert response.status_code == 422
    assert response.json()['detail'] == {'platform': 'Field required'}


def test_admin_match_accepts_vendor_json_content_type():
    response = make_client().post(
        '/api/retroachievements/match', data='{"platform":"snes"}',
        headers={'Content-Type': 'application/vnd.oneirodex+json'},
    )

    assert response.status_code == 200
    assert response.json()['platform'] == 'SNES'
