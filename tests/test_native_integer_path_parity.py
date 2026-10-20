from __future__ import annotations

import logging
from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from flask import Flask, request
from flask_login import LoginManager
from werkzeug.exceptions import HTTPException

from oneirodex.routes_apis.layouts import apis_bp
from oneirodex.runtime_native.layouts import create_layout_router
from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.utils.error_envelope import http_error_code, wants_json_error


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


def _install_legacy_error_envelope(app):
    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if not wants_json_error(request):
            return error.get_response()
        from oneirodex.utils.api_response import api_error

        return api_error(
            error.description or error.name or 'Request failed',
            code=http_error_code(error.code), status=error.code or 500,
        )


def test_layout_preset_delete_rejects_paths_flask_integer_converter_does_not_match():
    legacy_app = Flask(__name__)
    legacy_app.config['SECRET_KEY'] = 'legacy-layout-route-parity-secret'
    login_manager = LoginManager()
    login_manager.init_app(legacy_app)
    login_manager.login_view = 'login'
    login_manager.user_loader(lambda _user_id: None)
    _install_legacy_error_envelope(legacy_app)
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
        assert native.headers['content-type'].startswith('application/json')
        assert native.headers['content-type'] == legacy.headers['Content-Type']
        assert native.json() == legacy.json
        assert native.headers.get('location') == legacy.headers.get('Location')

    valid = native_client.delete(
        '/api/layouts/detail/presets/123',
        headers={'X-CSRFToken': native_client.csrf_token},
    )
    assert valid.status_code == 404, valid.text
    assert delete_calls == [(71, 123)]


def test_native_api_unmatched_route_uses_legacy_flask_not_found_message():
    import asgi

    legacy_app = Flask(__name__)
    _install_legacy_error_envelope(legacy_app)
    current_app = FastAPI()
    asgi._install_native_api_error_handlers(
        current_app, {'CSP_ENABLED': False}, logging.getLogger('route-parity-test')
    )

    legacy_client = legacy_app.test_client()
    current_client = TestClient(current_app)
    for path in ('/api/route-that-does-not-exist', '/route-that-does-not-exist'):
        legacy = legacy_client.get(path)
        current = current_client.get(path)
        assert current.status_code == legacy.status_code == 404
        assert current.headers['content-type'] == legacy.headers['Content-Type']
        if current.headers['content-type'].startswith('application/json'):
            assert current.json() == legacy.json
        else:
            assert current.content == legacy.get_data()


def test_native_admin_method_misses_match_legacy_html_and_allowed_methods():
    import asgi

    legacy_app = Flask(__name__)
    legacy_app.config.update(SECRET_KEY='admin-method-parity-secret', CSP_ENABLED=False)
    _install_legacy_error_envelope(legacy_app)
    legacy_app.add_url_rule(
        '/admin/api/delete_image/<int:image_id>', 'delete_image',
        lambda image_id: '', methods=['DELETE'],
    )
    legacy_app.add_url_rule(
        '/admin/api/user/<int:user_id>', 'manage_user_get_delete',
        lambda user_id: '', methods=['GET', 'DELETE'],
    )
    legacy_app.add_url_rule(
        '/admin/api/user/<int:user_id>', 'manage_user_put',
        lambda user_id: '', methods=['PUT'],
    )

    current_app = FastAPI()
    nested_router = APIRouter()
    nested_router.add_api_route(
        '/admin/api/delete_image/{image_id:int}', lambda image_id: '',
        methods=['DELETE'],
    )
    nested_router.add_api_route(
        '/admin/api/user/{user_id:int}', lambda user_id: '',
        methods=['GET', 'DELETE'],
    )
    nested_router.add_api_route(
        '/admin/api/user/{user_id:int}', lambda user_id: '',
        methods=['PUT'],
    )
    current_app.include_router(nested_router)
    asgi._install_native_api_error_handlers(
        current_app, legacy_app.config, logging.getLogger('admin-method-parity-test'),
        routing_app=legacy_app,
    )

    legacy_client = legacy_app.test_client()
    current_client = TestClient(current_app)
    for method, path in (
        ('PUT', '/admin/api/delete_image/1'),
        ('POST', '/admin/api/user/1'),
    ):
        legacy = legacy_client.open(path, method=method)
        current = current_client.request(method, path)
        assert current.status_code == legacy.status_code == 405
        assert current.headers['content-type'] == legacy.headers['Content-Type']
        assert current.content == legacy.get_data()
        assert set(current.headers['allow'].split(', ')) == set(
            legacy.headers['Allow'].split(', ')
        )


def test_integer_route_converter_misses_match_flask_for_social_chat_and_ownership():
    import asgi

    from oneirodex.routes_apis import apis_bp
    from oneirodex.runtime_native.chat_reads import create_chat_reads_router
    from oneirodex.runtime_native.ownership_admin_reads import create_ownership_admin_read_router
    from oneirodex.runtime_native.social_writes import create_social_writes_router
    from oneirodex.runtime_native.wishlist import create_wishlist_router

    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='integer-route-parity-secret', CSP_ENABLED=False)
    legacy_login = LoginManager()
    legacy_login.init_app(flask_app)
    legacy_login.login_view = 'login'
    legacy_login.user_loader(lambda _user_id: None)
    _install_legacy_error_envelope(flask_app)
    flask_app.register_blueprint(apis_bp, url_prefix='/api')

    router_args = {
        'find_user': lambda _user_id: None,
        'find_token': lambda _prefix: None,
        'commit_token_touch': lambda _token: None,
        'database_scope': lambda _app: nullcontext(),
    }
    current_app = FastAPI()
    for create_router in (
        create_chat_reads_router,
        create_ownership_admin_read_router,
        create_social_writes_router,
        create_wishlist_router,
    ):
        current_app.include_router(create_router(flask_app, **router_args))
    asgi._install_native_api_error_handlers(
        current_app, flask_app.config, logging.getLogger('route-parity-test')
    )

    cases = (
        ('POST', '/api/chat/channels/nope/mute'),
        ('POST', '/api/chat/channels/nope/archive'),
        ('POST', '/api/chat/channels/nope/leave'),
        ('POST', '/api/chat/channels/nope/attachments'),
        ('OPTIONS', '/api/chat/channels/nope/attachments'),
        ('GET', '/api/chat/channels/nope/messages'),
        ('HEAD', '/api/chat/channels/nope/messages'),
        ('POST', '/api/chat/channels/nope/messages'),
        ('POST', '/api/chat/messages/nope/reactions'),
        ('POST', '/api/chat/spaces/nope/channels'),
        ('GET', '/api/chat/spaces/nope/members'),
        ('HEAD', '/api/chat/spaces/nope/members'),
        ('POST', '/api/chat/spaces/nope/members'),
        ('DELETE', '/api/chat/spaces/nope/members/also-nope'),
        ('GET', '/api/chat/spaces/nope/invites'),
        ('HEAD', '/api/chat/spaces/nope/invites'),
        ('POST', '/api/chat/spaces/nope/invites'),
        ('POST', '/api/chat/spaces/invites/nope/revoke'),
        ('POST', '/api/admin/ownership/connections/nope/steam/sync'),
        ('POST', '/api/admin/ownership/connections/nope/steam/cancel'),
        ('POST', '/api/social/friends/nope/reject'),
        ('POST', '/api/social/friends/nope/block'),
        ('POST', '/api/social/friends/nope/accept'),
        ('DELETE', '/api/social/friends/nope'),
        ('DELETE', '/api/requests/nope'),
        ('PATCH', '/api/requests/nope'),
    )
    legacy_client = flask_app.test_client()
    current_client = TestClient(current_app)
    for method, path in cases:
        legacy = legacy_client.open(path, method=method)
        current = current_client.request(method, path)
        assert current.status_code == legacy.status_code == 404, (method, path)
        assert current.headers['content-type'] == legacy.headers['Content-Type'], (method, path)
        if method == 'HEAD':
            assert current.content == legacy.get_data() == b'', (method, path)
        else:
            assert current.json() == legacy.json, (method, path)


def test_empty_path_converter_values_match_legacy_route_misses():
    import asgi

    import oneirodex.routes_admin_ext.images
    from oneirodex.routes_admin_ext import admin2_bp
    from oneirodex.runtime_native.admin_theme_fonts import create_admin_theme_font_router
    from oneirodex.runtime_native.discover_reads import create_discover_reads_router
    from oneirodex.runtime_native.emulator_mutations import create_emulator_mutations_router
    from oneirodex.routes_apis import apis_bp

    legacy_app = Flask(__name__)
    legacy_app.config.update(SECRET_KEY='path-route-parity-secret', CSP_ENABLED=False)
    login_manager = LoginManager()
    login_manager.init_app(legacy_app)
    login_manager.login_view = 'login'
    login_manager.user_loader(lambda _user_id: None)
    _install_legacy_error_envelope(legacy_app)
    legacy_app.register_blueprint(apis_bp, url_prefix='/api')
    legacy_app.register_blueprint(admin2_bp)

    current_flask_app = Flask('path-route-parity-current')
    current_flask_app.config.update(SECRET_KEY='path-route-parity-secret', CSP_ENABLED=False)
    router_args = {
        'find_user': lambda _user_id: None,
        'find_token': lambda _prefix: None,
        'commit_token_touch': lambda _token: None,
        'database_scope': lambda _app: nullcontext(),
    }
    current_app = FastAPI()
    current_app.include_router(create_admin_theme_font_router(current_flask_app, **router_args))
    current_app.include_router(create_discover_reads_router(
        current_flask_app, **router_args, data_access=SimpleNamespace(),
    ))
    current_app.include_router(create_emulator_mutations_router(
        current_flask_app, **router_args, data_access=SimpleNamespace(),
    ))
    asgi._install_native_api_error_handlers(
        current_app, current_flask_app.config, logging.getLogger('path-route-parity-test')
    )

    cases = (
        ('GET', '/api/games/test/cheats/'),
        ('DELETE', '/api/games/test/cheats/'),
        ('GET', '/api/discover/hubs/genre/'),
        ('DELETE', '/admin/api/theme/fonts/'),
    )
    legacy_client = legacy_app.test_client()
    current_client = TestClient(current_app)
    for method, path in cases:
        legacy = legacy_client.open(path, method=method)
        current = current_client.request(method, path)
        assert current.status_code == legacy.status_code == 404, (method, path)
        assert current.headers['content-type'] == legacy.headers['Content-Type'], (method, path)
        assert current.headers.get('location') == legacy.headers.get('Location'), (method, path)
        if current.headers['content-type'].startswith('application/json'):
            assert current.json() == legacy.json, (method, path)
        else:
            assert current.content == legacy.get_data(), (method, path)
