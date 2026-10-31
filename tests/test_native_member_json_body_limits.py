"""Request size limits for small native member JSON actions."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native import member_meta, playtime, social_writes, wishlist
from oneirodex.runtime_native.session_compat import dump_session_cookie


class Data:
    def __init__(self):
        self.calls = []

    def create(self, *args, **kwargs):
        self.calls.append(('wishlist', args, kwargs))

    def start(self, *args, **kwargs):
        self.calls.append(('playtime', args, kwargs))

    def request(self, *args, **kwargs):
        self.calls.append(('social', args, kwargs))

    def username_exists(self, *args, **kwargs):
        self.calls.append(('username', args, kwargs))
        return False


def setup_client():
    secret = 'member-json-body-limit-test'
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=secret,
        WTF_CSRF_ENABLED=False,
        SESSION_COOKIE_NAME='session',
    )
    user = SimpleNamespace(
        id=7, role='user', is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fp',
    )
    manager = SimpleNamespace(login_view='/login', session_protection='basic')
    data = Data()
    common = dict(
        find_user=lambda user_id: user if user_id == 7 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '7' else None,
        login_manager=manager,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(wishlist.create_wishlist_router(flask_app, data_access=data, **common))
    app.include_router(playtime.create_playtime_router(flask_app, data_access=data, **common))
    app.include_router(social_writes.create_social_writes_router(flask_app, data_access=data, **common))
    app.include_router(member_meta.create_member_meta_router(flask_app, data_access=data, **common))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie({'_user_id': '7:fp'}, secret))
    return client, data


def assert_payload_too_large(response):
    assert response.status_code == 413
    assert response.json()['error_code'] == 'payload_too_large'


def test_wishlist_create_rejects_oversized_json_before_data_write(monkeypatch):
    monkeypatch.setattr(wishlist, '_MAX_JSON_BODY_BYTES', 8)
    client, data = setup_client()

    response = client.post('/api/requests', content=b'{"title":"too long"}', headers={'content-type': 'application/json'})

    assert_payload_too_large(response)
    assert data.calls == []


def test_playtime_start_rejects_oversized_json_before_data_write(monkeypatch):
    monkeypatch.setattr(playtime, '_MAX_JSON_BODY_BYTES', 8)
    client, data = setup_client()

    response = client.post('/api/playtime/sessions', content=b'{"game_uuid":"too long"}', headers={'content-type': 'application/json'})

    assert_payload_too_large(response)
    assert data.calls == []


def test_playtime_start_non_object_json_preserves_root_validation_error():
    client, data = setup_client()

    response = client.post(
        '/api/playtime/sessions',
        content=b'[]',
        headers={'content-type': 'application/json'},
    )

    assert response.status_code == 422
    body = response.json()
    assert body['error_code'] == 'unprocessable'
    assert '__root__' in body['detail']
    assert data.calls == []


def test_social_friend_request_rejects_oversized_json_before_data_write(monkeypatch):
    monkeypatch.setattr(social_writes, '_MAX_JSON_BODY_BYTES', 8)
    client, data = setup_client()

    response = client.post('/api/social/friends', content=b'{"user_id":123}', headers={'content-type': 'application/json'})

    assert_payload_too_large(response)
    assert data.calls == []


def test_username_check_rejects_oversized_json_before_lookup(monkeypatch):
    monkeypatch.setattr(member_meta, '_MAX_JSON_BODY_BYTES', 8)
    client, data = setup_client()

    response = client.post('/api/check_username', content=b'{"username":"too long"}', headers={'content-type': 'application/json'})

    assert_payload_too_large(response)
    assert data.calls == []
