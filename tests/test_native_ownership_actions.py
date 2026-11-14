from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask

from tests.fixtures.native_auth import login_identity_for, persistent_login_store

from oneirodex.runtime_native.ownership_actions import (
    create_ownership_actions_router,
)
from oneirodex.runtime_native.ownership_providers import (
    create_ownership_provider_router,
)
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token,
)
from oneirodex.utils.store_credentials import (
    StoreCredentialKeyUnavailable,
    StoreCredentialMigrationRequired,
)
from oneirodex.utils.store_sync_errors import SyncOutcomeError


class FakeOwnershipActions:
    def __init__(self):
        self.calls = []
        self.is_enabled = True
        self.sync_error = None
        self.connect_error = None

    def enabled(self):
        return self.is_enabled

    def connect(self, user_id, store, fields):
        self.calls.append(('connect', user_id, store, fields))
        if self.connect_error:
            raise self.connect_error
        return SimpleNamespace(to_dict=lambda: {'store': store, 'linked': True})

    def disconnect(self, user_id, store):
        self.calls.append(('disconnect', user_id, store))

    def sync(self, user_id, store):
        self.calls.append(('sync', user_id, store))
        if self.sync_error:
            raise self.sync_error
        raise AssertionError('fake sync should not contact a provider')

    def sync_all(self, user_id):
        self.calls.append(('sync_all', user_id))
        return [{'store': 'steam', 'status': 'skipped', 'reason': 'not_connected'}]

    def import_csv(self, user_id, store, csv_text):
        self.calls.append(('csv', user_id, store, csv_text))
        return {'imported': 1}

    def summary(self, user_id):
        self.calls.append(('summary', user_id))
        return {'stores': []}

    def cancel_sync(self, user_id, store):
        self.calls.append(('cancel_sync', user_id, store))
        return {'job': {'status': 'cancelled'}}, None

    def decide(self, user, title_id, expected_revision, game_uuid, *, undo=False):
        self.calls.append(('decide', user.id, title_id, expected_revision, game_uuid, undo))
        return {'updated': True}

    def rollback(self):
        self.calls.append(('rollback',))


@pytest.fixture
def native_client():
    flask_app = Flask('ownership-actions-tests')
    flask_app.config.update(
        SECRET_KEY='ownership-actions-secret',
        SESSION_PROTECTION='none',
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_SECRET_KEY='ownership-actions-secret',
        MAX_CONTENT_LENGTH=1024,
        MAX_UPLOAD_MB=1,
    )
    user = SimpleNamespace(id=7, role='user', state=True, is_active=True, session_fingerprint=lambda: '0123456789abcdef')
    data = FakeOwnershipActions()
    bearer = {'token': None}
    runtime = FastAPI()
    runtime.include_router(create_ownership_actions_router(
        flask_app,
        find_user=lambda _user_id: user,
        find_token=lambda _prefix: bearer['token'],
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: user if user_id.split(':', 1)[0] == str(7) else None,
        data_access=data,
    ))
    runtime.include_router(create_ownership_provider_router(
        flask_app,
        find_user=lambda _user_id: user,
        find_token=lambda _prefix: bearer['token'],
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: user if user_id.split(':', 1)[0] == str(7) else None,
        data_access=data,
    ))
    runtime._test_bearer = bearer
    runtime._test_user = user
    return runtime, data


def _session_cookie(csrf=True):
    session = {'_user_id': login_identity_for(7), '_fresh': True}
    token = generate_csrf_token(session, 'ownership-actions-secret') if csrf else None
    return dump_session_cookie(session, 'ownership-actions-secret'), token


def _request(runtime, method, path, *, json=None, content=None, headers=None, files=None, data=None, cookie=True):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            request_headers = dict(headers or {})
            if cookie:
                session, csrf = _session_cookie()
                request_headers['Cookie'] = f'session={session}'
                request_headers['X-CSRFToken'] = csrf
            return await client.request(
                method, path, json=json, content=content, headers=request_headers,
                files=files, data=data,
            )

    return asyncio.run(send())


def test_connect_preserves_provider_aliases_and_status(native_client):
    runtime, data = native_client

    response = _request(runtime, 'POST', '/api/ownership/gog', json={
        'user_id': ' gog-user ', 'token': ' refresh-secret ', 'note': ' household label ',
    })

    assert response.status_code == 201
    assert response.json()['account'] == {'store': 'gog', 'linked': True}
    assert data.calls[0] == ('connect', 7, 'gog', {
        'gog_user_id': 'gog-user', 'note': 'household label',
        'refresh_token': 'refresh-secret', 'access_token': None,
    })
    assert 'refresh-secret' not in response.text


def test_connect_validation_uses_shared_422_envelope(native_client):
    runtime, data = native_client

    response = _request(runtime, 'POST', '/api/ownership/steam', json={'unknown': 'secret'})

    assert response.status_code == 422
    assert response.json()['error_code'] == 'unprocessable'
    assert 'steam_id' in response.json()['detail']
    assert 'secret' not in response.text
    assert data.calls == []


@pytest.mark.parametrize(
    'error,reason',
    [
        (StoreCredentialKeyUnavailable('secret keyring path'), 'credential_storage_unavailable'),
        (StoreCredentialMigrationRequired('legacy token value'), 'credential_migration_required'),
    ],
)
def test_connect_credential_errors_use_redacted_setup_contract(native_client, error, reason):
    runtime, data = native_client
    data.connect_error = error

    response = _request(runtime, 'POST', '/api/ownership/gog', json={'refresh_token': 'sensitive-token'})

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert response.json()['detail']['reason'] == reason
    assert 'secret keyring path' not in response.text
    assert 'legacy token value' not in response.text
    assert 'sensitive-token' not in response.text


def test_connect_json_mimetype_matches_flask_request_is_json(native_client):
    runtime, data = native_client

    accepted = _request(
        runtime, 'POST', '/api/ownership/steam', content=b'{"steam_id":"123"}',
        headers={'Content-Type': 'application/vnd.oneirodex+json'},
    )
    refused = _request(
        runtime, 'POST', '/api/ownership/steam', content=b'{"steam_id":"456"}',
        headers={'Content-Type': 'text/plain'},
    )

    assert accepted.status_code == 201
    assert refused.status_code == 422
    assert [call[3]['steam_id'] for call in data.calls if call[0] == 'connect'] == ['123']


def test_csrf_refusal_precedes_authentication(native_client):
    runtime, data = native_client

    response = _request(
        runtime, 'POST', '/api/ownership/steam/sync', headers={'Content-Type': 'application/json'},
        content=b'{}', cookie=False,
    )

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert data.calls == []


def test_read_only_bearer_cannot_connect_ownership(native_client):
    runtime, data = native_client
    runtime._test_bearer['token'] = SimpleNamespace(
        user_id=7, scopes=['read:library'], token_hash=hashlib.sha256(b'secret').hexdigest(),
        has_scope=lambda scope: scope in ['read:library'],
        is_expired=lambda _now=None: False, revoked_at=None,
    )

    response = _request(
        runtime, 'POST', '/api/ownership/steam', json={'steam_id': '123'},
        headers={'Authorization': 'Bearer gt_deadbeef_secret'}, cookie=False,
    )

    assert response.status_code == 403, response.text
    assert response.json()['error'] == 'Bearer token requires write:library scope'
    assert data.calls == []


def test_write_bearer_can_connect_ownership(native_client):
    runtime, data = native_client
    runtime._test_bearer['token'] = SimpleNamespace(
        user_id=7, scopes=['read:library', 'write:library'],
        token_hash=hashlib.sha256(b'secret').hexdigest(),
        has_scope=lambda scope: scope in ['read:library', 'write:library'],
        is_expired=lambda _now=None: False, revoked_at=None,
    )

    response = _request(
        runtime, 'POST', '/api/ownership/steam', json={'steam_id': '123'},
        headers={'Authorization': 'Bearer gt_deadbeef_secret'}, cookie=False,
    )

    assert response.status_code == 201
    assert data.calls[0][0:3] == ('connect', 7, 'steam')


def test_child_bearer_with_write_scope_cannot_connect_ownership(native_client):
    runtime, data = native_client
    runtime._test_bearer['token'] = SimpleNamespace(
        user_id=7, scopes=['read:library', 'write:library'],
        token_hash=hashlib.sha256(b'secret').hexdigest(),
        has_scope=lambda scope: scope in ['read:library', 'write:library'],
        is_expired=lambda _now=None: False, revoked_at=None,
    )
    runtime._test_user.role = 'child'

    response = _request(
        runtime, 'POST', '/api/ownership/steam', json={'steam_id': '123'},
        headers={'Authorization': 'Bearer gt_deadbeef_secret'}, cookie=False,
    )

    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert data.calls == []


def test_child_session_cannot_connect_ownership(native_client):
    runtime, data = native_client
    runtime._test_user.role = 'child'

    response = _request(
        runtime, 'POST', '/api/ownership/steam', json={'steam_id': '123'},
    )

    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert data.calls == []


@pytest.mark.parametrize(
    ('path', 'payload'),
    [
        ('/api/ownership/gog/sync/cancel', {}),
        ('/api/ownership/titles/1/match', {'game_uuid': 'game-1'}),
        ('/api/ownership/titles/1/match/undo', {}),
    ],
)
def test_child_session_cannot_cancel_or_review_ownership(native_client, path, payload):
    runtime, data = native_client
    runtime._test_user.role = 'child'

    response = _request(runtime, 'POST', path, json=payload)

    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert data.calls == []


def test_sync_failure_is_redacted_and_sync_all_is_not_shadowed(native_client):
    runtime, data = native_client
    data.sync_error = SyncOutcomeError('network_error')

    failed = _request(runtime, 'POST', '/api/ownership/steam/sync', json={})
    all_stores = _request(runtime, 'POST', '/api/ownership/sync-all', json={})

    assert failed.status_code == 502
    assert failed.json()['error_code'] == 'bad_gateway'
    assert 'network_error' in failed.json()['detail']['reason']
    assert 'could not be reached from the server' in failed.json()['message']
    assert all_stores.status_code == 200
    assert all_stores.json()['results'][0]['reason'] == 'not_connected'
    assert ('sync_all', 7) in data.calls


def test_csv_import_accepts_json_and_meta_quest_note(native_client):
    runtime, data = native_client

    response = _request(runtime, 'POST', '/api/ownership/meta_quest/csv', json={'csv': 'id,name\n1,Title'})

    assert response.status_code == 200
    assert response.json()['imported'] == 1
    assert 'never downloads Meta/Quest DRM titles' in response.json()['note']
    assert ('csv', 7, 'meta_quest', 'id,name\n1,Title') in data.calls


def test_csv_import_accepts_multipart_and_enforces_configured_body_limit(native_client):
    runtime, data = native_client
    uploaded = _request(
        runtime, 'POST', '/api/ownership/steam/csv',
        files={'file': ('ownership.csv', b'appid,name\n1,Title', 'text/csv')},
    )
    assert uploaded.status_code == 200
    assert ('csv', 7, 'steam', 'appid,name\n1,Title') in data.calls

    oversized = _request(
        runtime, 'POST', '/api/ownership/steam/csv', content=b'x' * 1025,
        headers={'Content-Type': 'application/json'},
    )
    assert oversized.status_code == 413
    assert oversized.json()['error_code'] == 'payload_too_large'
    assert len([call for call in data.calls if call[0] == 'csv']) == 1


def test_csv_import_has_a_tighter_limit_than_the_global_request_limit(native_client, monkeypatch):
    from oneirodex.runtime_native import ownership_actions

    runtime, data = native_client
    monkeypatch.setattr(ownership_actions, 'MAX_OWNERSHIP_CSV_REQUEST_BYTES', 256)

    wrapped_json_at_csv_limit = _request(
        runtime, 'POST', '/api/ownership/steam/csv', json={'csv': 'x' * 128},
    )
    oversized_multipart = _request(
        runtime, 'POST', '/api/ownership/steam/csv',
        files={'file': ('ownership.csv', b'x' * 512, 'text/csv')},
    )

    async def streamed_body():
        yield b'{"csv":"' + b'x' * 150
        yield b'x' * 150 + b'"}'

    async def send_streamed():
        session, csrf = _session_cookie()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.post(
                '/api/ownership/steam/csv', content=streamed_body(),
                headers={
                    'Content-Type': 'application/json', 'Cookie': f'session={session}',
                    'X-CSRFToken': csrf,
                },
            )

    oversized_streamed = asyncio.run(send_streamed())

    assert wrapped_json_at_csv_limit.status_code == 200
    assert wrapped_json_at_csv_limit.json()['imported'] == 1
    assert oversized_multipart.status_code == 413
    assert oversized_multipart.json()['error_code'] == 'payload_too_large'
    assert oversized_streamed.status_code == 413
    assert oversized_streamed.json()['error_code'] == 'payload_too_large'
    csv_calls = [call for call in data.calls if call[0] == 'csv']
    assert len(csv_calls) == 1
    assert csv_calls[0][3] == 'x' * 128


def test_disconnect_and_feature_gate_preserve_response_contract(native_client):
    runtime, data = native_client

    disconnected = _request(runtime, 'DELETE', '/api/ownership/psn')
    assert disconnected.status_code == 200
    assert ('disconnect', 7, 'psn') in data.calls

    data.is_enabled = False
    denied = _request(runtime, 'POST', '/api/ownership/psn/csv', json={'csv': 'x'})
    assert denied.status_code == 403
    assert denied.json()['error_code'] == 'forbidden'
    assert len([call for call in data.calls if call[0] == 'csv']) == 0


def test_ownership_action_routes_are_limited_to_supported_store_slugs(native_client):
    runtime, data = native_client

    reserved = (
            # The provider router exposes these paths for their read methods.
        ('POST', '/api/ownership/connections', 405),
        ('DELETE', '/api/ownership/providers', 405),
            ('POST', '/api/ownership/titles', 405),
        ('DELETE', '/api/ownership/sync-all', 405),
    )
    for method, path, expected_status in reserved:
        response = _request(runtime, method, path)
        assert response.status_code == expected_status, (method, path, response.text)
    assert data.calls == []
