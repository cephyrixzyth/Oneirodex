from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_theme_fonts import create_admin_theme_font_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeFontStore:
    def __init__(self):
        self.calls = []

    def store(self, file_storage, **kwargs):
        self.calls.append(('store', file_storage.filename, file_storage.stream.read(), kwargs))
        return {'id': 'test-face', 'filename': file_storage.filename, 'size': 4}

    def delete(self, filename, **kwargs):
        self.calls.append(('delete', filename, kwargs))
        return filename == 'custom.ttf'


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-theme-fonts', CSP_ENABLED=False,
        WTF_CSRF_ENABLED=True, FONT_MAX_BYTES=1024,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=12, user_id='operator', role=role, state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    csrf_data = {'_user_id': '12:fingerprint', '_fresh': True}
    token = generate_csrf_token(csrf_data, flask_app.config['SECRET_KEY'])
    store = FakeFontStore()
    router = create_admin_theme_font_router(
        flask_app, find_user=lambda user_id: user if user_id == 12 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '12' else None,
        login_manager=manager, font_store=store,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(csrf_data, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = token
    return client, store


def test_font_upload_uses_csrf_admin_gate_and_shared_storage_contract():
    client, store = _client()
    response = client.post(
        '/admin/api/theme/fonts', files={'file': ('custom.ttf', b'font')},
    )
    assert response.status_code == 201
    assert response.json()['filename'] == 'custom.ttf'
    assert store.calls[0][0:3] == ('store', 'custom.ttf', b'font')


def test_font_mutations_reject_missing_csrf_and_non_admin_user():
    client, store = _client()
    no_csrf = client.post(
        '/admin/api/theme/fonts', files={'file': ('custom.ttf', b'font')},
        headers={'X-CSRFToken': ''},
    )
    denied, _ = _client(role='user')
    forbidden = denied.delete('/admin/api/theme/fonts/custom.ttf')
    assert no_csrf.status_code == 400 and no_csrf.json()['error_code'] == 'bad_request'
    assert forbidden.status_code == 403
    assert store.calls == []


def test_font_delete_preserves_removed_not_found_and_builtin_validation():
    client, store = _client()
    removed = client.delete('/admin/api/theme/fonts/custom.ttf')
    missing = client.delete('/admin/api/theme/fonts/missing.ttf')
    assert removed.status_code == 200 and removed.json()['removed'] == 'custom.ttf'
    assert missing.status_code == 404 and missing.json()['error_code'] == 'not_found'
    assert [call[0] for call in store.calls] == ['delete', 'delete']


def test_font_mutation_paths_are_selected_for_supported_methods():
    from asgi import _is_native_admin_theme_font_path

    assert _is_native_admin_theme_font_path('/admin/api/theme/fonts', 'POST')
    assert _is_native_admin_theme_font_path('/admin/api/theme/fonts/custom.ttf', 'DELETE')
    assert not _is_native_admin_theme_font_path('/admin/api/theme/fonts', 'GET')
