from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.emulator_health import create_emulator_health_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeEmulatorHealth:
    def read(self, config):
        return {
            'installed_cores': ['snes9x'],
            'pcdos_browser': bool(config.get('ENABLE_PCDOS_BROWSER')),
            'core_checks': {'snes9x': True},
            'deferred_cores': [],
        }


def _client(*, authenticated=True):
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-emulator-health', CSP_ENABLED=False,
        ENABLE_PCDOS_BROWSER=True,
    )
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=4, user_id='member', role='user', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_emulator_health_router(
        flask_app, find_user=lambda user_id: user if user_id == 4 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '4' else None,
        login_manager=manager, data_access=FakeEmulatorHealth(),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie(
                {'_user_id': '4:fingerprint', '_fresh': True}, flask_app.config['SECRET_KEY'],
            ),
        )
    return client


def test_emulator_health_preserves_payload_and_head():
    client = _client()
    response = client.get('/api/emulator/health')
    head = client.head('/api/emulator/health')
    assert response.status_code == 200
    assert response.json() == {
        'installed_cores': ['snes9x'], 'pcdos_browser': True,
        'core_checks': {'snes9x': True}, 'deferred_cores': [],
    }
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_emulator_health_redirects_anonymous_requests_like_flask_login():
    response = _client(authenticated=False).get(
        '/api/emulator/health', follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')
