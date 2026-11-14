"""Tests for household game server registry API (SRV-1/2)."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from oneirodex.models import Game, GameServer, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.api_tokens import generate_api_token


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'admin_{uid[:8]}',
        email=f'admin_{uid[:8]}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def regular_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'user_{uid[:8]}',
        email=f'user_{uid[:8]}@test.com',
        role='user',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def child_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'child_{uid[:8]}',
        email=f'child_{uid[:8]}@test.com',
        role='child',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_game(db_session):
    library = Library(name=f'SrvLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    game = Game(
        name='Server Game',
        library_uuid=library.uuid,
        full_disk_path=f'/tmp/{uuid4().hex}',
    )
    db_session.add(game)
    db_session.commit()
    return game


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestGameServersApi:
    def test_member_can_list_servers(self, client, regular_user, db_session):
        server = GameServer(
            display_name='Valheim',
            connect_string='192.168.1.50:2456',
            invite_note='Password in family vault',
        )
        db_session.add(server)
        db_session.commit()
        _login(client, regular_user)
        response = client.get('/api/game-servers')
        assert response.status_code == 200
        body = response.get_json()
        names = [row['display_name'] for row in body['servers']]
        assert 'Valheim' in names
        row = next(item for item in body['servers'] if item['display_name'] == 'Valheim' and item['connect_string'] == '192.168.1.50:2456')
        assert row['invite_note'] == 'Password in family vault'
        assert 'health_url' not in row

    def test_child_can_read_but_not_create(self, client, child_user, db_session):
        server = GameServer(
            display_name='Minecraft',
            connect_string='mc.local:25565',
        )
        db_session.add(server)
        db_session.commit()
        _login(client, child_user)
        assert client.get('/api/game-servers').status_code == 200
        create = client.post(
            '/api/game-servers',
            json={'display_name': 'Nope', 'connect_string': 'x:1'},
        )
        assert create.status_code == 403

    def test_admin_crud(self, client, admin_user, sample_game):
        _login(client, admin_user)
        create = client.post(
            '/api/game-servers',
            json={
                'display_name': 'Terraria',
                'connect_string': 'terraria.local:7777',
                'game_uuid': sample_game.uuid,
                'health_url': 'http://127.0.0.1:9999/health',
                'compose_project': 'terraria',
                'invite_note': 'Join after dinner',
            },
        )
        assert create.status_code == 201
        body = create.get_json()
        server_uuid = body['uuid']
        assert body['health_url'] == 'http://127.0.0.1:9999/health'

        update = client.put(
            f'/api/game-servers/{server_uuid}',
            json={'display_name': 'Terraria Dedicated'},
        )
        assert update.status_code == 200
        assert update.get_json()['display_name'] == 'Terraria Dedicated'

        delete = client.delete(f'/api/game-servers/{server_uuid}')
        assert delete.status_code == 200
        remaining = client.get('/api/game-servers').get_json()['servers']
        assert all(row['uuid'] != server_uuid for row in remaining)

    def test_status_endpoint_uses_health_probe(self, client, regular_user, db_session):
        server = GameServer(
            display_name='Probe Me',
            connect_string='127.0.0.1:9',
            health_url='http://127.0.0.1/pulse',
        )
        db_session.add(server)
        db_session.commit()
        _login(client, regular_user)
        with patch(
            'oneirodex.routes_apis.game_servers.probe_server_health',
            return_value={'reachable': True, 'method': 'http', 'status_code': 200, 'error': None},
        ):
            response = client.get(f'/api/game-servers/{server.uuid}/status')
        assert response.status_code == 200
        body = response.get_json()
        assert body['reachable'] is True
        assert body['method'] == 'http'

    def test_bearer_reads_require_social_scope_but_sessions_keep_access(
        self, client, regular_user, db_session,
    ):
        server = GameServer(display_name='Scoped', connect_string='host:7')
        db_session.add(server)
        db_session.commit()
        token, raw = generate_api_token(regular_user, 'library-only', ['read:library'])
        headers = {'Authorization': f'Bearer {raw}'}
        paths = (
            '/api/game-servers',
            f'/api/game-servers/{server.uuid}',
            f'/api/game-servers/{server.uuid}/status',
            '/api/game-servers/acl-check',
        )

        for path in paths:
            denied = client.get(path, headers=headers)
            assert denied.status_code == 403
            assert denied.get_json()['error'] == 'Missing scope: read:social'
            assert denied.get_json()['detail'] == {'required_scope': 'read:social'}

        token.scopes = ['read:social']
        db_session.commit()
        with patch(
            'oneirodex.routes_apis.game_servers.probe_server_health',
            return_value={'reachable': True, 'method': 'http', 'status_code': 200, 'error': None},
        ):
            allowed = [client.get(path, headers=headers) for path in paths]
        assert [response.status_code for response in allowed] == [200, 200, 200, 200]

        _login(client, regular_user)
        session_read = client.get('/api/game-servers')
        assert session_read.status_code == 200

    def test_regular_user_cannot_update(self, client, regular_user, db_session):
        server = GameServer(display_name='Locked', connect_string='host:1')
        db_session.add(server)
        db_session.commit()
        _login(client, regular_user)
        response = client.put(
            f'/api/game-servers/{server.uuid}',
            json={'display_name': 'Hacked'},
        )
        assert response.status_code == 403
