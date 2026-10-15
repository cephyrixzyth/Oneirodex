"""Database-free contracts for the native personal API-token routes."""
from __future__ import annotations

import hashlib
import re
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient

from oneirodex.runtime_native.account_tokens import mount_account_tokens_routes
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie,
    generate_csrf_token,
)


SECRET_KEY = 'native-token-test-secret'


class FakeUser:
    def __init__(self, user_id=27, role='user'):
        self.id = user_id
        self.role = role
        self.state = True
        self.is_active = True


class FakeToken:
    def __init__(self, token_id, user_id, scopes, *, prefix=None, secret='test-secret'):
        self.id = token_id
        self.user_id = user_id
        self.scopes = list(scopes)
        self.token_prefix = prefix or f'{token_id:08x}'
        self.token_hash = hashlib.sha256(secret.encode()).hexdigest()
        self.revoked_at = None
        self.expires_at = None
        self.last_used_at = None

    def is_expired(self, now=None):
        return False

    def has_scope(self, scope):
        return 'admin' in self.scopes or scope in self.scopes


class FakeRow:
    def __init__(self, token_id, user_id, scopes, prefix='a1b2c3d4'):
        self.id = token_id
        self.user_id = user_id
        self.scopes = list(scopes)
        self.token_prefix = prefix

    def to_public_dict(self):
        return {
            'id': self.id,
            'name': 'CLI',
            'token_prefix': self.token_prefix,
            'scopes': list(self.scopes),
            'created_at': '2026-01-01T00:00:00+00:00',
            'last_used_at': None,
            'expires_at': None,
            'revoked_at': None,
        }


class FakeData:
    def __init__(self, rows=(), *, raw='gt_a1b2c3d4_RawSecret_0123456789'):
        self.rows = list(rows)
        self.raw = raw
        self.created = []
        self.revocations = []

    def list_for_user(self, user_id):
        return [row for row in self.rows if row.user_id == user_id]

    def create(self, user, name, scopes):
        self.created.append((user.id, name, scopes))
        row = FakeRow(90 + len(self.created), user.id, scopes or ['read:library'])
        return row, self.raw

    def revoke(self, token_id, user_id):
        self.revocations.append((token_id, user_id))
        row = next(
            (row for row in self.rows if row.id == token_id and row.user_id == user_id),
            None,
        )
        return row is not None


class FakePolicy:
    valid = frozenset({
        'read:library', 'read:social', 'write:social', 'write:presence',
        'write:download', 'write:library', 'admin',
    })
    preset_map = {
        'companion': {'label': 'Desktop companion', 'scopes': ['read:library', 'write:download']},
        'thin': {'label': 'Thin client', 'scopes': ['read:library', 'read:social', 'write:presence']},
    }

    def valid_scopes(self):
        return self.valid

    def presets(self):
        return self.preset_map

    def forbidden_scopes(self, role):
        return frozenset({'admin', 'write:library', 'write:download'}) if role == 'child' else frozenset()

    def is_raw_token(self, raw):
        return bool(re.fullmatch(r'gt_[0-9a-f]{8}_[A-Za-z0-9_-]+', raw or ''))


class FakeFlaskApp:
    def __init__(self, *, csrf_enabled=True):
        self.config = {
        'SECRET_KEY': SECRET_KEY,
        'SECRET_KEY_FALLBACKS': [],
        'SESSION_COOKIE_NAME': 'session',
        'REMEMBER_COOKIE_NAME': 'remember_token',
        'PERMANENT_SESSION_LIFETIME': timedelta(days=31),
        'SESSION_PROTECTION': None,
        'SESSION_REFRESH_EACH_REQUEST': True,
        'WTF_CSRF_ENABLED': csrf_enabled,
        'WTF_CSRF_FIELD_NAME': 'csrf_token',
        'WTF_CSRF_TIME_LIMIT': 3600,
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SECURE': False,
        'SESSION_COOKIE_SAMESITE': 'Lax',
        }
        self.logger = SimpleNamespace(error=lambda *args, **kwargs: None)

    def app_context(self):
        return nullcontext()


class FakeLoginManager:
    login_view = '/login'
    blueprint_login_views = {}
    login_message = None
    login_message_category = 'message'


def make_client(*, user=None, rows=(), bearer=None, raw=None, csrf_enabled=True):
    app = FastAPI()
    data = FakeData(rows, raw=raw or 'gt_a1b2c3d4_RawSecret_0123456789')
    policy = FakePolicy()
    users = {user.id: user} if user is not None else {}
    tokens = {bearer.token_prefix: bearer} if bearer is not None else {}
    touched = []

    mount_account_tokens_routes(
        app,
        FakeFlaskApp(csrf_enabled=csrf_enabled),
        find_user=lambda user_id: users.get(user_id),
        find_token=lambda prefix: tokens.get(prefix),
        commit_token_touch=touched.append,
        load_user_id=lambda user_id: users.get(int(str(user_id).split(':', 1)[0])),
        login_manager=FakeLoginManager(),
        data_access=data,
        policy=policy,
    )
    return TestClient(app), data, touched


def browser_credentials(user: FakeUser):
    session = {'_user_id': str(user.id)}
    csrf = generate_csrf_token(session, SECRET_KEY)
    return {
        'Cookie': 'session=' + dump_session_cookie(session, SECRET_KEY),
        'X-CSRFToken': csrf,
    }


def test_list_tokens_preserves_personal_scope_projection_and_public_rows():
    user = FakeUser()
    owned = FakeRow(1, user.id, ['read:library'])
    other = FakeRow(2, user.id + 1, ['admin'])
    client, _, _ = make_client(user=user, rows=[owned, other])

    response = client.get('/api/tokens', headers=browser_credentials(user))

    assert response.status_code == 200
    body = response.json()
    assert [row['id'] for row in body['tokens']] == [owned.id]
    assert 'valid_scopes' in body and 'scope_presets' in body
    assert 'secret' not in body
    assert 'ok' not in body  # Existing GET is the legacy flat projection.


def test_child_role_hides_forbidden_scopes_and_presets():
    child = FakeUser(role='child')
    client, _, _ = make_client(user=child)

    response = client.get('/api/tokens', headers=browser_credentials(child))

    assert response.status_code == 200
    body = response.json()
    assert 'admin' not in body['valid_scopes']
    assert 'write:library' not in body['valid_scopes']
    assert 'write:download' not in body['valid_scopes']
    assert 'companion' not in body['scope_presets']


def test_create_returns_raw_secret_once_with_201_and_csrf():
    user = FakeUser()
    client, data, _ = make_client(user=user)

    response = client.post(
        '/api/tokens',
        headers=browser_credentials(user),
        json={'name': '  Desktop  ', 'preset': ' COMPANION '},
    )

    assert response.status_code == 201
    body = response.json()
    assert body['secret'] == 'gt_a1b2c3d4_RawSecret_0123456789'
    assert body['token']['token_prefix'] in body['secret']
    assert body['warning'] == 'Store this secret now; it will not be shown again.'
    assert data.created == [(user.id, 'Desktop', ['read:library', 'write:download'])]


def test_create_requires_csrf_before_body_validation():
    user = FakeUser()
    client, data, _ = make_client(user=user)
    auth = browser_credentials(user)

    response = client.post('/api/tokens', headers={'Cookie': auth['Cookie']}, json={})

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert response.json()['error'] == 'The CSRF token is missing.'
    assert data.created == []


def test_create_enforces_role_and_bearer_scope_narrowing():
    user = FakeUser()
    admin_scope_data = make_client(user=user)[0]
    denied_role = admin_scope_data.post(
        '/api/tokens',
        headers=browser_credentials(user),
        json={'name': 'Admin', 'scopes': [' admin ']},
    )
    assert denied_role.status_code == 403
    assert denied_role.json()['error_code'] == 'forbidden'

    bearer = FakeToken(7, user.id, ['read:library'], prefix='1234abcd', secret='bearer-secret')
    client, data, touched = make_client(user=user, bearer=bearer, csrf_enabled=False)
    denied_scope = client.post(
        '/api/tokens',
        headers={'Authorization': 'Bearer gt_1234abcd_bearer-secret'},
        json={'name': 'Too broad', 'scopes': ['read:social']},
    )
    assert denied_scope.status_code == 403
    assert denied_scope.json()['detail'] == {'denied_scopes': ['read:social']}
    assert data.created == []
    assert touched == [bearer]


def test_create_refuses_unknown_preset_and_impure_secret():
    user = FakeUser()
    client, data, _ = make_client(user=user)
    headers = browser_credentials(user)

    unknown = client.post('/api/tokens', headers=headers, json={'name': 'x', 'preset': 'unknown'})
    assert unknown.status_code == 400
    assert unknown.json()['error'] == 'Unknown preset: unknown'

    client, data, _ = make_client(user=user, raw='label gt_secret')
    impure = client.post('/api/tokens', headers=headers, json={'name': 'x'})
    assert impure.status_code == 500
    assert impure.json()['error_code'] == 'internal'
    assert 'secret' not in impure.text


def test_create_validates_body_without_echoing_user_input():
    user = FakeUser()
    client, data, _ = make_client(user=user)

    response = client.post(
        '/api/tokens',
        headers=browser_credentials(user),
        json={'name': {'sensitive': 'never echo'}, 'unexpected': 'private'},
    )

    assert response.status_code == 422
    assert response.json()['error_code'] == 'unprocessable'
    assert 'never echo' not in response.text
    assert 'private' not in response.text
    assert data.created == []


def test_delete_is_csrf_protected_and_scoped_to_authenticated_owner():
    user = FakeUser()
    owned = FakeRow(10, user.id, ['read:library'])
    foreign = FakeRow(11, user.id + 1, ['read:library'])
    client, data, _ = make_client(user=user, rows=[owned, foreign])
    headers = browser_credentials(user)

    denied = client.delete('/api/tokens/10', headers={'Cookie': headers['Cookie']})
    assert denied.status_code == 400
    assert data.revocations == []

    deleted = client.delete('/api/tokens/10', headers=headers)
    assert deleted.status_code == 200
    assert deleted.json() == {
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert data.revocations == [(10, user.id)]

    not_owned = client.delete('/api/tokens/11', headers=headers)
    assert not_owned.status_code == 404
    assert not_owned.json()['error_code'] == 'not_found'
    assert data.revocations[-1] == (11, user.id)


def test_unauthenticated_get_keeps_flask_login_redirect_contract():
    client, _, _ = make_client()

    response = client.get('/api/tokens', follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['location'].startswith('/login?next=%2Fapi%2Ftokens')
