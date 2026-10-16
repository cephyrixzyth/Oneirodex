from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.game_health import create_game_health_router
from oneirodex.runtime_native.library_health import create_library_health_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeLibraryHealthData:
    def __init__(self):
        self.calls = []

    def summarize(self, *, limit, library_uuid):
        self.calls.append((limit, library_uuid))
        return {'summary': 'ok', 'limit': limit, 'library_uuid': library_uuid}


class FakeGameHealthData:
    def __init__(self):
        self.game = object()
        self.accessible = True

    def find(self, game_uuid):
        return self.game if game_uuid == 'game-1' else None

    def can_access(self, _user, game):
        return self.accessible and game is self.game

    def score(self, _game):
        return {'score': 88, 'grade': 'B'}


def make_client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-health-read-secret', TESTING=True)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=31, role=role, is_active=True, state=True, is_authenticated=True,
    )
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message',
        localize_callback=None,
        session_protection='basic',
    )
    library_data = FakeLibraryHealthData()
    game_data = FakeGameHealthData()
    app = FastAPI()
    app.include_router(create_library_health_router(
        flask_app,
        find_user=lambda user_id: user if user_id == user.id else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == str(user.id) else None,
        login_manager=manager,
        data_access=library_data,
    ))
    app.include_router(create_game_health_router(
        flask_app,
        find_user=lambda user_id: user if user_id == user.id else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == str(user.id) else None,
        login_manager=manager,
        data_access=game_data,
    ))
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native health route pushed a Flask app context')
    )
    client = TestClient(app)
    client.cookies.set(
        'session', dump_session_cookie(
            {'_user_id': '31:fp'}, 'native-health-read-secret'
        )
    )
    return client, library_data, game_data


def test_library_health_read_preserves_first_value_query_and_admin_contract():
    client, library, _game = make_client()

    response = client.get('/api/health/library?limit=12&limit=99&library_uuid=lib-1')

    assert response.status_code == 200
    assert response.json() == {
        'summary': 'ok', 'limit': 12, 'library_uuid': 'lib-1',
    }
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert library.calls == [(12, 'lib-1')]


def test_game_health_read_preserves_scoring_and_error_contracts():
    client, _library, game = make_client(role='member')

    response = client.get('/api/health/games/game-1')
    assert response.status_code == 200
    assert response.json() == {'score': 88, 'grade': 'B'}

    missing = client.get('/api/health/games/missing')
    assert missing.status_code == 404
    assert missing.json()['error_code'] == 'not_found'

    game.accessible = False
    forbidden = client.get('/api/health/games/game-1')
    assert forbidden.status_code == 403
    assert forbidden.json()['error_code'] == 'forbidden'
