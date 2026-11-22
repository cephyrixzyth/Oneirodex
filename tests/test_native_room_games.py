"""Full native request-auth integration; execute only in authorized disposable CI."""
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.runtime_native.room_games import create_room_games_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token

SECRET = 'synthetic-room-game-native-test-secret'


class Data:
    def __init__(self): self.rows = {}; self.writes = []
    def read(self, user, game):
        return self.rows.get((user.id, game), {'game_id': game, 'revision': 0, 'state': None, 'updated_at': None})
    def write(self, user, game, revision, state):
        self.writes.append((user.id, game))
        value = {'game_id': game, 'revision': revision + 1, 'state': state, 'updated_at': None}
        self.rows[user.id, game] = value
        return value


def _client():
    data = Data()
    members = {i: SimpleNamespace(id=i, user_id=f'room-member-{i}', name=f'member-{i}', role='user',
        is_active=True, state=True, is_authenticated=True) for i in (41, 42)}
    settings = SimpleNamespace(config={'SECRET_KEY': SECRET, 'TESTING': True, 'CSP_ENABLED': False})
    router = create_room_games_router(settings, find_user=members.get, find_token=lambda _: None,
        commit_token_touch=lambda _: None, load_user_id=lambda value: members.get(int(value.split(':')[0])), data_access=data)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), data, members


def _session(client, member=41):
    state = {'_user_id': f'{member}:fp', '_fresh': True}
    token = generate_csrf_token(state, SECRET)
    client.cookies.set('session', dump_session_cookie(state, SECRET))
    return {'X-CSRFToken': token}


def _save():
    return {'revision': 0, 'state': json.loads((Path(__file__).parent / 'fixtures/moonfall-save-v1.json').read_text())}


def test_real_native_session_identity_is_used_instead_of_payload_owner():
    client, data, _ = _client()
    headers = _session(client)
    response = client.put('/api/room-games/moonfall-pinball/progress', json=_save(), headers=headers)
    assert response.status_code == 200
    assert data.writes == [(41, 'moonfall-pinball')]
    _session(client, 42)
    response = client.get('/api/room-games/moonfall-pinball/progress')
    assert response.status_code == 200
    assert response.json()['state'] is None
    _session(client, 41)
    assert client.get('/api/room-games/moonfall-pinball/progress').json()['state'] == _save()['state']


def test_missing_csrf_and_inactive_account_do_not_write():
    client, data, members = _client()
    headers = _session(client)
    assert client.put('/api/room-games/moonfall-pinball/progress', json=_save()).status_code == 400
    members[41].state = False
    members[41].is_active = False
    assert client.put('/api/room-games/moonfall-pinball/progress', json=_save(), headers=headers).status_code == 401
    assert data.writes == []


def test_anonymous_and_invalid_authorization_do_not_redirect_to_html():
    client, data, _ = _client()
    for headers in ({}, {'Authorization': 'Bearer synthetic-invalid-room-token'}):
        response = client.get('/api/room-games/moonfall-pinball/progress', headers=headers)
        assert response.status_code == 401
        assert response.json()['error_code'] == 'unauthorized'
        assert response.headers['cache-control'] == 'private, no-store'
    assert data.writes == []
