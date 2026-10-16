from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.game_health import create_game_health_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeGameHealthData:
    def __init__(self, *, game=..., allowed=True):
        self.game = SimpleNamespace(uuid='game-123') if game is ... else game
        self.allowed = allowed
        self.calls = []
        self.payload = {
            'uuid': 'game-123',
            'score': 72,
            'grade': 'fair',
            'issues': [{'code': 'missing_cover', 'severity': 'low'}],
        }

    def find(self, game_uuid):
        self.calls.append(('find', game_uuid))
        return self.game

    def can_access(self, user, game):
        self.calls.append(('access', user.id, game.uuid))
        return self.allowed

    def score(self, game):
        self.calls.append(('score', game.uuid))
        return self.payload


def make_client(*, authenticated=True, data=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-game-health-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=67, role='user', is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    router = create_game_health_router(
        flask_app,
        find_user=lambda user_id: user if authenticated and user_id == 67 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if authenticated and value.split(':', 1)[0] == '67' else None,
        login_manager=manager,
        data_access=data or FakeGameHealthData(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie({'_user_id': '67:fp'}, 'native-game-health-secret')
        )
    return client


def test_accessible_game_returns_bare_score_payload_and_runs_lookup_acl_score_in_order():
    data = FakeGameHealthData()
    response = make_client(data=data).get('/api/health/games/game-123')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.json() == data.payload
    assert 'ok' not in response.json()
    assert data.calls == [
        ('find', 'game-123'),
        ('access', 67, 'game-123'),
        ('score', 'game-123'),
    ]


def test_missing_game_returns_existing_not_found_envelope_without_acl_or_score():
    data = FakeGameHealthData(game=None)
    response = make_client(data=data).get('/api/health/games/missing')
    assert response.status_code == 404
    assert response.json() == {
        'ok': False,
        'error': 'Game not found',
        'error_code': 'not_found',
        'message': 'Game not found',
        'success': False,
    }
    assert data.calls == [('find', 'missing')]


def test_inaccessible_game_returns_forbidden_envelope_without_scoring():
    data = FakeGameHealthData(allowed=False)
    response = make_client(data=data).get('/api/health/games/game-123')
    assert response.status_code == 403
    assert response.json() == {
        'ok': False,
        'error': 'Forbidden',
        'error_code': 'forbidden',
        'message': 'Forbidden',
        'success': False,
    }
    assert data.calls == [('find', 'game-123'), ('access', 67, 'game-123')]


def test_anonymous_request_redirects_with_login_flash_and_next_without_lookup():
    data = FakeGameHealthData()
    response = make_client(authenticated=False, data=data).get(
        '/api/health/games/game-123?from=details', follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fapi%2Fhealth%2Fgames%2Fgame-123%3Ffrom%3Ddetails'
    )
    session = load_session_cookie(
        response.cookies['session'], 'native-game-health-secret', max_age=31_536_000
    )
    assert session['_flashes'] == [('message', 'Please log in to access this page.')]
    assert data.calls == []


def test_head_preserves_status_and_content_length_but_omits_body():
    data = FakeGameHealthData()
    client = make_client(data=data)
    get_response = client.get('/api/health/games/game-123')
    head_response = client.head('/api/health/games/game-123')
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))
    assert data.calls[-3:] == [
        ('find', 'game-123'),
        ('access', 67, 'game-123'),
        ('score', 'game-123'),
    ]
