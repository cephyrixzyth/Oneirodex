from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager

from oneirodex.runtime_native.announcements import create_announcements_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class _AnnouncementData:
    def __init__(self):
        self.created = []

    def create(self, **values):
        self.created.append(values)
        return {'id': len(self.created), **values}


def _runtime():
    flask_app = Flask('announcements-body-limit-test')
    flask_app.config.update(
        SECRET_KEY='announcements-body-limit-test-secret',
        SESSION_PROTECTION='none', SECURITY_HEADERS_ENABLED=True,
        WTF_CSRF_ENABLED=False,
    )
    user = SimpleNamespace(
        id=42, role='admin', state=True, is_active=True, is_authenticated=True,
        session_fingerprint=lambda: 'fp',
    )
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda identity: user if identity == '42:fp' else None)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    data = _AnnouncementData()
    app = FastAPI()
    app.include_router(create_announcements_router(
        flask_app,
        find_user=lambda user_id: user if user_id == user.id else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda identity: manager.user_callback(identity),
        login_manager=manager, data_access=data,
    ))
    cookie = dump_session_cookie(
        {'_user_id': '42:fp', '_fresh': True},
        'announcements-body-limit-test-secret',
    )
    return app, data, cookie


def _post(app, cookie, payload):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post('/api/announcements', json=payload)

    return asyncio.run(perform())


def test_announcement_write_body_limit_and_success_contract():
    app, data, cookie = _runtime()

    created = _post(app, cookie, {'title': 'Notice', 'body': 'Hello'})
    oversized = _post(
        app, cookie,
        {'title': '', 'body': 'x' * (128 * 1024)},
    )

    assert created.status_code == 201
    assert created.json()['title'] == 'Notice'
    assert oversized.status_code == 413
    assert oversized.json()['error_code'] == 'payload_too_large'
    assert len(data.created) == 1
