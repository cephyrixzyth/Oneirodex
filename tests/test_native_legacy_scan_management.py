from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask

from oneirodex.runtime_native.legacy_scan_management import create_legacy_scan_management_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeScanManagementData:
    def __init__(self):
        self.calls = []
        self.library_row = SimpleNamespace(uuid='lib-1', name='Library', scan_depth=2)

    def library(self, uuid):
        return self.library_row if uuid == 'lib-1' else None

    def add_filter(self, pattern, case_sensitive):
        self.calls.append(('add_filter', pattern, case_sensitive))

    def delete_filter(self, filter_id):
        self.calls.append(('delete_filter', filter_id))
        return filter_id == 4

    def delete_unmatched(self, *, only_unmatched):
        self.calls.append(('delete_unmatched', only_unmatched))
        return 3

    def resolve_path(self, app, folder, root):
        self.calls.append(('resolve', folder, root))
        return (folder or '/safe/root/games'), None

    def allowed_bases(self, app):
        return ['/safe/root']

    def safe_path(self, path, bases):
        return path.startswith('/safe/root'), 'outside configured roots'

    def readable(self, path):
        return path.startswith('/safe/root')

    def scan_mode(self, path, requested):
        return 'folders' if requested == 'auto' else requested

    def busy(self):
        return False

    def start_scan(self, *, library, folder, options, app, database_scope=None):
        self.calls.append(('start_scan', library.uuid, folder, options))
        return {'status': 'queued', 'message': 'Scan queued.'}

    def scan_patterns(self):
        return ([], [])

    def list_folders(self, path, insensitive, sensitive, library):
        self.calls.append(('list_folders', path, library.uuid))
        return [{'name': 'Game A', 'full_path': path + '/Game A'}]

    def list_files(self, path, insensitive, sensitive):
        self.calls.append(('list_files', path))
        return ([{'name': 'Game A', 'full_path': path + '/Game A.iso'}], True)

    def metadata_write_permissions(self, path):
        return True, []


@pytest.fixture
def native_client():
    app = Flask('legacy-scan-management-tests')
    app.config.update(
        SECRET_KEY='scan-management-secret', WTF_CSRF_ENABLED=True,
        WTF_CSRF_SECRET_KEY='scan-management-secret', SESSION_PROTECTION='none',
    )
    user = SimpleNamespace(id=9, name='Admin', role='admin', state=True, is_active=True)
    data = FakeScanManagementData()
    runtime = FastAPI()
    runtime.include_router(create_legacy_scan_management_router(
        app, find_user=lambda _id: user, find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: user if user_id == '9:fp' else None,
        data_access=data, database_scope=lambda _app: nullcontext(),
    ))
    return runtime, data


def _request(runtime, action, *, fields=None, csrf=True):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
            follow_redirects=False,
        ) as client:
            session = {'_user_id': '9:fp', '_fresh': True}
            token = generate_csrf_token(session, 'scan-management-secret')
            cookie = dump_session_cookie(session, 'scan-management-secret')
            body = {'submit': action, 'csrf_token': token if csrf else 'invalid', **(fields or {})}
            headers = {'Cookie': f'session={cookie}'}
            if csrf:
                headers['X-CSRFToken'] = token
            return await client.post('/scan_management', data=body, headers=headers)
    return asyncio.run(send())


def test_legacy_scan_management_csrf_and_filter_actions(native_client):
    runtime, data = native_client
    refused = _request(runtime, 'AddReleaseGroup', fields={'filter_pattern': 'Scene'}, csrf=False)
    assert refused.status_code == 400
    assert data.calls == []

    added = _request(runtime, 'AddReleaseGroup', fields={
        'filter_pattern': ' Scene ', 'case_sensitive': 'yes',
    })
    assert added.status_code == 302
    assert added.headers['location'] == '/scan_management?active_tab=scan_filters'
    assert ('add_filter', 'Scene', True) in data.calls

    deleted = _request(runtime, 'DeleteReleaseGroup', fields={'filter_id': '4'})
    assert deleted.status_code == 302
    assert ('delete_filter', 4) in data.calls


def test_legacy_scan_management_unmatched_cleanup_actions(native_client):
    runtime, data = native_client
    all_rows = _request(runtime, 'DeleteAllUnmatched')
    only_unmatched = _request(runtime, 'DeleteOnlyUnmatched')
    assert all_rows.status_code == only_unmatched.status_code == 302
    assert ('delete_unmatched', False) in data.calls
    assert ('delete_unmatched', True) in data.calls


def test_legacy_scan_management_auto_and_manual_scan_actions(native_client):
    runtime, data = native_client
    auto = _request(runtime, 'AutoScan', fields={
        'library_uuid': 'lib-1', 'folder_path': '/safe/root/library',
        'scan_mode': 'folders', 'remove_missing': 'y', 'fetch_hltb': 'y',
    })
    assert auto.status_code == 302
    assert auto.headers['location'] == '/scan_management?active_tab=auto&library_uuid=lib-1'
    queued = next(call for call in data.calls if call[0] == 'start_scan')
    assert queued[3]['remove_missing'] is True
    assert queued[3]['fetch_hltb'] is True

    manual = _request(runtime, 'ManualScan', fields={
        'library_uuid': 'lib-1', 'folder_path': '/safe/root/library',
        'scan_mode': 'folders', 'force_updates_extras_scan': 'on',
    })
    assert manual.status_code == 302
    assert manual.headers['location'] == '/scan_management?active_tab=manual&library_uuid=lib-1'
    assert ('list_folders', '/safe/root/library', 'lib-1') in data.calls


@pytest.mark.parametrize(('action', 'tab'), [('AutoScan', 'auto'), ('ManualScan', 'manual')])
def test_legacy_scan_management_rejects_unknown_scan_mode(native_client, action, tab):
    runtime, data = native_client
    response = _request(runtime, action, fields={
        'library_uuid': 'lib-1', 'folder_path': '/safe/root/library',
        'scan_mode': 'unexpected-mode',
    })

    assert response.status_code == 302
    assert response.headers['location'] == f'/scan_management?active_tab={tab}'
    assert not any(call[0] in {'start_scan', 'list_folders', 'list_files'} for call in data.calls)


def test_legacy_scan_management_rejects_padded_schedule_choice(native_client):
    runtime, data = native_client
    response = _request(runtime, 'AutoScan', fields={
        'library_uuid': 'lib-1', 'folder_path': '/safe/root/library',
        'scan_mode': 'folders', 'schedule': ' interval ',
        'schedule_interval_value': '15', 'schedule_interval_unit': 'minutes',
    })

    assert response.status_code == 302
    assert response.headers['location'] == '/scan_management?active_tab=auto'
    assert not any(call[0] == 'start_scan' for call in data.calls)


def test_legacy_scan_management_uses_six_hour_interval_default(native_client):
    runtime, data = native_client
    response = _request(runtime, 'AutoScan', fields={
        'library_uuid': 'lib-1', 'folder_path': '/safe/root/library',
        'scan_mode': 'folders', 'schedule': 'interval',
    })

    assert response.status_code == 302
    queued = next(call for call in data.calls if call[0] == 'start_scan')
    assert queued[3]['schedule_fields']['schedule_interval_minutes'] == 360


def test_legacy_scan_management_rejects_unknown_libraries_and_unsafe_paths(native_client):
    runtime, data = native_client
    unknown = _request(runtime, 'AutoScan', fields={'library_uuid': 'missing'})
    unsafe = _request(runtime, 'ManualScan', fields={
        'library_uuid': 'lib-1', 'folder_path': '/etc',
    })
    assert unknown.status_code == unsafe.status_code == 302
    assert not any(call[0] == 'start_scan' for call in data.calls)
    assert not any(call[0] == 'list_folders' for call in data.calls)
