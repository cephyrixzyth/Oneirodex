from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_art_studio_preview import (
    create_admin_art_studio_preview_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakePreview:
    def __init__(self):
        self.kwargs = None

    def render(self, **kwargs):
        self.kwargs = kwargs
        return b'webp-image'


def _client(*, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-art-preview', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
    )
    user = SimpleNamespace(
        id=18, user_id='admin-id', role=role, state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '18:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    preview = FakePreview()
    router = create_admin_art_studio_preview_router(
        flask_app, find_user=lambda uid: user if uid == 18 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '18' else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
        preview_data=preview,
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, preview


def test_preview_preserves_raw_payload_and_clamped_render_options():
    client, preview = _client()
    response = client.post('/admin/api/art-studio/preview', json={
        'title': ' Test Game ', 'system': ' NES ', 'width': 4096,
        'height': 300, 'format': 'invalid', 'artistic': 'false',
    })
    assert response.status_code == 200
    assert response.json() == {
        'preview': 'data:image/webp;base64,d2VicC1pbWFnZQ==',
        'width': 2048, 'height': 300, 'artistic': False, 'variant': 'wide',
    }
    assert preview.kwargs['title'] == 'Test Game'
    assert preview.kwargs['system'] == 'NES'
    assert preview.kwargs['format'] == 'webp'


def test_preview_validates_body_admin_role_and_csrf():
    client, _preview = _client()
    missing = client.post('/admin/api/art-studio/preview', json={})
    no_csrf = client.post(
        '/admin/api/art-studio/preview', json={'title': 'Game'},
        headers={'X-CSRFToken': ''},
    )
    denied, _ = _client(role='user')
    forbidden = denied.post('/admin/api/art-studio/preview', json={'title': 'Game'})
    assert missing.status_code == 422 and 'title' in missing.json()['detail']
    assert no_csrf.status_code == 400 and no_csrf.json()['error_code'] == 'bad_request'
    assert forbidden.status_code == 403
