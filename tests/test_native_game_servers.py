from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.game_servers import create_game_servers_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class Server:
    def __init__(self, *, uuid='srv-1', display_name='Valheim', connect_string='host:2456',
                 game_uuid=None, invite_note='Join us', health_url='http://localhost/pulse',
                 compose_project='games', container_id='abc'):
        self.uuid = uuid
        self.id = 1
        self.display_name = display_name
        self.connect_string = connect_string
        self.game_uuid = game_uuid
        self.invite_note = invite_note
        self.health_url = health_url
        self.compose_project = compose_project
        self.container_id = container_id
        self.created_at = self.updated_at = None

    def to_dict(self, *, admin=False):
        result = {
            'uuid': self.uuid, 'display_name': self.display_name,
            'connect_string': self.connect_string, 'game_uuid': self.game_uuid,
            'invite_note': self.invite_note, 'created_at': None, 'updated_at': None,
        }
        if admin:
            result.update(id=self.id, health_url=self.health_url,
                          compose_project=self.compose_project, container_id=self.container_id)
        return result


class FakeData:
    def __init__(self):
        self.servers = {'srv-1': Server()}
        self.calls = []

    def list_servers(self):
        self.calls.append(('list',))
        return sorted(self.servers.values(), key=lambda row: row.display_name)

    def get_server(self, uid):
        self.calls.append(('get', uid))
        return self.servers.get(uid)

    def game_exists(self, uid):
        self.calls.append(('game_exists', uid))
        return uid == 'game-1'

    def create_server(self, **values):
        self.calls.append(('create', values))
        server = Server(uuid='srv-new', **values)
        self.servers[server.uuid] = server
        return server

    def save_server(self, server):
        self.calls.append(('save', server.uuid))

    def delete_server(self, server):
        self.calls.append(('delete', server.uuid))
        del self.servers[server.uuid]

    def probe(self, connect_string, health_url):
        self.calls.append(('probe', connect_string, health_url))
        return {'reachable': True, 'method': 'http', 'status_code': 204, 'error': None}

    def rollback(self):
        self.calls.append(('rollback',))


@pytest.fixture
def runtime():
    flask_app = Flask('game-servers-test')
    flask_app.config.update(
        SECRET_KEY='game-servers-test-secret', SESSION_PROTECTION='none',
        SECURITY_HEADERS_ENABLED=True, WTF_CSRF_ENABLED=False,
    )
    users = {
        'admin': SimpleNamespace(id=7, role='admin', state=True, is_active=True,
                                 is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'member': SimpleNamespace(id=8, role='user', state=True, is_active=True,
                                  is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'child': SimpleNamespace(id=9, role='child', state=True, is_active=True,
                                 is_authenticated=True, session_fingerprint=lambda: 'fp'),
    }
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: next(
        (user for user in users.values() if identity == f'{user.id}:fp'), None,
    ))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    fake = FakeData()
    tokens = {}

    def find_token(prefix):
        return tokens.get(prefix)

    app = FastAPI()
    app.include_router(create_game_servers_router(
        flask_app, find_user=lambda uid: next((user for user in users.values() if user.id == uid), None),
        find_token=find_token, commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager, data_access=fake,
    ))
    cookies = {
        name: dump_session_cookie({'_user_id': f'{user.id}:fp', '_fresh': True},
                                  'game-servers-test-secret')
        for name, user in users.items()
    }
    return app, flask_app, fake, users, tokens, cookies


def _request(app, path, *, cookie=None, method='GET', json=None, headers=None):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, json=json, headers=headers or {}, follow_redirects=False)

    return asyncio.run(perform())


def test_member_listing_and_detail_keep_admin_fields_private(runtime):
    app, _flask_app, _data, _users, _tokens, cookies = runtime
    listing = _request(app, '/api/game-servers', cookie=cookies['member'])
    detail = _request(app, '/api/game-servers/srv-1', cookie=cookies['member'])

    assert listing.status_code == 200
    assert listing.json()['servers'][0]['display_name'] == 'Valheim'
    assert 'invite_note' in listing.json()['servers'][0]
    assert 'health_url' not in listing.json()['servers'][0]
    assert 'health_url' not in detail.json()


def test_anonymous_request_redirects_and_acl_child_projection(runtime):
    app, _flask_app, _data, _users, _tokens, cookies = runtime
    anonymous = _request(app, '/api/game-servers')
    acl = _request(app, '/api/game-servers/acl-check', cookie=cookies['child'])

    assert anonymous.status_code == 302
    assert anonymous.headers['location'] == '/login?next=%2Fapi%2Fgame-servers'
    assert acl.json() == {
        'role': 'child', 'can_manage': False, 'can_read': True, 'read_only': True,
    }


def test_admin_create_update_delete_and_validation(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    created = _request(
        app, '/api/game-servers', cookie=cookies['admin'], method='POST',
        json={'display_name': 'New server', 'connect_string': 'new.host:7', 'game_uuid': 'game-1'},
    )
    assert created.status_code == 201
    assert created.json()['uuid'] == 'srv-new'
    assert created.json()['health_url'] is None

    updated = _request(
        app, '/api/game-servers/srv-new', cookie=cookies['admin'], method='PATCH',
        json={'display_name': ' Renamed ', 'invite_note': ' note '},
    )
    assert updated.status_code == 200
    assert updated.json()['display_name'] == 'Renamed'
    assert updated.json()['invite_note'] == 'note'
    invalid = _request(app, '/api/game-servers', cookie=cookies['admin'], method='POST', json={})
    assert invalid.status_code == 422

    deleted = _request(app, '/api/game-servers/srv-new', cookie=cookies['admin'], method='DELETE')
    assert deleted.status_code == 200
    assert deleted.json()['uuid'] == 'srv-new'
    assert ('delete', 'srv-new') in data.calls


def test_admin_only_writes_and_csrf_runs_before_anonymous_redirect(runtime):
    app, flask_app, data, _users, _tokens, cookies = runtime
    forbidden = _request(
        app, '/api/game-servers', cookie=cookies['member'], method='POST',
        json={'display_name': 'Nope', 'connect_string': 'x'},
    )
    assert forbidden.status_code == 403
    assert not any(call[0] == 'create' for call in data.calls)

    flask_app.config['WTF_CSRF_ENABLED'] = True
    csrf_first = _request(
        app, '/api/game-servers', method='POST', json={'display_name': 'Nope'},
    )
    assert csrf_first.status_code == 400
    assert csrf_first.json()['error_code'] == 'bad_request'


def test_admin_bearer_token_requires_admin_scope(runtime):
    app, _flask_app, data, users, tokens, _cookies = runtime
    token = SimpleNamespace(
        user_id=7, token_hash=hashlib.sha256(b'secret').hexdigest(),
        revoked_at=None, scopes=['read:library'], last_used_at=None,
        has_scope=lambda scope: scope in ['read:library'],
    )
    tokens['prefix'] = token
    denied = _request(
        app, '/api/game-servers', method='POST',
        json={'display_name': 'Nope', 'connect_string': 'x'},
        headers={'Authorization': 'Bearer gt_prefix_secret'},
    )
    assert denied.status_code == 403
    assert not any(call[0] == 'create' for call in data.calls)

    limited_read = _request(
        app, '/api/game-servers',
        headers={'Authorization': 'Bearer gt_prefix_secret'},
    )
    assert limited_read.status_code == 200
    assert 'health_url' not in limited_read.json()['servers'][0]
    acl = _request(app, '/api/game-servers/acl-check',
                   headers={'Authorization': 'Bearer gt_prefix_secret'})
    assert acl.json()['can_manage'] is False


def test_member_status_uses_data_adapter_probe_and_not_admin_detail(runtime):
    app, _flask_app, data, _users, _tokens, cookies = runtime
    response = _request(app, '/api/game-servers/srv-1/status', cookie=cookies['member'])

    assert response.status_code == 200
    assert response.json()['reachable'] is True
    assert response.json()['method'] == 'http'
    assert 'health_url' not in response.json()
    assert ('probe', 'host:2456', 'http://localhost/pulse') in data.calls


def test_missing_server_returns_legacy_not_found_envelope(runtime):
    app, _flask_app, _data, _users, _tokens, cookies = runtime
    response = _request(app, '/api/game-servers/missing', cookie=cookies['member'])
    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'
