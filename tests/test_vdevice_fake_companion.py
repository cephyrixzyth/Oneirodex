"""Virtual-device pass, Layer 3: a fake desktop companion over the real routes.

No desktop app is needed to prove the server side of the companion protocol:
a member queues an install from the web (session), a stand-in companion with a
Bearer token receives it on heartbeat, acks or nacks it, and reports lifecycle
state. Everything runs through the real Flask routes and API-token auth.
"""
from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils import client_commands as cc
from oneirodex.utils.api_tokens import generate_api_token
from oneirodex.routes_apis.tokens import TOKEN_SCOPE_PRESETS

pytestmark = pytest.mark.integration


@pytest.fixture
def world(app, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    uid = str(uuid4())
    user = User(name=f'fc_{uid[:8]}', email=f'fc_{uid[:8]}@example.com', role='user', user_id=uid, state=True)
    user.set_password('password123')
    library = Library(name=f'FakeCompanionLib_{uid[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add_all([user, library])
    db_session.commit()
    game = Game(uuid=str(uuid4()), name='Fake Companion Game', library_uuid=library.uuid)
    db_session.add(game)
    db_session.commit()
    _row, raw = generate_api_token(user, 'fake-companion', list(TOKEN_SCOPE_PRESETS['companion']['scopes']))
    return {'user': user, 'game': game, 'token': raw}


def _web(client, app, user):
    from flask_login import login_user

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)
    return client


class FakeCompanion:
    """The smallest thing that behaves like the desktop app towards the server."""

    def __init__(self, app, token, device_id='vdevice-fake-1'):
        self.http = app.test_client()
        self.headers = {'Authorization': f'Bearer {token}'}
        self.device_id = device_id

    @staticmethod
    def _fresh_request():
        # Requests made inside the test's app context share its `g`; without
        # this the browser session's cached user hides the Bearer token.
        from flask import g

        g.pop('_login_user', None)
        g.pop('api_token', None)

    def heartbeat(self):
        self._fresh_request()
        return self.http.post(
            '/api/client/heartbeat',
            json={'device_id': self.device_id, 'device_kind': 'companion', 'client_version': '0.0.0-fake'},
            headers=self.headers,
        )

    def ack(self, ids):
        self._fresh_request()
        return self.http.post('/api/client/commands/ack', json={'ids': ids}, headers=self.headers)

    def nack(self, ids):
        self._fresh_request()
        return self.http.post('/api/client/commands/nack', json={'ids': ids}, headers=self.headers)


def test_install_command_reaches_the_companion_once_and_is_acked(client, app, world):
    web = _web(client, app, world['user'])
    queued = web.post('/api/client/commands', json={'game_uuid': world['game'].uuid, 'action': 'install'})
    assert queued.status_code == 201, queued.get_data(as_text=True)[:200]

    fake = FakeCompanion(app, world['token'])
    beat = fake.heartbeat()
    assert beat.status_code == 200, beat.get_data(as_text=True)[:200]
    commands = beat.get_json()['commands']
    assert [(c['game_uuid'], c['action']) for c in commands] == [(world['game'].uuid, 'install')]

    # Delivered once: a second heartbeat does not hand the same command out again.
    assert fake.heartbeat().get_json()['commands'] == []
    ack = fake.ack([commands[0]['id']])
    assert ack.get_json()['removed'] == 1


def test_nacked_command_comes_back(client, app, world):
    _web(client, app, world['user']).post(
        '/api/client/commands', json={'game_uuid': world['game'].uuid, 'action': 'install'},
    )
    fake = FakeCompanion(app, world['token'])
    first = fake.heartbeat().get_json()['commands']
    assert len(first) == 1
    assert fake.nack([first[0]['id']]).get_json()['released'] == 1
    again = fake.heartbeat().get_json()['commands']
    assert [c['game_uuid'] for c in again] == [world['game'].uuid]


def test_a_browser_session_never_receives_the_install_queue(client, app, world):
    web = _web(client, app, world['user'])
    web.post('/api/client/commands', json={'game_uuid': world['game'].uuid, 'action': 'install'})
    # Session cookie only: no companion token, so nothing is delivered or acked.
    assert web.post('/api/client/heartbeat', json={'device_id': 'browser', 'device_kind': 'companion'}).get_json()['commands'] == []
    assert web.post('/api/client/commands/ack', json={'ids': ['x']}).status_code in (400, 401, 403)


def test_lifecycle_round_trip_from_the_companion(app, world):
    fake = FakeCompanion(app, world['token'])
    body = {'records': [{'game_uuid': world['game'].uuid, 'state': 'installed'}]}
    fake._fresh_request()
    saved = fake.http.post('/api/client/lifecycle', json=body, headers=fake.headers)
    assert saved.status_code == 200, saved.get_data(as_text=True)[:200]
    fake._fresh_request()
    listed = fake.http.get('/api/client/lifecycle', headers=fake.headers).get_json()['records']
    assert (world['game'].uuid, 'installed') in {(r['game_uuid'], r['state']) for r in listed}


def test_the_companion_cannot_queue_work_for_a_game_it_cannot_see(client, app, world, db_session):
    web = _web(client, app, world['user'])
    missing = web.post('/api/client/commands', json={'game_uuid': str(uuid4()), 'action': 'install'})
    assert missing.status_code == 404
