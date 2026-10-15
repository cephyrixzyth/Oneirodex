"""DB-free auth, CSRF, and write-contract checks for Attract Mode routes."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from flask import Flask

from oneirodex.runtime_native.attract_mode_reads import mount_attract_mode_routes
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class Data:
    def __init__(self):
        self.saved = []
        self.rollbacks = 0

    def payload(self, user):
        return {'enabled': True, 'idle_timeout': 60, 'settings': {'user': getattr(user, 'id', None)}}

    def save_override(self, user, payload):
        self.saved.append((user.id, payload))

    def rollback(self):
        self.rollbacks += 1


def setup():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-attract-route-test',
        WTF_CSRF_ENABLED=True,
        SESSION_COOKIE_NAME='session',
        WTF_CSRF_TIME_LIMIT=3600,
    )
    user = SimpleNamespace(
        id=3, user_id='user-guid', name='Member', role='user', state=True,
        is_active=True, session_fingerprint=lambda: 'fingerprint',
    )
    data = Data()
    lookups = []
    native = FastAPI()
    mount_attract_mode_routes(
        native,
        flask_app,
        find_user=lambda user_id: lookups.append(user_id) or (user if user_id == 3 else None),
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        login_manager=SimpleNamespace(login_view='/login', session_protection='basic'),
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    return flask_app, native, user, data, lookups


def request(app, method, path, **kwargs):
    cookies = kwargs.pop('cookies', None)
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://localhost',
            cookies=cookies,
        ) as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


def test_public_read_is_bare_json_and_head_has_matching_length():
    flask_app, native, _user, _data, _lookups = setup()

    get_response = request(native, 'GET', '/api/attract-mode/settings')
    head_response = request(native, 'HEAD', '/api/attract-mode/settings')

    assert get_response.status_code == 200
    assert get_response.json() == {
        'enabled': True, 'idle_timeout': 60, 'settings': {'user': None},
    }
    assert get_response.headers['x-content-type-options'] == 'nosniff'
    assert head_response.status_code == 200
    assert head_response.content == b''
    assert head_response.headers['content-length'] == str(len(get_response.content))


def test_write_rejects_missing_csrf_before_resolving_auth():
    _flask_app, native, _user, data, lookups = setup()

    response = request(
        native, 'POST', '/api/attract-mode/user-override',
        json={'filters': {'genres': [1]}},
    )

    assert response.status_code == 400
    assert response.json()['error_code'] == 'bad_request'
    assert lookups == []
    assert data.saved == []


def test_signed_session_csrf_write_persists_override_through_adapter():
    flask_app, native, _user, data, _lookups = setup()
    session_data = {'_user_id': '3:fingerprint', '_fresh': True}
    csrf_token = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    session_cookie = dump_session_cookie(session_data, flask_app.config['SECRET_KEY'])
    payload = {'filters': {'genres': [1, 4]}, 'autoplay': {'enabled': False}}

    response = request(
        native, 'POST', '/api/attract-mode/user-override',
        json=payload,
        headers={'X-CSRFToken': csrf_token},
        cookies={'session': session_cookie},
    )

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['message'] == 'Your attract mode preferences have been saved'
    assert data.saved == [(3, payload)]
    assert data.rollbacks == 0
