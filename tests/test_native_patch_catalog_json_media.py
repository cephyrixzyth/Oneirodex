from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, request as flask_request

from oneirodex.runtime_native.patch_catalog_routes import create_patch_catalog_router
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie,
    generate_csrf_token,
)


def test_patch_guide_attach_uses_flask_json_media_type_classification():
    legacy = Flask('legacy-patch-catalog')
    with legacy.test_request_context(
        '/api/patch-catalog/attach', method='POST', content_type='text/plain+json',
        data=b'{"game_uuid":"game-1","source_url":"https://patch.test/guide"}',
    ):
        assert flask_request.is_json is False
        assert flask_request.get_json(silent=True) is None

    flask_app = Flask('native-patch-catalog')
    flask_app.config.update(SECRET_KEY='patch-catalog-media-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=41, role='admin', is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    calls = []
    data = SimpleNamespace(
        enabled=lambda _app: True,
        game=lambda game_uuid: calls.append(('game', game_uuid)) or object(),
        can_access_game=lambda _user, _game: True,
        attach=lambda *_args, **_kwargs: calls.append(('attach',)) or {},
    )
    router = create_patch_catalog_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 41 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '41' else None,
        login_manager=manager,
        data_access=data,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session = {'_user_id': '41:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, flask_app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session, flask_app.config['SECRET_KEY']))

    response = client.post(
        '/api/patch-catalog/attach',
        content=b'{"game_uuid":"game-1","source_url":"https://patch.test/guide"}',
        headers={
            'Content-Type': 'text/plain+json',
            'X-CSRFToken': csrf,
        },
    )

    assert response.status_code == 422, response.text
    assert response.json()['error_code'] == 'unprocessable'
    assert set(response.json()['detail']) == {'game_uuid', 'source_url'}
    assert calls == []
