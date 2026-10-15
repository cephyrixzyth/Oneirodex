from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask

from oneirodex.runtime_native.ownership_actions import (
    create_ownership_actions_router,
)
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token,
)
from oneirodex.utils.store_sync_errors import SyncOutcomeError


class FakeOwnershipActions:
    def __init__(self):
        self.calls = []
        self.is_enabled = True
        self.sync_error = None

    def enabled(self):
        return self.is_enabled

    def connect(self, user_id, store, fields):
        self.calls.append(('connect', user_id, store, fields))
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
    user = SimpleNamespace(id=7, role='user', state=True, is_active=True)
    data = FakeOwnershipActions()
    bearer = {'token': None}
    runtime = FastAPI()
    runtime.include_router(create_ownership_actions_router(
        flask_app,
        find_user=lambda _user_id: user,
        find_token=lambda _prefix: bearer['token'],
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: user if user_id == '7:fp' else None,
        data_access=data,
    ))
    runtime._test_bearer = bearer
    return runtime, data


def _session_cookie(csrf=True):
    session = {'_user_id': '7:fp', '_fresh': True}
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
