"""Virtual-device pass, Layer 3: a fake desktop companion over the real routes.

No desktop app is needed to prove the server side of the companion protocol:
a member queues an install from the web (session), a stand-in companion with a
Bearer token receives it on heartbeat, acks or nacks it, and reports lifecycle
state. Both clients use the served ASGI routes with independent cookie jars.
"""
from uuid import uuid4

import pytest

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils import client_commands as cc
from oneirodex.utils import client_lifecycle
from oneirodex.utils.api_tokens import TOKEN_SCOPE_PRESETS, generate_api_token
from tests.fixtures.native_client import served_client

pytestmark = pytest.mark.integration


@pytest.fixture
def world(app, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(cc, '_library_root', lambda: str(tmp_path))
    monkeypatch.setattr(client_lifecycle, '_library_root', lambda: str(tmp_path))
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


@pytest.fixture
def web(client, world):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(world['user'].id)
        sess['_fresh'] = True
    return client


class FakeCompanion:
    """The smallest thing that behaves like the desktop app towards the server."""

    def __init__(self, app, token, device_id='vdevice-fake-1'):
        self.http = served_client(app)
        self.headers = {'Authorization': f'Bearer {token}'}
        self.device_id = device_id

    def heartbeat(self, **features):
        return self.http.post(
            '/api/client/heartbeat',
            json={'device_id': self.device_id, 'device_kind': 'companion', 'client_version': '0.0.0-fake', **features},
            headers=self.headers,
        )

    def ack(self, ids, *, lease_id=None):
        body = {'ids': ids}
        if lease_id is not None:
            body.update(device_id=self.device_id, lease_id=lease_id)
        return self.http.post('/api/client/commands/ack', json=body, headers=self.headers)

    def nack(self, ids):
        return self.http.post('/api/client/commands/nack', json={'ids': ids}, headers=self.headers)


def test_install_command_reaches_the_companion_once_and_is_acked(web, app, world):
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


def test_targeted_desktop_install_accepts_only_the_claiming_device_receipt(web, app, world):
    target = FakeCompanion(app, world['token'], 'den')
    other = FakeCompanion(app, world['token'], 'office')
    queued = web.post('/api/client/commands', json={
        'game_uuid': world['game'].uuid, 'action': 'install', 'target_device_id': target.device_id,
    })
    assert queued.status_code == 201
    command_id = queued.get_json()['command']['id']

    assert other.heartbeat(command_protocol=2).get_json()['commands'] == []
    [command] = target.heartbeat(command_protocol=2).get_json()['commands']
    assert command['id'] == command_id
    lease = command['lease_id']
    assert lease
    assert target.heartbeat(command_protocol=2, renew_lease=lease).get_json()['commands'] == []
    assert other.ack([command_id], lease_id=lease).get_json()['removed'] == 0
    assert target.ack([command_id]).get_json()['removed'] == 0
    assert target.ack([command_id], lease_id=lease).get_json()['removed'] == 1
    assert target.ack([command_id], lease_id=lease).get_json()['removed'] == 0
    assert target.heartbeat(command_protocol=2).get_json()['commands'] == []


def test_nacked_command_comes_back(web, app, world):
    web.post(
        '/api/client/commands', json={'game_uuid': world['game'].uuid, 'action': 'install'},
    )
    fake = FakeCompanion(app, world['token'])
    first = fake.heartbeat().get_json()['commands']
    assert len(first) == 1
    assert fake.nack([first[0]['id']]).get_json()['released'] == 1
    again = fake.heartbeat().get_json()['commands']
    assert [c['game_uuid'] for c in again] == [world['game'].uuid]


def test_new_preset_supports_heartbeat_without_widening_existing_tokens(web, app, world, db_session):
    queued = web.post('/api/client/commands', json={'game_uuid': world['game'].uuid, 'action': 'install'})
    assert queued.status_code == 201
    row, old_raw = generate_api_token(world['user'], 'old-companion', ['read:library', 'write:download'])

    old_companion = FakeCompanion(app, old_raw)
    denied = old_companion.heartbeat()
    assert denied.status_code == 403
    assert denied.get_json()['detail']['required_scope'] == 'write:presence'
    delegated = old_companion.http.post(
        '/api/tokens', json={'name': 'no-escalation', 'preset': 'companion'},
        headers=old_companion.headers,
    )
    assert delegated.status_code == 403
    assert delegated.get_json()['detail']['denied_scopes'] == ['write:presence']
    db_session.refresh(row)
    assert row.scopes == ['read:library', 'write:download']

    created = web.post('/api/tokens', json={'name': 'new-companion', 'preset': 'companion'})
    assert created.status_code == 201
    assert set(created.get_json()['token']['scopes']) == {'read:library', 'write:download', 'write:presence'}
    delivered = FakeCompanion(app, created.get_json()['secret']).heartbeat()
    assert delivered.status_code == 200
    assert [(c['game_uuid'], c['action']) for c in delivered.get_json()['commands']] == [
        (world['game'].uuid, 'install'),
    ]


def test_a_browser_session_never_receives_the_install_queue(web, world):
    web.post('/api/client/commands', json={'game_uuid': world['game'].uuid, 'action': 'install'})
    # Session cookie only: no companion token, so nothing is delivered or acked.
    assert web.post('/api/client/heartbeat', json={'device_id': 'browser', 'device_kind': 'companion'}).get_json()['commands'] == []
    assert web.post('/api/client/commands/ack', json={'ids': ['x']}).status_code in (400, 401, 403)


def test_read_only_companion_token_cannot_ack_or_nack_commands(app, world):
    _row, raw = generate_api_token(world['user'], 'read-only-companion', ['read:library'])
    read_only = FakeCompanion(app, raw)

    ack = read_only.ack(['known-command-id'])
    nack = read_only.nack(['known-command-id'])

    assert ack.status_code == 403
    assert ack.get_json()['detail']['required_scope'] == 'write:download or write:library'
    assert nack.status_code == 403
    assert nack.get_json()['detail']['required_scope'] == 'write:download or write:library'

    _row, lifecycle_raw = generate_api_token(
        world['user'], 'lifecycle-companion', ['read:library', 'write:download'],
    )
    lifecycle = FakeCompanion(app, lifecycle_raw)
    assert lifecycle.ack(['missing-command-id']).status_code == 200
    assert lifecycle.nack(['missing-command-id']).status_code == 200


def test_lifecycle_round_trip_from_the_companion(app, world):
    fake = FakeCompanion(app, world['token'])
    body = {'records': [{'game_uuid': world['game'].uuid, 'state': 'installed'}]}
    saved = fake.http.post('/api/client/lifecycle', json=body, headers=fake.headers)
    assert saved.status_code == 200, saved.get_data(as_text=True)[:200]
    listed = fake.http.get('/api/client/lifecycle', headers=fake.headers).get_json()['records']
    assert (world['game'].uuid, 'installed') in {(r['game_uuid'], r['state']) for r in listed}


def test_the_companion_cannot_queue_work_for_a_game_it_cannot_see(web):
    missing = web.post('/api/client/commands', json={'game_uuid': str(uuid4()), 'action': 'install'})
    assert missing.status_code == 404
