from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask
from flask_login import LoginManager

from oneirodex.routes_apis.layouts import apis_bp
from oneirodex.runtime_native.layouts import create_layout_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token


def _native_layout_client(delete_calls):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='layout-route-parity-secret', CSP_ENABLED=False)
    user = SimpleNamespace(
        id=71, user_id='layout-user', role='user', is_active=True,
        state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    login_manager = SimpleNamespace(
        login_view='login', blueprint_login_views={},
        login_message='Please log in', login_message_category='message',
        localize_callback=None, session_protection='basic',
    )
    router = create_layout_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('71:') else None,
        login_manager=login_manager,
        data_access=SimpleNamespace(
            delete_preset=lambda user_id, preset_id: delete_calls.append((user_id, preset_id)) or False
        ),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session_data = {'_user_id': '71:fingerprint', '_fresh': True}
    client.csrf_token = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    client.cookies.set(
        'session', dump_session_cookie(session_data, flask_app.config['SECRET_KEY'])
    )
    return client


def test_layout_preset_delete_rejects_paths_flask_integer_converter_does_not_match():
    legacy_app = Flask(__name__)
    legacy_app.config['SECRET_KEY'] = 'legacy-layout-route-parity-secret'
    login_manager = LoginManager()
    login_manager.init_app(legacy_app)
    login_manager.login_view = 'login'
    login_manager.user_loader(lambda _user_id: None)
    legacy_app.register_blueprint(apis_bp, url_prefix='/api')

    legacy_client = legacy_app.test_client()
    delete_calls = []
    native_client = _native_layout_client(delete_calls)
    for path in (
        '/api/layouts/detail/presets/not-an-integer',
        '/api/layouts/detail/presets/-1',
    ):
        legacy = legacy_client.delete(path)
        native = native_client.delete(path)
        assert native.status_code == legacy.status_code == 404
        assert native.headers['content-type'] == legacy.headers['Content-Type']
        assert native.content == legacy.get_data()
        assert native.headers.get('location') == legacy.headers.get('Location')

    valid = native_client.delete(
        '/api/layouts/detail/presets/123',
        headers={'X-CSRFToken': native_client.csrf_token},
    )
    assert valid.status_code == 404, valid.text
    assert delete_calls == [(71, 123)]
