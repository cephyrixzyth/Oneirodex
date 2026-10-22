from __future__ import annotations

import asyncio
from contextlib import nullcontext
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask, redirect as flask_redirect
from PIL import Image

from oneirodex.runtime_native.library_admin_mutations import (
    LibraryAdminMutationData,
    create_library_admin_mutations_router,
)
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token,
)


class FakeLibraryAdminMutations:
    def __init__(self):
        self.items = {
            'lib-1': SimpleNamespace(uuid='lib-1', name='Library One', last_scan_folder='/safe/root/one'),
        }
        self.calls = []

    def library(self, library_uuid):
        return self.items.get(library_uuid)

    def create(self, **values):
        self.calls.append(('create', values))
        return {'library_uuid': 'new-lib', 'name': values['name']}

    def update(self, library, **values):
        self.calls.append(('update', library.uuid, values))
        return {
            'uuid': library.uuid, 'name': values['name'],
            'platform': values['platform'].name,
            'scan_depth': values['scan_depth'],
        }

    def start_scan(self, *, library, folder, options, app, database_scope=None):
        self.calls.append(('scan', library.uuid, folder, options, database_scope))
        return {'status': 'queued', 'job_id': 'scan-job', 'position': 2, 'message': 'queued'}

    def fail_scan_for_legacy_mode(self, *, library, folder, options):
        self.calls.append(('fail_scan_mode', library.uuid, folder, options))
        return {
            'status': 'started', 'job_id': 'failed-scan-job', 'position': None,
            'message': 'Scan started (job failed-s…).',
        }

    def resolve_scan_path(self, app, folder, library_root):
        self.calls.append(('resolve', folder, library_root))
        resolved = folder or '/safe/root/one'
        if not resolved.startswith('/'):
            resolved = '/safe/root/' + resolved
        return resolved, None

    def allowed_bases(self, _app):
        return ['/safe/root']

    def safe_path(self, path, allowed_bases):
        return path.startswith('/safe/root'), None

    def scan_mode_for_path(self, _path, _mode):
        return 'files'

    def refresh_queue(self):
        return [{'uuid': 'lib-1', 'name': 'Library One', 'folder': '/safe/root/one'}]

    def refresh_busy(self):
        self.calls.append(('refresh_busy',))
        return False

    def enqueue_refresh(self, queue):
        self.calls.append(('enqueue_refresh', queue))
        return {'status': 'queued', 'jobs': [{'job_id': 'refresh-job', 'position': 1}]}

    def promote_refresh(self, _app, *, database_scope=None):
        self.calls.append(('promote_refresh', database_scope))
        return SimpleNamespace(id='refresh-job')

    def force_refresh(self, queue, _app, *, database_scope=None):
        self.calls.append(('force_refresh', queue, database_scope))

    def start_delete(self, library, app, *, database_scope=None):
        self.calls.append(('delete', library.uuid, callable(database_scope)))
        return 'delete-job'

    def log_event(self, message, *, level, user):
        self.calls.append(('event', level))


@pytest.fixture
def native_client():
    flask_app = Flask('native-library-admin-tests')
    flask_app.config.update(
        SECRET_KEY='library-admin-secret', SESSION_PROTECTION='none',
        WTF_CSRF_ENABLED=True, WTF_CSRF_SECRET_KEY='library-admin-secret',
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    users = {
        7: SimpleNamespace(id=7, name='Admin', role='admin', state=True, is_active=True),
        8: SimpleNamespace(id=8, name='Member', role='user', state=True, is_active=True),
    }
    data = FakeLibraryAdminMutations()
    database_scope = lambda _app: nullcontext()
    runtime = FastAPI()
    runtime.include_router(create_library_admin_mutations_router(
        flask_app, find_user=lambda user_id: users.get(user_id), find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: users.get(int(user_id.split(':', 1)[0]))
        if user_id in ('7:fp', '8:fp') else None,
        login_manager=SimpleNamespace(login_view='/login'),
        data_access=data,
        database_scope=database_scope,
    ))
    return runtime, data


def _session_cookie(user_id=7):
    session = {'_user_id': f'{user_id}:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'library-admin-secret')
    return dump_session_cookie(session, 'library-admin-secret'), csrf


def _request(runtime, method, path, *, json=None, headers=None, cookie=True, csrf_header=True, files=None, data=None, user_id=7):
    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime), base_url='http://testserver') as client:
            request_headers = dict(headers or {})
            form_data = data
            if cookie:
                session, csrf = _session_cookie(user_id)
                request_headers['Cookie'] = f'session={session}'
                if csrf_header:
                    request_headers['X-CSRFToken'] = csrf
                if isinstance(form_data, dict) and form_data.get('csrf_token') == '__csrf__':
                    form_data = {**form_data, 'csrf_token': csrf}
            return await client.request(method, path, json=json, headers=request_headers, files=files, data=form_data)
    return asyncio.run(send())


def test_csrf_precedes_auth_and_create_validates_then_uses_fake(native_client):
    runtime, data = native_client
    refused = _request(runtime, 'POST', '/api/admin/libraries', json={'name': 'x'}, cookie=False)
    assert refused.status_code == 400
    assert data.calls == []

    invalid = _request(runtime, 'POST', '/api/admin/libraries', json={'name': 'x', 'platform': 'unknown'})
    assert invalid.status_code == 400
    assert data.calls == []

    created = _request(runtime, 'POST', '/api/admin/libraries', json={
        'name': ' New Library ', 'platform': 'PCWIN', 'scan_depth': 2, 'watch_enabled': 'off',
    })
    assert created.status_code == 200
    assert created.json()['library_uuid'] == 'new-lib'
    assert data.calls[0][0] == 'create'
    assert data.calls[0][1]['name'] == 'New Library'
    assert data.calls[0][1]['scan_depth'] == 2
    assert data.calls[0][1]['watch_enabled'] is False


def test_unauthenticated_library_api_returns_json_401_after_valid_csrf(native_client):
    runtime, data = native_client
    session = {}
    csrf = generate_csrf_token(session, 'library-admin-secret')
    session_cookie = dump_session_cookie(session, 'library-admin-secret')
    response = _request(
        runtime, 'PUT', '/api/admin/libraries/lib-1', cookie=False,
        headers={'Cookie': f'session={session_cookie}', 'X-CSRFToken': csrf},
        data={
            'csrf_token': csrf, 'name': 'Must not update', 'platform': 'PCWIN',
            'scan_depth': '1', 'watch_enabled': 'default',
        },
    )

    assert response.status_code == 401
    assert response.json()['error_code'] == 'unauthorized'
    assert not any(call[0] == 'update' for call in data.calls)


def test_legacy_library_create_form_uses_hidden_csrf_and_redirects(native_client):
    runtime, data = native_client
    rejected = _request(
        runtime, 'POST', '/admin/library/add',
        data={'name': 'Library', 'platform': 'PCWIN', 'scan_depth': '1'},
        csrf_header=False,
    )
    accepted = _request(
        runtime, 'POST', '/admin/library/add',
        data={'csrf_token': '__csrf__', 'name': 'Library', 'platform': 'PCWIN',
              'scan_depth': '1', 'watch_enabled': 'default'},
        csrf_header=False,
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 302
    assert accepted.headers['location'] == '/libraries'
    expected = flask_redirect('/libraries', code=302)
    assert accepted.headers['content-type'] == expected.headers['Content-Type']
    assert accepted.content == expected.get_data()
    assert [call[0] for call in data.calls] == ['create']


@pytest.mark.parametrize(
    ('form', 'message'),
    [
        ({'platform': 'PCWIN', 'scan_depth': '1', 'watch_enabled': 'default'},
         'Please correct the errors below.'),
        ({'name': 'Library', 'platform': 'NOT_A_PLATFORM', 'scan_depth': '1',
          'watch_enabled': 'default'}, 'Please correct the errors below.'),
        ({'name': 'Library', 'platform': 'PCWIN', 'scan_depth': '9',
          'watch_enabled': 'default'}, 'Please correct the errors below.'),
        ({'name': 'Library', 'platform': 'PCWIN', 'scan_depth': '1',
          'watch_enabled': 'invalid'}, 'Please correct the errors below.'),
        ({'name': 'Library', 'platform': 'PCWIN', 'scan_depth': '1',
          'watch_enabled': 'false'}, 'Please correct the errors below.'),
    ],
)
def test_legacy_library_invalid_create_form_renders_matching_error_page(native_client, form, message):
    runtime, data = native_client
    response = _request(
        runtime, 'POST', '/admin/library/add',
        data={'csrf_token': '__csrf__', **form},
        csrf_header=False,
    )

    assert response.status_code == 200
    assert 'id="admin-app-root"' in response.text
    assert message in response.text
    assert data.calls == []


def test_legacy_library_edit_missing_record_matches_not_found(native_client):
    runtime, data = native_client
    response = _request(
        runtime, 'POST', '/admin/library/edit/not-present',
        data={'csrf_token': '__csrf__', 'name': 'Updated library',
              'platform': 'PCWIN', 'scan_depth': '2', 'watch_enabled': 'off'},
        csrf_header=False,
    )

    assert response.status_code == 404
    assert response.headers['content-type'].startswith('text/html')
    assert response.text == (
        '<!doctype html>\n<html lang=en>\n'
        '<title>404 Not Found</title>\n'
        '<h1>Not Found</h1>\n'
        '<p>The requested URL was not found on the server. If you entered the URL manually '
        'please check your spelling and try again.</p>\n'
    )
    assert data.calls == []


def test_legacy_library_create_matches_legacy_server_error_for_corrupt_image(native_client):
    runtime, data = native_client
    response = _request(
        runtime, 'POST', '/admin/library/add',
        data={'csrf_token': '__csrf__', 'name': 'Library', 'platform': 'PCWIN',
              'scan_depth': '1', 'watch_enabled': 'default'},
        files={'image': ('broken.png', b'not an image', 'image/png')},
        csrf_header=False,
    )

    assert response.status_code == 500
    assert 'Please correct the errors below.' in response.text
    assert data.calls == []


def test_legacy_library_edit_form_preserves_hidden_csrf_and_updates_adapter(native_client):
    runtime, data = native_client
    response = _request(
        runtime, 'POST', '/admin/library/edit/lib-1',
        data={'csrf_token': '__csrf__', 'name': 'Updated library',
              'platform': 'PCWIN', 'scan_depth': '2', 'watch_enabled': 'off'},
        csrf_header=False,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/libraries'
    expected = flask_redirect('/libraries', code=302)
    assert response.headers['content-type'] == expected.headers['Content-Type']
    assert response.content == expected.get_data()
    assert data.calls[0][0] == 'update'
    assert data.calls[0][1] == 'lib-1'


def test_batch_scan_keeps_aliases_queue_result_and_partial_rows(native_client):
    runtime, data = native_client
    response = _request(runtime, 'POST', '/api/admin/libraries/batch/scan', json={
        'uuids': ['lib-1', 'missing'], 'remove_missing': 'yes', 'download_missing_images': True,
        'force_updates_extras': 1,
    })
    assert response.status_code == 200
    body = response.json()
    assert (body['started'], body['queued'], body['failed'], body['count']) == (0, 1, 1, 2)
    assert body['results'][0]['job_id'] == 'scan-job'
    scan = next(call for call in data.calls if call[0] == 'scan')
    assert scan[2] == '/safe/root/one'
    assert scan[3]['remove_missing'] is True
    assert scan[3]['download_missing_images'] is True


def test_single_scan_resolves_location_and_preserves_scan_options(native_client):
    runtime, data = native_client
    response = _request(runtime, 'POST', '/api/admin/libraries/scan', json={
        'library_uuid': 'lib-1', 'folder': '/safe/root/one',
        'scan_mode': 'auto', 'remove_missing': True,
        'download_missing_images': 'yes', 'force_updates_extras': 1,
        'fetch_hltb': True, 'force_hltb_refetch': False,
    })

    assert response.status_code == 200
    assert response.json()['status'] == 'queued'
    scan = next(call for call in data.calls if call[0] == 'scan')
    assert scan[2] == '/safe/root/one'
    assert scan[3]['scan_mode'] == 'files'
    assert scan[3]['remove_missing'] is True
    assert scan[3]['download_missing_images'] is True
    assert scan[3]['force_updates_extras'] is True
    assert scan[3]['fetch_hltb'] is True


def test_single_scan_stringifies_legacy_scalar_folder_without_weakening_root_allowlist(native_client):
    runtime, data = native_client
    response = _request(runtime, 'POST', '/api/admin/libraries/scan', json={
        'library_uuid': 'lib-1', 'folder': 123,
    })

    assert response.status_code == 200
    assert response.json()['status'] == 'queued'
    scan = next(call for call in data.calls if call[0] == 'scan')
    assert scan[2] == '/safe/root/123'


def test_single_scan_unknown_mode_preserves_legacy_accepted_then_failed_contract(native_client):
    runtime, data = native_client
    response = _request(runtime, 'POST', '/api/admin/libraries/scan', json={
        'library_uuid': 'lib-1', 'folder': '/safe/root/one', 'scan_mode': 'unknown',
    })

    assert response.status_code == 200
    assert response.json()['status'] == 'started'
    assert response.json()['position'] is None
    assert response.json()['job_id'] == 'failed-scan-job'
    assert any(call[0] == 'fail_scan_mode' for call in data.calls)
    assert not any(call[0] == 'scan' for call in data.calls)


@pytest.mark.parametrize('interval_unit', [' hours ', 'HOURS', 'Minutes'])
def test_single_scan_rejects_non_choice_interval_unit(native_client, interval_unit):
    runtime, data = native_client
    response = _request(runtime, 'POST', '/api/admin/libraries/scan', json={
        'library_uuid': 'lib-1', 'folder': '/safe/root/one', 'schedule': 'interval',
        'schedule_interval_value': 15, 'schedule_interval_unit': interval_unit,
    })

    assert response.status_code == 400
    assert response.json()['error'] == 'Not a valid choice.'
    assert not any(call[0] == 'scan' for call in data.calls)


def test_single_scan_rejects_padded_schedule_choice(native_client):
    runtime, data = native_client
    response = _request(runtime, 'POST', '/api/admin/libraries/scan', json={
        'library_uuid': 'lib-1', 'folder': '/safe/root/one',
        'schedule': ' interval ', 'schedule_interval_value': 15,
        'schedule_interval_unit': 'minutes',
    })

    assert response.status_code == 400
    assert response.json()['error'] == 'Not a valid choice.'
    assert not any(call[0] == 'scan' for call in data.calls)


def test_single_scan_uses_legacy_six_hour_default_when_interval_is_omitted(native_client):
    runtime, data = native_client
    response = _request(runtime, 'POST', '/api/admin/libraries/scan', json={
        'library_uuid': 'lib-1', 'folder': '/safe/root/one', 'schedule': 'interval',
    })

    assert response.status_code == 200
    scan = next(call for call in data.calls if call[0] == 'scan')
    assert scan[3]['schedule_fields']['schedule_interval_minutes'] == 360


def test_single_scan_missing_folder_matches_legacy_rejection(native_client):
    runtime, data = native_client
    data.items['lib-no-folder'] = SimpleNamespace(
        uuid='lib-no-folder', name='Library Without Folder', last_scan_folder=None,
    )

    response = _request(
        runtime, 'POST', '/api/admin/libraries/scan',
        json={'library_uuid': 'lib-no-folder'},
    )

    assert response.status_code == 400
    assert response.json()['error'] == (
        'No folder provided and library has no last_scan_folder. '
        'Run one Auto Scan first or pass folder.'
    )
    assert not any(call[0] in {'resolve', 'scan'} for call in data.calls)


def test_refresh_all_enqueues_and_promotes_fifo_job(native_client):
    runtime, data = native_client
    response = _request(runtime, 'POST', '/api/admin/libraries/refresh_all', json={})

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'started'
    assert body['job_id'] == 'refresh-job'
    assert body['jobs'][0]['status'] == 'started'
    assert body['jobs'][0]['position'] is None
    promote_call = next(call for call in data.calls if call[0] == 'promote_refresh')
    assert callable(promote_call[1])
    assert [call[0] for call in data.calls if call[0] in ('refresh_busy', 'enqueue_refresh')] == [
        'refresh_busy', 'enqueue_refresh',
    ]


def test_force_refresh_passes_native_database_scope_to_worker(native_client):
    runtime, data = native_client
    response = _request(
        runtime, 'POST', '/api/admin/libraries/refresh_all?force_parallel=true', json={},
    )

    assert response.status_code == 200
    force_call = next(call for call in data.calls if call[0] == 'force_refresh')
    assert force_call[1] == [{'uuid': 'lib-1', 'name': 'Library One', 'folder': '/safe/root/one'}]
    assert callable(force_call[2])


def test_force_refresh_opens_native_scope_around_scan_worker(monkeypatch):
    from contextlib import contextmanager
    import threading
    import oneirodex.utils.services.scan_orchestration as scan_orchestration

    class NativeApp:
        config = {}

        @staticmethod
        def app_context():
            raise AssertionError('native force-refresh must not push Flask app context')

    app = NativeApp()
    scope_events = []
    scan_calls = []

    @contextmanager
    def database_scope(_app):
        scope_events.append('enter')
        try:
            yield
        finally:
            scope_events.append('exit')

    class ImmediateThread:
        def __init__(self, *, target, daemon, name):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(
        scan_orchestration, 'scan_and_add_games',
        lambda *args, **kwargs: scan_calls.append((args, kwargs, tuple(scope_events))),
    )

    LibraryAdminMutationData().force_refresh(
        [{'folder': '/library', 'uuid': 'lib-1', 'name': 'Library'}], app,
        database_scope=database_scope,
    )

    assert scope_events == ['enter', 'exit']
    assert scan_calls[0][2] == ('enter',)
    assert scan_calls[0][1]['database_scope'] is database_scope
    assert scan_calls[0][1]['app'] is app


def test_single_library_update_preserves_json_and_bounded_image_form(native_client):
    runtime, data = native_client
    image = BytesIO()
    Image.new('RGB', (2, 2), color='green').save(image, format='PNG')
    updated = _request(runtime, 'PUT', '/api/admin/libraries/lib-1', json={
        'name': 'Renamed library', 'platform': 'PCWIN', 'scan_depth': 2,
        'watch_enabled': 'off',
    })
    multipart = _request(
        runtime, 'PUT', '/api/admin/libraries/lib-1',
        files={'image': ('library.png', image.getvalue())},
        data={'name': 'Image library', 'platform': 'PCWIN', 'scan_depth': '1'},
    )

    assert updated.status_code == 200
    assert updated.json()['name'] == 'Renamed library'
    assert multipart.status_code == 200
    update_call = next(call for call in data.calls if call[0] == 'update')
    assert update_call[1] == 'lib-1'
    assert update_call[2]['watch_enabled'] is False
    image_call = [call for call in data.calls if call[0] == 'update'][1]
    assert image_call[2]['image'][0] == 'library.png'
    assert len(image_call[2]['image'][1]) == len(image.getvalue())


def test_batch_delete_requires_exact_confirmation_and_schedules_only_fake(native_client):
    runtime, data = native_client
    refused = _request(runtime, 'POST', '/api/admin/libraries/batch/delete', json={'uuids': ['lib-1']})
    assert refused.status_code == 400
    assert refused.json()['error'] == 'confirm_name_required'
    assert not any(call[0] == 'delete' for call in data.calls)

    mismatch = _request(runtime, 'POST', '/api/admin/libraries/batch/delete', json={
        'uuids': ['lib-1'], 'confirm_names': {'lib-1': 'wrong'},
    })
    assert mismatch.status_code == 400
    assert mismatch.json()['results'][0]['error'] == 'confirm_name_mismatch'
    assert not any(call[0] == 'delete' for call in data.calls)

    accepted = _request(runtime, 'POST', '/api/admin/libraries/batch/delete', json={
        'uuids': ['lib-1'], 'confirm_name': 'Library One',
    })
    assert accepted.status_code == 200
    assert accepted.json()['results'][0]['job_id'] == 'delete-job'
    assert ('delete', 'lib-1', True) in data.calls


def test_single_library_delete_preserves_legacy_confirmation_and_form_csrf(native_client):
    runtime, data = native_client
    missing_csrf = _request(
        runtime, 'POST', '/delete_full_library/lib-1',
        data={'csrf_token': 'wrong'}, csrf_header=False,
    )
    assert missing_csrf.status_code == 400
    assert not any(call[0] == 'delete' for call in data.calls)
    # Existing classic clients rely on client-side typed confirmation and omit
    # the optional server-side force/confirm fields.
    accepted = _request(
        runtime, 'POST', '/delete_full_library/lib-1',
        data={'csrf_token': '__csrf__'}, csrf_header=False,
    )
    assert accepted.status_code == 200
    assert accepted.json()['status'] == 'started'
    assert ('delete', 'lib-1', True) in data.calls


def test_single_library_delete_form_csrf_failure_matches_legacy_html(native_client):
    runtime, data = native_client
    response = _request(
        runtime, 'POST', '/delete_full_library/lib-1',
        data={}, csrf_header=False,
    )

    assert response.status_code == 400
    assert response.headers['content-type'].startswith('text/html')
    assert data.calls == []


def test_single_library_delete_form_member_denial_redirects_to_login(native_client):
    runtime, data = native_client
    response = _request(
        runtime, 'POST', '/delete_full_library/lib-1',
        data={'csrf_token': '__csrf__'}, csrf_header=False, user_id=8,
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    assert data.calls == []


def test_single_library_delete_validates_explicit_confirmation(native_client):
    runtime, data = native_client
    mismatch = _request(
        runtime, 'POST', '/delete_full_library/lib-1',
        data={'confirm_name': 'wrong'},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()['error'] == 'confirm_name_mismatch'
    assert not any(call[0] == 'delete' for call in data.calls)

    accepted = _request(
        runtime, 'POST', '/delete_full_library/lib-1',
        data={'confirm_name': 'Library One'},
    )
    assert accepted.status_code == 200
    assert ('delete', 'lib-1', True) in data.calls


def test_native_background_worker_uses_explicit_database_scope(monkeypatch):
    from contextlib import contextmanager
    import threading

    from oneirodex.utils.background import run_in_background

    class NativeApp:
        config = {}

        @staticmethod
        def app_context():
            raise AssertionError('native worker must not push Flask app context')

    events = []

    @contextmanager
    def database_scope(_app):
        events.append('enter')
        try:
            yield
        finally:
            events.append('exit')

    class ImmediateThread:
        def __init__(self, *, target, daemon, name):
            self.target = target
            self.name = name

        def start(self):
            self.target()

    monkeypatch.setattr(threading, 'Thread', ImmediateThread)
    thread = run_in_background(
        NativeApp(), lambda: events.append('work'),
        name='native-delete-test', database_scope=database_scope,
    )

    assert thread.name == 'native-delete-test'
    assert events == ['enter', 'work', 'exit']


def test_non_admin_rejected_and_no_adapter_calls(native_client):
    runtime, data = native_client
    # Remove the valid session, then send a valid member session under the same signature.
    from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
    member = SimpleNamespace(id=9, name='Member', role='user', state=True, is_active=True)
    # A second independently mounted app keeps this setup local and fake-only.
    other = Flask('native-library-member-tests')
    other.config.update(SECRET_KEY='member-secret', SESSION_PROTECTION='none',
                        WTF_CSRF_ENABLED=True, WTF_CSRF_SECRET_KEY='member-secret')
    member_runtime = FastAPI()
    member_runtime.include_router(create_library_admin_mutations_router(
        other, find_user=lambda _id: member, find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda user_id: member if user_id == '9:fp' else None,
        data_access=data,
    ))
    session = {'_user_id': '9:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'member-secret')
    response = _request(member_runtime, 'POST', '/api/admin/libraries/batch/delete',
                        json={'uuids': ['lib-1'], 'force': True}, cookie=False,
                        headers={'Cookie': f"session={dump_session_cookie(session, 'member-secret')}",
                                 'X-CSRFToken': csrf})
    assert response.status_code == 403
    assert data.calls == []
