from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.legacy_scan_forms import create_legacy_scan_form_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeScanFormData:
    def __init__(self):
        self.calls = []

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


def test_legacy_scan_manual_form_checks_hidden_csrf_and_persists_scan_projection():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='legacy-scan-secret', WTF_CSRF_ENABLED=True,
        SESSION_PROTECTION='none',
    )
    user = SimpleNamespace(
        id=7, name='Admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fp',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Login required',
        login_message_category='message', localize_callback=None, session_protection='none',
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    session = {'_user_id': '7:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'legacy-scan-secret')
    data = FakeScanFormData()
    app = FastAPI()
    app.include_router(create_legacy_scan_form_router(
        flask_app, find_user=lambda uid: user if uid == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value == '7:fp' else None,
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

    assert rejected.status_code == 400
    assert accepted.status_code == 302
    assert accepted.headers['location'] == '/admin/scan_management?active_tab=manualScan'
    assert ('list', '/safe/ROMs', ['ignored'], ['CaseSensitive']) in data.calls
    assert 'session=' in accepted.headers.get('set-cookie', '')
