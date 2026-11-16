from __future__ import annotations

from contextlib import nullcontext
from http.cookies import SimpleCookie
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from tests.fixtures.native_auth import login_identity_for, persistent_login_store

from oneirodex.models import Library
from oneirodex.platform import LibraryPlatform
from oneirodex.runtime_native.legacy_scan_forms import (
    LegacyScanFormData,
    create_legacy_scan_form_router,
)
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie,
    generate_csrf_token,
    load_session_cookie,
)


class FakeScanFormData:
    def __init__(self):
        self.calls = []

    def library_exists(self, library_uuid):
        self.calls.append(('library_exists', library_uuid))
        return library_uuid == 'lib-1'

    def resolve_path(self, app, folder_path, library_root):
        self.calls.append(('resolve', folder_path, library_root))
        return '/safe/ROMs', None

    def allowed_bases(self, app):
        return ['/safe']

    def safe_path(self, path, allowed):
        self.calls.append(('safe', path, allowed))
        return path.startswith('/safe'), 'outside allowed roots'

    def readable_directory(self, path):
        return path == '/safe/ROMs'

    def scan_patterns(self):
        return ['ignored'], ['CaseSensitive']

    def list_games(self, path, insensitive, sensitive):
        self.calls.append(('list', path, insensitive, sensitive))
        return [{'name': 'Example Game', 'full_path': '/safe/ROMs/Example Game'}]


def test_readable_directory_rejects_regular_files(tmp_path):
    folder = tmp_path / 'folder'
    folder.mkdir()
    file_path = tmp_path / 'not-a-folder'
    file_path.write_text('', encoding='utf-8')
    data = LegacyScanFormData()

    assert data.readable_directory(folder)
    assert not data.readable_directory(file_path)
    assert not data.readable_directory(tmp_path / 'missing')


def test_legacy_scan_manual_form_checks_hidden_csrf_and_persists_scan_projection():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='legacy-scan-secret', WTF_CSRF_ENABLED=True,
        SESSION_PROTECTION='none',
    )
    user = SimpleNamespace(
        id=7, name='Admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: '0123456789abcdef',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Login required',
        login_message_category='message', localize_callback=None, session_protection='none',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    session = {'_user_id': login_identity_for(7), '_fresh': True}
    csrf = generate_csrf_token(session, 'legacy-scan-secret')
    data = FakeScanFormData()
    app = FastAPI()
    app.include_router(create_legacy_scan_form_router(
        flask_app, find_user=lambda uid: user if uid == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == str(7) else None,
        login_manager=manager, data_access=data,
        database_scope=lambda _app: nullcontext(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, 'legacy-scan-secret'))

    rejected = client.post('/scan_manual_folder', data={
        'folder_path': '/safe/ROMs', 'library_uuid': 'lib-1',
    }, follow_redirects=False)
    accepted = client.post('/scan_manual_folder', data={
        'csrf_token': csrf, 'folder_path': '/safe/ROMs', 'library_uuid': 'lib-1',
    }, follow_redirects=False)
    preview = client.get('/api/admin/scan/manual-identify/session-preview')

    assert rejected.status_code == 400
    assert rejected.headers['content-type'] == 'text/html; charset=utf-8'
    assert rejected.text == (
        '<!doctype html>\n<html lang=en>\n<title>400 Bad Request</title>\n'
        '<h1>Bad Request</h1>\n<p>The CSRF token is missing.</p>\n'
    )
    assert accepted.status_code == 302
    assert accepted.headers['content-type'] == 'text/html; charset=utf-8'
    assert accepted.headers['location'] == '/scan_management?active_tab=manual'
    assert ('library_exists', 'lib-1') in data.calls
    assert ('list', '/safe/ROMs', ['ignored'], ['CaseSensitive']) in data.calls
    assert 'session=' in accepted.headers.get('set-cookie', '')
    assert preview.status_code == 200
    assert preview.json()['games'] == [
        {'name': 'Example Game', 'full_path': '/safe/ROMs/Example Game'},
    ]
    assert preview.json()['library_uuid'] == 'lib-1'


def test_legacy_scan_manual_form_rejects_unknown_library_before_changing_session_or_scanning():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='legacy-scan-secret', WTF_CSRF_ENABLED=True,
        SESSION_PROTECTION='none',
    )
    user = SimpleNamespace(
        id=7, name='Admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: '0123456789abcdef',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Login required',
        login_message_category='message', localize_callback=None, session_protection='none',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    session = {
        '_user_id': login_identity_for(7), '_fresh': True,
        'game_paths': {'Existing': '/safe/Existing'},
        'selected_library_uuid': 'lib-1', 'active_tab': 'auto',
    }
    csrf = generate_csrf_token(session, 'legacy-scan-secret')
    data = FakeScanFormData()
    app = FastAPI()
    app.include_router(create_legacy_scan_form_router(
        flask_app, find_user=lambda uid: user if uid == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == str(7) else None,
        login_manager=manager, data_access=data,
        database_scope=lambda _app: nullcontext(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, 'legacy-scan-secret'))

    response = client.post('/scan_manual_folder', data={
        'csrf_token': csrf, 'folder_path': '/safe/ROMs', 'library_uuid': 'not-a-library',
    }, follow_redirects=False)
    preview = client.get('/api/admin/scan/manual-identify/session-preview')

    assert response.status_code == 302
    assert response.headers['location'] == '/scan_management?active_tab=manual'
    assert ('library_exists', 'not-a-library') in data.calls
    assert not any(call[0] == 'list' for call in data.calls)
    rejected_session = load_session_cookie(
        SimpleCookie(response.headers['set-cookie'])['session'].value,
        'legacy-scan-secret', max_age=31_536_000,
    )
    assert rejected_session['_flashes'][-1] == ('error', 'Not a valid choice.')
    assert preview.status_code == 200
    assert preview.json()['games'] == [
        {'name': 'Existing', 'full_path': '/safe/Existing'},
    ]
    assert preview.json()['library_uuid'] == 'lib-1'


def test_legacy_scan_manual_form_keeps_csrf_and_admin_gates_before_scan_work(monkeypatch):
    from oneirodex.runtime_native import legacy_scan_forms as native_scan_forms

    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='legacy-scan-secret', WTF_CSRF_ENABLED=True,
        SESSION_PROTECTION='none',
    )
    member = SimpleNamespace(
        id=8, name='Member', role='user', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: '0123456789abcdef',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Login required',
        login_message_category='message', localize_callback=None, session_protection='none',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    data = FakeScanFormData()
    app = FastAPI()
    app.include_router(create_legacy_scan_form_router(
        flask_app,
        find_user=lambda uid: member if uid == 8 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: member if value.split(':', 1)[0] == str(8) else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    ))

    anonymous_session = {}
    csrf = generate_csrf_token(anonymous_session, 'legacy-scan-secret')
    anonymous_client = TestClient(app)
    anonymous_client.cookies.set(
        'session', dump_session_cookie(anonymous_session, 'legacy-scan-secret'),
    )
    missing_csrf = anonymous_client.post('/scan_manual_folder', data={
        'folder_path': '/safe/ROMs', 'library_uuid': 'lib-1',
    }, follow_redirects=False)
    anonymous_client = TestClient(app)
    anonymous_client.cookies.set(
        'session', dump_session_cookie(anonymous_session, 'legacy-scan-secret'),
    )
    anonymous = anonymous_client.post('/scan_manual_folder', data={
        'csrf_token': csrf, 'folder_path': '/safe/ROMs', 'library_uuid': 'lib-1',
    }, follow_redirects=False)

    member_session = {'_user_id': login_identity_for(8), '_fresh': True}
    member_csrf = generate_csrf_token(member_session, 'legacy-scan-secret')
    member_client = TestClient(app)
    member_client.cookies.set(
        'session', dump_session_cookie(member_session, 'legacy-scan-secret'),
    )
    non_admin = member_client.post('/scan_manual_folder', data={
        'csrf_token': member_csrf, 'folder_path': '/safe/ROMs', 'library_uuid': 'lib-1',
    }, follow_redirects=False)

    assert missing_csrf.status_code == 400
    assert missing_csrf.headers['content-type'] == 'text/html; charset=utf-8'
    assert anonymous.status_code == 302
    assert anonymous.headers['location'] == '/login?next=%2Fscan_manual_folder'
    assert non_admin.status_code == 302
    assert non_admin.headers['location'] == '/login'
    member_result = load_session_cookie(
        non_admin.cookies['session'], 'legacy-scan-secret', max_age=31_536_000,
    )
    assert member_result['_flashes'] == [
        ('danger', 'You must be an admin to access this page.'),
    ]
    assert data.calls == []

    token_context = SimpleNamespace(
        user=SimpleNamespace(role='admin', is_authenticated=True),
        token=object(),
        has_scope=lambda scope: scope == 'library:write',
        session_data={},
        should_set_session_cookie=False,
    )
    monkeypatch.setattr(
        native_scan_forms, 'request_auth_context',
        lambda *_args, **_kwargs: token_context,
    )
    token_session = {}
    token_csrf = generate_csrf_token(token_session, 'legacy-scan-secret')
    token_client = TestClient(app)
    token_client.cookies.set(
        'session', dump_session_cookie(token_session, 'legacy-scan-secret'),
    )
    token_denied = token_client.post('/scan_manual_folder', data={
        'csrf_token': token_csrf, 'folder_path': '/safe/ROMs', 'library_uuid': 'lib-1',
    }, follow_redirects=False)
    assert token_denied.status_code == 403
    assert token_denied.json()['error_code'] == 'forbidden'
    assert token_denied.json()['message'] == 'This token does not have the admin scope'
    assert data.calls == []


def test_manual_identify_session_preview_is_admin_only_and_never_caches_paths(monkeypatch):
    from oneirodex.runtime_native import legacy_scan_forms as native_scan_forms

    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='legacy-scan-secret', SESSION_PROTECTION='none',
    )
    admin = SimpleNamespace(
        id=7, name='Admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: '0123456789abcdef',
    )
    member = SimpleNamespace(
        id=8, name='Member', role='user', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: '0123456789abcdef',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Login required',
        login_message_category='message', localize_callback=None, session_protection='none',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    app = FastAPI()
    app.include_router(create_legacy_scan_form_router(
        flask_app,
        find_user=lambda uid: {7: admin, 8: member}.get(uid),
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: {'7': admin, '8': member}.get(value.split(':', 1)[0]),
        login_manager=manager,
        database_scope=lambda _app: nullcontext(),
    ))
    path = '/storage/PrivateCandidate/Example Game'
    admin_session = {
        '_user_id': login_identity_for(7), '_fresh': True,
        'game_paths': {'Example Game': path},
        'selected_library_uuid': 'library-1',
    }
    member_session = {
        '_user_id': login_identity_for(8), '_fresh': True,
        'game_paths': {'Example Game': path},
        'selected_library_uuid': 'library-1',
    }

    admin_client = TestClient(app)
    admin_client.cookies.set(
        'session', dump_session_cookie(admin_session, 'legacy-scan-secret'),
    )
    allowed = admin_client.get('/api/admin/scan/manual-identify/session-preview')
    assert allowed.status_code == 200
    assert allowed.headers['cache-control'] == 'no-store'
    assert allowed.json()['games'] == [{'name': 'Example Game', 'full_path': path}]

    anonymous = TestClient(app).get(
        '/api/admin/scan/manual-identify/session-preview', follow_redirects=False,
    )
    assert anonymous.status_code == 302
    assert path not in anonymous.text

    member_client = TestClient(app)
    member_client.cookies.set(
        'session', dump_session_cookie(member_session, 'legacy-scan-secret'),
    )
    denied_member = member_client.get(
        '/api/admin/scan/manual-identify/session-preview', follow_redirects=False,
    )
    assert denied_member.status_code == 302
    assert denied_member.headers['location'] == '/login'
    assert path not in denied_member.text

    token_context = SimpleNamespace(
        user=admin,
        token=object(),
        has_scope=lambda scope: scope == 'library:read',
        session_data={
            'game_paths': {'Example Game': path},
            'selected_library_uuid': 'library-1',
        },
        should_set_session_cookie=False,
    )
    monkeypatch.setattr(
        native_scan_forms, 'request_auth_context',
        lambda *_args, **_kwargs: token_context,
    )
    denied_token = TestClient(app).get(
        '/api/admin/scan/manual-identify/session-preview',
        headers={'Authorization': 'Bearer synthetic-token'},
    )
    assert denied_token.status_code == 403
    assert denied_token.json()['error_code'] == 'forbidden'
    assert path not in denied_token.text


def test_legacy_scan_library_choice_lookup_uses_persisted_libraries(db_session):
    library = Library(
        uuid='d9a534c1-ea2a-4bc2-a4dd-45f5ad4b22f0',
        name='Manual scan validation fixture',
        platform=LibraryPlatform.NES,
    )
    db_session.add(library)
    db_session.flush()

    data = LegacyScanFormData()

    assert data.library_exists(library.uuid)
    assert not data.library_exists('f3b2ddf1-8ec3-4a33-8ef7-9a51e861d5d9')
