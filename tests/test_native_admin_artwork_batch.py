from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.admin_artwork_batch import create_admin_artwork_batch_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


class FakeArtworkBatch:
    def __init__(self, enabled):
        self.is_enabled = enabled
        self.calls = []

    def enabled(self, _config):
        return self.is_enabled

    def generate(self, app, body):
        self.calls.append(body)
        return {'considered': 2, 'generated': 1, 'skipped': 1, 'failed': 0, 'games': [], 'errors': []}


def _client(*, enabled):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-artwork-batch', CSP_ENABLED=False, WTF_CSRF_ENABLED=True,
    )
    user = SimpleNamespace(
        id=13, user_id='admin', role='admin', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    session = {'_user_id': '13:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    data = FakeArtworkBatch(enabled)
    app = FastAPI()
    app.include_router(create_admin_artwork_batch_router(
        flask_app, find_user=lambda uid: user if uid == 13 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '13' else None,
        login_manager=manager, database_scope=lambda _app: nullcontext(),
        data_access=data,
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))
    client.headers['X-CSRFToken'] = csrf
    return client, data


def test_batch_artwork_generation_is_gated_before_any_provider_work():
    client, data = _client(enabled=False)
    response = client.post('/admin/api/artwork/generate/batch', json={'limit': 5})
    assert response.status_code == 403
    assert data.calls == []


def test_batch_artwork_generation_uses_fake_provider_adapter_when_enabled():
    client, data = _client(enabled=True)
    response = client.post('/admin/api/artwork/generate/batch', json={
        'limit': 5, 'library_uuid': 'lib-1',
    })
    assert response.status_code == 200 and response.json()['ok'] is True
    assert response.json()['generated'] == 1
    assert data.calls == [{'limit': 5, 'library_uuid': 'lib-1'}]
