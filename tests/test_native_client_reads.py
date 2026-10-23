from __future__ import annotations

import hashlib
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.client_reads import create_client_reads_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


SECRET = 'native-client-reads-secret'
RAW_TOKEN = 'gt_abcd1234_ClientSecret_987654321'


class FakeToken:
    token_prefix = 'abcd1234'
    user_id = 27
    revoked_at = None
    last_used_at = None
    expires_at = None

    def __init__(self, scopes):
        self.scopes = list(scopes)
        self.token_hash = hashlib.sha256(b'ClientSecret_987654321').hexdigest()

    def is_expired(self, now=None):
        return False

    def has_scope(self, scope):
        return 'admin' in self.scopes or scope in self.scopes


class FakeData:
    def __init__(self):
        self.capability_calls = []
        self.lifecycle_calls = []
        self.heartbeat_calls = []
        self.command_calls = []

    def capabilities(self, device_kind, token, _user):
        self.capability_calls.append((device_kind, token))
        return {'device_kind': device_kind or 'companion', 'allows': ['browse'], 'denies': []}

    def lifecycle(self, user_id):
        self.lifecycle_calls.append(('read', user_id))
        return {'records': [{'game_uuid': 'game-1', 'state': 'installed'}]}

    def save_lifecycle(self, user_id, records, *, replace=False):
        self.lifecycle_calls.append(('write', user_id, records, replace))
        return {'records': [{'game_uuid': row['game_uuid'], 'state': row['state']} for row in records]}

    def heartbeat(
        self, user_id, device_id, device_kind, device_name, client_version,
        user_agent, token, _user,
    ):
        self.heartbeat_calls.append((
            user_id, device_id, device_kind, device_name, client_version,
            user_agent, token,
        ))
        return {'device_id': device_id, 'commands': []}

    def find_game(self, game_uuid):
        return SimpleNamespace(
            uuid=game_uuid, full_disk_path=str(Path(__file__).resolve().parent),
        ) if game_uuid == 'game-1' else None

    def can_access_game(self, _user, _game):
        return True

    def find_version(self, _game, kind, version_uuid):
        return SimpleNamespace(extra_kind='translation_patch') if (
            kind == 'extra' and version_uuid == 'patch-1'
        ) else None

    def enqueue(self, user_id, game_uuid, action, **kwargs):
        self.command_calls.append((user_id, game_uuid, action, kwargs))
        return {'id': 'command-1', 'action': action}

    def claim(self, user_id, *, limit=None):
        self.command_calls.append(('claim', user_id, limit))
        return [{'id': 'command-1'}]

    def acknowledge(self, user_id, ids):
        self.command_calls.append(('ack', user_id, ids))
        return len(ids)

    def negative_acknowledge(self, user_id, ids):
        self.command_calls.append(('nack', user_id, ids))
        return len(ids)


def make_client(*, scopes=('read:library', 'write:download')):
    user = SimpleNamespace(id=27, role='user', state=True, is_active=True)
    token = FakeToken(scopes)
    data = FakeData()
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET,
        TESTING=True,
        SECRET_KEY_FALLBACKS=[],
        SESSION_COOKIE_NAME='session',
        REMEMBER_COOKIE_NAME='remember_token',
        PERMANENT_SESSION_LIFETIME=timedelta(days=31),
        SESSION_PROTECTION=None,
        SESSION_REFRESH_EACH_REQUEST=True,
        WTF_CSRF_ENABLED=True,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    login_manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message=None,
        login_message_category='message', session_protection=None,
    )
    router = create_client_reads_router(
        flask_app,
        find_user=lambda user_id: user if user_id == user.id else None,
        find_token=lambda prefix: token if prefix == token.token_prefix else None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '27' else None,
        login_manager=login_manager,
        data_access=data,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, follow_redirects=False)
    client.data = data
    client.user = user
    client.token = token
    return client


def browser_cookie(user_id=27):
    return dump_session_cookie({'_user_id': str(user_id), '_fresh': True}, SECRET)


def browser_headers():
    session = {'_user_id': '27', '_fresh': True}
    csrf = generate_csrf_token(session, SECRET)
    return {
        'Cookie': 'session=' + dump_session_cookie(session, SECRET),
        'X-CSRFToken': csrf,
    }


def test_capabilities_requires_login_and_uses_first_device_kind_value():
    client = make_client()
    response = client.get('/api/client/capabilities?device_kind=thin&device_kind=browser')
    assert response.status_code == 302

    client.cookies.set('session', browser_cookie())
    response = client.get('/api/client/capabilities?device_kind=thin&device_kind=browser')
    assert response.status_code == 200
    assert response.json() == {'device_kind': 'thin', 'allows': ['browse'], 'denies': []}
    assert client.data.capability_calls == [('thin', None)]


def test_lifecycle_read_preserves_read_library_scope():
    client = make_client(scopes=('write:download',))
    response = client.get(
        '/api/client/lifecycle', headers={'Authorization': f'Bearer {RAW_TOKEN}'}
    )
    assert response.status_code == 403
    assert response.json()['error'] == 'Missing scope: read:library'

    client = make_client(scopes=('read:library',))
    response = client.get(
        '/api/client/lifecycle', headers={'Authorization': f'Bearer {RAW_TOKEN}'}
    )
    assert response.status_code == 200
    assert response.json() == {'records': [{'game_uuid': 'game-1', 'state': 'installed'}]}
    assert client.data.lifecycle_calls == [('read', 27)]


def test_lifecycle_write_is_bearer_only_and_preserves_scope_gate():
    session_client = make_client()
    session_client.cookies.set('session', browser_cookie())
    session = session_client.post('/api/client/lifecycle', json={'records': []})
    assert session.status_code == 403
    assert session.json()['error'] == 'Companion API token required'
    assert session_client.data.lifecycle_calls == []

    no_write = make_client(scopes=('read:library',))
    denied = no_write.post(
        '/api/client/lifecycle',
        headers={'Authorization': f'Bearer {RAW_TOKEN}'},
        json={'records': []},
    )
    assert denied.status_code == 403
    assert 'Missing scope' in denied.json()['error']

    writer = make_client(scopes=('write:download',))
    saved = writer.post(
        '/api/client/lifecycle',
        headers={'Authorization': f'Bearer {RAW_TOKEN}'},
        json={'records': [{'game_uuid': 'game-2', 'state': 'installed'}], 'replace': True},
    )
    assert saved.status_code == 200
    assert saved.json()['count'] == 1
    assert writer.data.lifecycle_calls == [
        ('write', 27, [{'game_uuid': 'game-2', 'state': 'installed'}], True)
    ]


def test_lifecycle_validation_runs_before_bearer_only_denial():
    client = make_client()
    client.cookies.set('session', browser_cookie())
    response = client.post('/api/client/lifecycle', json={})
    assert response.status_code == 422
    assert response.json()['error'] == 'Invalid request.'


def test_lifecycle_scalar_body_preserves_root_validation_error():
    client = make_client()
    response = client.post(
        '/api/client/lifecycle',
        headers={'Authorization': f'Bearer {RAW_TOKEN}'},
        json=['bad'],
    )
    assert response.status_code == 422
    assert response.json()['detail'] == {
        '__root__': 'Input should be a valid dictionary or instance of ClientLifecycleBody'
    }
    assert client.data.lifecycle_calls == []


def test_head_lifecycle_has_empty_body_and_security_headers():
    client = make_client(scopes=('read:library',))
    response = client.head(
        '/api/client/lifecycle', headers={'Authorization': f'Bearer {RAW_TOKEN}'}
    )
    assert response.status_code == 200
    assert response.content == b''
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_heartbeat_requires_csrf_for_session_and_accepts_valid_browser_write():
    client = make_client()
    client.cookies.set('session', browser_cookie())
    rejected = client.post('/api/client/heartbeat', json={'device_id': 'desktop'})
    assert rejected.status_code == 400
    assert rejected.json()['error'] == 'The CSRF token is missing.'
    assert client.data.heartbeat_calls == []

    session = {'_user_id': '27', '_fresh': True}
    csrf = generate_csrf_token(session, SECRET)
    client.cookies.set('session', dump_session_cookie(session, SECRET))
    accepted = client.post(
        '/api/client/heartbeat',
        json={
            'device_id': ' desktop ',
            'device_kind': 'thin',
            'device_name': 'Laptop',
            'client_version': '1.2.3',
        },
        headers={'X-CSRFToken': csrf},
    )
    assert accepted.status_code == 200
    assert accepted.json() == {'device_id': 'desktop', 'commands': []}
    assert client.data.heartbeat_calls[0][:6] == (
        27, 'desktop', 'thin', 'Laptop', '1.2.3', 'testclient',
    )


def test_heartbeat_requires_presence_scope_and_bearer_bypasses_csrf():
    reader = make_client(scopes=('read:library',))
    denied = reader.post(
        '/api/client/heartbeat', headers={'Authorization': f'Bearer {RAW_TOKEN}'},
        json={'device_id': 'desktop'},
    )
    assert denied.status_code == 403
    assert denied.json()['error'] == 'Missing scope: write:presence'
    assert reader.data.heartbeat_calls == []

    writer = make_client(scopes=('write:presence',))
    response = writer.post(
        '/api/client/heartbeat', headers={'Authorization': f'Bearer {RAW_TOKEN}'},
        json={'device_id': 'desktop'},
    )
    assert response.status_code == 200
    assert response.json()['device_id'] == 'desktop'
    assert writer.data.heartbeat_calls[0][0:3] == (27, 'desktop', None)
    assert writer.data.heartbeat_calls[0][-1] is writer.token


def bearer_headers(client, *, scopes=None):
    session = {}
    csrf = generate_csrf_token(session, SECRET)
    client.cookies.set('session', dump_session_cookie(session, SECRET))
    return {'Authorization': f'Bearer {RAW_TOKEN}', 'X-CSRFToken': csrf}


def test_command_poll_requires_bearer_read_scope_and_caps_limit():
    browser = make_client()
    browser.cookies.set('session', browser_cookie())
    denied = browser.get('/api/client/commands')
    assert denied.status_code == 403
    assert denied.json()['error'] == 'Companion API token required'

    client = make_client(scopes=('read:library', 'write:download'))
    response = client.get(
        '/api/client/commands?device_kind=companion&limit=999',
        headers={'Authorization': f'Bearer {RAW_TOKEN}'},
    )
    assert response.status_code == 200
    assert response.json() == {'commands': [{'id': 'command-1'}]}
    assert client.data.command_calls == [('claim', 27, 25)]


def test_downgraded_child_token_cannot_poll_companion_commands():
    client = make_client(scopes=('read:library', 'write:download'))
    client.user.role = 'child'
    response = client.get(
        '/api/client/commands?device_kind=companion',
        headers={'Authorization': f'Bearer {RAW_TOKEN}'},
    )
    assert response.status_code == 200
    assert response.json() == {'commands': []}
    assert client.data.command_calls == []


def test_command_queue_preserves_csrf_scope_acl_and_path_action_contracts():
    client = make_client(scopes=('read:library',))
    headers = bearer_headers(client)
    denied = client.post(
        '/api/client/commands', headers=headers,
        json={'game_uuid': 'game-1', 'action': 'download'},
    )
    assert denied.status_code == 403
    assert denied.json()['detail'] == {'required_scope': 'write:download'}
    assert client.data.command_calls == []

    browser = make_client()
    denied_unmatched = browser.post(
        '/api/client/commands', headers=browser_headers(),
        json={'action': 'open_path', 'path': str(Path(__file__).resolve())},
    )
    assert denied_unmatched.status_code == 403
    assert browser.data.command_calls == []

    response = browser.post(
        '/api/client/commands', headers=browser_headers(),
        json={
            'game_uuid': 'game-1', 'action': 'open_path',
            'path': str(Path(__file__).resolve()), 'select': True,
        },
    )
    assert response.status_code == 201
    assert response.json()['command']['id'] == 'command-1'
    assert browser.data.command_calls == [(
        27, 'game-1', 'open_path', {'path': str(Path(__file__).resolve()), 'select': True},
    )]

    outside_game = browser.post(
        '/api/client/commands', headers=browser_headers(),
        json={
            'game_uuid': 'game-1', 'action': 'open_path',
            'path': str(Path(__file__).resolve().parent.parent),
        },
    )
    assert outside_game.status_code == 403
    assert len(browser.data.command_calls) == 1


def test_command_queue_checks_game_and_translation_patch_version():
    client = make_client(scopes=('write:download',))
    headers = bearer_headers(client)
    missing_game = client.post(
        '/api/client/commands', headers=headers,
        json={'game_uuid': 'missing', 'action': 'install'},
    )
    assert missing_game.status_code == 404

    success = client.post(
        '/api/client/commands', headers=headers,
        json={
            'game_uuid': 'game-1', 'action': 'apply_patch',
            'kind': 'extra', 'version_uuid': 'patch-1',
        },
    )
    assert success.status_code == 201
    assert client.data.command_calls[-1] == (
        27, 'game-1', 'apply_patch', {'kind': 'extra', 'version_uuid': 'patch-1'},
    )


def test_ack_and_nack_require_lifecycle_scope_and_return_legacy_counts():
    client = make_client(scopes=('read:library',))
    session_client = make_client()
    session_client.cookies.set('session', browser_cookie())
    denied = session_client.post('/api/client/commands/ack', json={'ids': ['one']})
    assert denied.status_code == 403
    assert denied.json()['error'] == 'Companion API token required'

    headers = {'Authorization': f'Bearer {RAW_TOKEN}'}
    denied_ack = client.post(
        '/api/client/commands/ack',
        headers=headers,
        json={'ids': ['one', 2]},
    )
    denied_nack = client.post(
        '/api/client/commands/nack',
        headers=headers,
        json={'ids': ['three']},
    )
    assert denied_ack.status_code == 403
    assert denied_ack.json()['detail']['required_scope'] == 'write:download or write:library'
    assert denied_nack.status_code == 403
    assert client.data.command_calls == []

    client = make_client(scopes=('write:download',))
    headers = {'Authorization': f'Bearer {RAW_TOKEN}'}
    response = client.post(
        '/api/client/commands/ack', headers=headers, json={'ids': ['one', 2]},
    )
    assert response.status_code == 200
    assert response.json()['removed'] == 2
    response = client.post(
        '/api/client/commands/nack',
        headers=headers,
        json={'ids': ['three']},
    )
    assert response.status_code == 200
    assert response.json()['released'] == 1
    assert client.data.command_calls == [
        ('ack', 27, ['one', '2']), ('nack', 27, ['three'])
    ]
