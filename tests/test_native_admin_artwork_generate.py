from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_artwork_generate import (
    create_admin_artwork_generation_router,
)
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeArtworkGeneration:
    def __init__(self, enabled):
        self.is_enabled = enabled
        self.calls = []

    def enabled(self, _config):
        return self.is_enabled

    def generate(self, game_uuid, image_type, config=None):
        del config
        self.calls.append((game_uuid, image_type))
        return {'game_uuid': game_uuid, 'image_type': image_type, 'url': '/static/generated.webp'}


def _client(*, enabled):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-artwork-generate', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
    )
    user = SimpleNamespace(
        id=31, user_id='admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '31:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    service = FakeArtworkGeneration(enabled)
    app = FastAPI()
    app.include_router(create_admin_artwork_generation_router(
        flask_app, find_user=lambda uid: user if uid == 31 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '31' else None,
        login_manager=manager, data_access=service,
        database_scope=lambda _app: nullcontext(),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, service


def test_artwork_generation_validates_body_then_respects_disabled_feature_gate():
    client, service = _client(enabled=False)
    invalid = client.post('/admin/api/artwork/generate', json={})
    disabled = client.post('/admin/api/artwork/generate', json={'game_uuid': 'game-1'})
    assert invalid.status_code == 422 and 'game_uuid' in invalid.json()['detail']
    assert disabled.status_code == 403
    assert service.calls == []


def test_artwork_generation_uses_fake_adapter_when_enabled():
    client, service = _client(enabled=True)
    response = client.post('/admin/api/artwork/generate', json={
        'game_uuid': 'game-2', 'image_type': 'fanart',
    })
    assert response.status_code == 200
    assert response.json()['image_type'] == 'fanart'
    assert service.calls == [('game-2', 'fanart')]
