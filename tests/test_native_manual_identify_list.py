"""Fake-only contracts for native manual-identify preview and queue behavior."""
from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.library_tools_manual_identify import (
    create_manual_identify_list_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie


class FakeManualIdentifyData:
    def __init__(self):
        self.library_row = SimpleNamespace(uuid='lib-1', name='Library', scan_depth=3)
        self.busy = False
        self.write_metadata = False
        self.permission_result = (True, [])
        self.extensions = ['.iso']
        self.resolved_path = '/safe/scan'
        self.queue_result = {'status': 'queued', 'job_id': 'job-fake', 'position': 2}
        self.calls = []

    def library(self, _app, library_uuid):
        self.calls.append(('library', library_uuid))
        return self.library_row if library_uuid == 'lib-1' else None

    def resolve_scan_path(self, _app, folder, root):
        self.calls.append(('resolve', folder, root))
        return self.resolved_path, None

    def safe_path(self, _app, path):
        self.calls.append(('safe', path))
        return (path.startswith('/safe'), 'outside configured roots')

    def readable_directory(self, path):
        self.calls.append(('readable', path))
        return path.startswith('/safe')

    def scan_mode(self, _app, path, requested):
        self.calls.append(('mode', path, requested))
        return 'folders' if requested == 'folders' else 'files'

    def is_scan_busy(self):
        self.calls.append(('busy',))
        return self.busy

    def start_or_queue_scan(self, **kwargs):
        self.calls.append(('queue', kwargs))
        return self.queue_result

    def write_local_metadata_enabled(self):
        self.calls.append(('write_metadata_enabled',))
        return self.write_metadata

    def check_library_write_permissions(self, path):
        self.calls.append(('permissions', path))
        return self.permission_result

    def games_in_folder(self, _app, path, library):
        self.calls.append(('games_folders', path, library.uuid))
        return [{'name': 'Metroid', 'full_path': '/safe/scan/Metroid'}]

    def allowed_extensions(self, _app):
        self.calls.append(('extensions',))
        return list(self.extensions)

    def games_in_files(self, _app, path, extensions):
        self.calls.append(('games_files', path, tuple(extensions)))
        return [{'name': 'Disc', 'full_path': '/safe/scan/disc.iso'}]

    def write_preview_session(self, session_data, library, games, parsed_body):
        # Mutate only the request's ephemeral session mapping; no client store
        # or durable session backend is configured in this test harness.
        self.calls.append(('write_preview_session', library.uuid, len(games)))
        session_data['selected_library_uuid'] = library.uuid
        session_data['game_paths'] = {row['name']: row['full_path'] for row in games}
        session_data['force_updates_extras_scan'] = parsed_body.force_updates_extras_scan
        session_data['fetch_hltb'] = parsed_body.fetch_hltb
        session_data['force_hltb_refetch'] = parsed_body.force_hltb_refetch


@pytest.fixture
def runtime():
    flask_app = Flask('manual-identify-list-test')
    flask_app.config.update(
        SECRET_KEY='manual-identify-list-test-secret', SESSION_PROTECTION='none',
        SECURITY_HEADERS_ENABLED=True, WTF_CSRF_ENABLED=False,
    )
    users = {
        'admin': SimpleNamespace(id=7, role='admin', state=True, is_active=True,
                                 is_authenticated=True, session_fingerprint=lambda: 'fp'),
        'member': SimpleNamespace(id=8, role='user', state=True, is_active=True,
                                  is_authenticated=True, session_fingerprint=lambda: 'fp'),
    }
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: next(
        (user for user in users.values() if identity == f'{user.id}:fp'), None,
    ))
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    fake = FakeManualIdentifyData()
    app = FastAPI()
    app.include_router(create_manual_identify_list_router(
        flask_app,
        find_user=lambda uid: next((user for user in users.values() if user.id == uid), None),
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager,
        data_access=fake,
    ))
    cookies = {
        name: dump_session_cookie(
            {'_user_id': f'{user.id}:fp', '_fresh': True},
            'manual-identify-list-test-secret',
        )
        for name, user in users.items()
    }
    return app, flask_app, fake, cookies


def request(runtime, path='/api/library_tools/manual_identify/list', *, cookie=None, json=None,
            headers=None):
    app = runtime[0]

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
            follow_redirects=False,
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.post(path, json=json, headers=headers or {})

    return asyncio.run(perform())


def body(**overrides):
    payload = {'library_uuid': 'lib-1', 'folder': 'Manual', 'root': 'games', 'scan_mode': 'folders'}
    payload.update(overrides)
    return payload


def test_idle_preview_returns_candidates_and_persists_exact_legacy_session_keys(runtime):
    app, flask_app, data, cookies = runtime
    response = request(runtime, cookie=cookies['admin'], json=body(fetch_hltb=False))

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.json()['action'] == 'preview'
    assert response.json()['games'][0]['name'] == 'Metroid'
    assert response.json()['read_only'] is True
    assert ('busy',) in data.calls
    assert not any(call[0] == 'queue' for call in data.calls)
    saved = load_session_cookie(
        response.cookies['session'], flask_app.config['SECRET_KEY'], max_age=31_536_000,
    )
    assert saved['selected_library_uuid'] == 'lib-1'
    assert saved['game_paths'] == {'Metroid': '/safe/scan/Metroid'}
    assert saved['force_updates_extras_scan'] is False
    assert saved['fetch_hltb'] is False
    assert saved['force_hltb_refetch'] is False


@pytest.mark.parametrize('policy', ['queue', 'force'])
def test_busy_queue_and_force_preserve_scheduler_options(runtime, policy):
    _app, flask_app, data, cookies = runtime
    data.busy = True
    data.queue_result = {'status': 'queued', 'message': 'Queued', 'job_id': 'fake-1', 'position': 4}
    response = request(runtime, cookie=cookies['admin'], json=body(
        scan_mode='auto', queue_policy=policy, force_updates_extras_scan=True,
        fetch_hltb=False, force_hltb_refetch=True,
    ))

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert {key: response.json()[key] for key in ('action', 'message', 'job_id', 'position', 'read_only')} == {
        'action': 'queued', 'message': 'Queued', 'job_id': 'fake-1',
        'position': 4, 'read_only': False,
    }
    queued = next(call[1] for call in data.calls if call[0] == 'queue')
    assert queued == {
        'folder_path': '/safe/scan', 'library_uuid': 'lib-1', 'scan_mode': 'files',
        'remove_missing': False, 'download_missing_images': False,
        'force_updates_extras_scan': True, 'fetch_hltb': False,
        'force_hltb_refetch': True, 'schedule': None, 'queue_policy': policy,
        'allow_force': True, 'app': flask_app,
    }


def test_busy_inspect_is_read_only_and_never_queues(runtime):
    _app, _flask_app, data, cookies = runtime
    data.busy = True
    response = request(runtime, cookie=cookies['admin'], json=body(queue_policy='inspect'))

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert {key: response.json()[key] for key in ('action', 'message', 'read_only')} == {
        'action': 'conflict', 'message': 'Another scan is already running.', 'read_only': True,
    }
    assert not any(call[0] == 'queue' for call in data.calls)


def test_idle_files_mode_uses_allowlisted_extensions_and_permission_gate(runtime):
    _app, _flask_app, data, cookies = runtime
    data.write_metadata = True
    response = request(runtime, cookie=cookies['admin'], json=body(scan_mode='files'))

    assert response.status_code == 200
    assert response.json()['games'][0]['name'] == 'Disc'
    assert ('extensions',) in data.calls
    assert ('games_files', '/safe/scan', ('.iso',)) in data.calls
    assert ('permissions', '/safe/scan') in data.calls


def test_failed_write_permissions_refuse_preview_before_listing(runtime):
    _app, _flask_app, data, cookies = runtime
    data.write_metadata = True
    data.permission_result = (False, ['/safe/scan/one', '/safe/scan/two'])
    response = request(runtime, cookie=cookies['admin'], json=body())

    assert response.status_code == 422
    assert response.json()['detail'] == {'failed_count': 2}
    assert not any(call[0] == 'games_folders' for call in data.calls)


def test_missing_supported_extensions_refuses_file_preview(runtime):
    _app, _flask_app, data, cookies = runtime
    data.extensions = []
    response = request(runtime, cookie=cookies['admin'], json=body(scan_mode='files'))

    assert response.status_code == 422
    assert response.json()['error'] == 'No supported game file types are configured'
    assert not any(call[0] == 'games_files' for call in data.calls)


def test_queue_rejection_preserves_conflict_contract(runtime):
    _app, _flask_app, data, cookies = runtime
    data.busy = True
    data.queue_result = {'status': 'rejected', 'message': 'Queue is full'}
    response = request(runtime, cookie=cookies['admin'], json=body(queue_policy='queue'))

    assert response.status_code == 409
    assert response.json()['error_code'] == 'conflict'
    assert response.json()['error'] == 'Queue is full'


@pytest.mark.parametrize('bad_payload', [
    {'library_uuid': 'lib-1', 'unknown': True},
    ['not', 'an', 'object'],
    {'library_uuid': 'lib-1', 'scan_mode': 'recursive'},
])
def test_request_schema_is_strict_and_does_not_reach_data_adapter(runtime, bad_payload):
    _app, _flask_app, data, cookies = runtime
    response = request(runtime, cookie=cookies['admin'], json=bad_payload)

    assert response.status_code == 422
    assert response.json()['error_code'] == 'unprocessable'
    assert data.calls == []


def test_admin_and_path_gates_precede_scan_or_preview_effects(runtime):
    _app, _flask_app, data, cookies = runtime
    denied = request(runtime, cookie=cookies['member'], json=body())
    assert denied.status_code == 302
    assert data.calls == []
    data.calls.clear()
    data.resolved_path = '/outside/scan'
    unsafe = request(runtime, cookie=cookies['admin'], json=body())
    assert unsafe.status_code == 403
    assert not any(call[0] in {'readable', 'busy', 'games_folders', 'queue'} for call in data.calls)


def test_invalid_csrf_is_rejected_before_auth_resolution():
    flask_app = Flask('manual-identify-csrf-order')
    flask_app.config.update(SECRET_KEY='csrf-order-secret', WTF_CSRF_ENABLED=True)
    called = []
    app = FastAPI()
    app.include_router(create_manual_identify_list_router(
        flask_app, find_user=lambda _uid: called.append('user') or None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        data_access=FakeManualIdentifyData(),
    ))

    async def perform():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            return await client.post('/api/library_tools/manual_identify/list', json=body())

    response = asyncio.run(perform())
    assert response.status_code == 400
    assert called == []


@pytest.mark.parametrize(('scopes', 'expected_status'), [([], 403), (['admin'], 200)])
def test_bearer_admin_scope_gate(scopes, expected_status):
    flask_app = Flask('manual-identify-token-scope')
    flask_app.config.update(
        SECRET_KEY='manual-identify-token-secret', WTF_CSRF_ENABLED=False,
        SESSION_PROTECTION='none',
    )
    user = SimpleNamespace(id=17, role='admin', state=True, is_active=True,
                           is_authenticated=True)
    raw_secret = 'secret-for-test'
    token = SimpleNamespace(
        token_hash=hashlib.sha256(raw_secret.encode()).hexdigest(), user_id=17,
        revoked_at=None, is_expired=lambda _now: False, scopes=scopes,
    )
    data = FakeManualIdentifyData()
    app = FastAPI()
    app.include_router(create_manual_identify_list_router(
        flask_app,
        find_user=lambda uid: user if uid == 17 else None,
        find_token=lambda prefix: token if prefix == 'scope' else None,
        commit_token_touch=lambda _token: None,
        data_access=data,
    ))

    async def perform():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            return await client.post(
                '/api/library_tools/manual_identify/list', json=body(),
                headers={'Authorization': f'Bearer gt_scope_{raw_secret}'},
            )

    response = asyncio.run(perform())
    assert response.status_code == expected_status
    if expected_status == 403:
        assert data.calls == []
    else:
        assert response.json()['action'] == 'preview'
