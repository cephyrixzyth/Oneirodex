from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_cover_apply import create_admin_cover_apply_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeCoverApply:
    def __init__(self):
        self.calls = []

    def path_status(self, _config):
        return {'path': '/images', 'writable': True}

    def apply(self, app, game_uuid, url, provider_id):
        self.calls.append((game_uuid, url, provider_id))
        return {'game_uuid': game_uuid, 'image_id': 3, 'url': '/static/cover.png'}


def _client():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-cover-apply', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
    )
    user = SimpleNamespace(
        id=8, user_id='admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '8:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    service = FakeCoverApply()
    app = FastAPI()
    app.include_router(create_admin_cover_apply_router(
        flask_app, find_user=lambda uid: user if uid == 8 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '8' else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
        data_access=service,
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, service


def test_cover_apply_preserves_result_and_provider_normalization():
    client, service = _client()
    response = client.post('/admin/api/covers/apply', json={
        'game_uuid': 'game-7', 'url': 'https://provider.example/cover.png', 'provider': 'IGDB',
    })
    assert response.status_code == 200
    assert response.json()['image_save_path']['writable'] is True
    assert service.calls == [('game-7', 'https://provider.example/cover.png', 'igdb')]


def test_cover_apply_requires_body_validation_and_csrf():
    client, service = _client()
    invalid = client.post('/admin/api/covers/apply', json={})
    no_csrf = client.post(
        '/admin/api/covers/apply', json={'game_uuid': 'g', 'url': 'https://x/a.png'},
        headers={'X-CSRFToken': ''},
    )
    assert invalid.status_code == 422
    assert no_csrf.status_code == 400
    assert service.calls == []
