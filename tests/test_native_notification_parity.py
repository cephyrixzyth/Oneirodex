from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from oneirodex.models import User


def test_admin_notification_bus_member_denial_redirects_without_calling_bus():
    from contextlib import nullcontext
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from flask import Flask

    from oneirodex.runtime_native.notifications import create_notifications_router
    from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token

    app = Flask('notification-bus-member-denial-test')
    app.config.update(
        SECRET_KEY='notification-bus-member-denial-secret',
        WTF_CSRF_ENABLED=True, CSP_ENABLED=False,
    )
    app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    member = SimpleNamespace(
        id=9, role='member', state=True, is_active=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Sign in',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    bus_calls = []
    native = FastAPI()
    native.include_router(create_notifications_router(
        app,
        find_user=lambda user_id: member if user_id == 9 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: member if value == '9:fingerprint' else None,
        login_manager=manager,
        data_access=SimpleNamespace(
            bus_status=lambda: bus_calls.append('status') or {'configured': True},
            emit_test=lambda: bus_calls.append('emit') or True,
        ),
        database_scope=lambda _app: nullcontext(),
    ))
    client = TestClient(native, follow_redirects=False)
    session = {'_user_id': '9:fingerprint', '_fresh': True}
    csrf = generate_csrf_token(session, app.config['SECRET_KEY'])
    client.cookies.set('session', dump_session_cookie(session, app.config['SECRET_KEY']))

    response = client.post('/api/admin/notify-bus/test', headers={'X-CSRFToken': csrf})

    assert response.status_code == 302
    assert response.headers['location'] == '/login'
    assert bus_calls == []


@pytest.mark.parametrize(
    'failure',
    [
        RuntimeError('synthetic-secret-db-detail'),
        OperationalError(
            'SELECT synthetic_notification_failure',
            {},
            Exception('synthetic-secret-db-detail'),
        ),
    ],
    ids=['unexpected-runtime-error', 'sqlalchemy-operational-error'],
)
def test_notification_database_failure_matches_wsgi_and_native_asgi(
    app, client, db_session, failure, monkeypatch,
):
    import asyncio
    from contextlib import nullcontext

    import httpx
    from fastapi import FastAPI

    import asgi
    from oneirodex import login_manager
    from oneirodex.runtime_native.notifications import create_notifications_router
    from oneirodex.runtime_native.session_compat import dump_session_cookie
    from oneirodex.routes_apis import notifications as notification_routes

    user_key = str(uuid4())
    flask_user = User(
        name=f'notification-failure-{user_key[:8]}',
        email=f'notification-failure-{user_key[:8]}@example.test',
        password_hash='unused',
        role='user',
        user_id=user_key,
        avatarpath='newstyle/avatar_default.jpg',
        state=True,
    )
    db_session.add(flask_user)
    db_session.commit()

    def fail_list(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(notification_routes, 'list_notifications', fail_list)
    monkeypatch.setattr(notification_routes, 'mark_read', fail_list)
    with client.session_transaction() as session:
        session['_user_id'] = str(flask_user.id)
        session['_fresh'] = True
    wsgi_list_response = client.get('/api/notifications')
    wsgi_write_response = client.post('/api/notifications/read', json={'ids': []})

    native_user = SimpleNamespace(
        id=flask_user.id,
        role='user',
        state=True,
        is_active=True,
        is_authenticated=True,
        session_fingerprint=lambda: 'notification-failure-fingerprint',
    )

    class FailingNotificationData:
        def list(self, *_args, **_kwargs):
            raise failure

        def mark_read(self, *_args, **_kwargs):
            raise failure

    native_app = FastAPI()
    native_app.include_router(create_notifications_router(
        app,
        find_user=lambda user_id: native_user if user_id == native_user.id else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: (
            native_user
            if value.split(':', 1)[0] == str(native_user.id)
            else None
        ),
        login_manager=login_manager,
        data_access=FailingNotificationData(),
        database_scope=lambda _flask_app: nullcontext(),
    ))
    asgi._install_native_api_error_handlers(native_app, app.config, app.logger)
    native_cookie = dump_session_cookie(
        {
            '_user_id': f'{native_user.id}:{native_user.session_fingerprint()}',
            '_fresh': True,
        },
        app.config['SECRET_KEY'],
    )

    async def get_native_responses():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=native_app,
                raise_app_exceptions=False,
            ),
            base_url='http://localhost',
        ) as native_client:
            native_client.cookies.set('session', native_cookie)
            list_response = await native_client.get('/api/notifications')
            write_response = await native_client.post(
                '/api/notifications/read', json={'ids': []},
            )
            return list_response, write_response

    native_list_response, native_write_response = asyncio.run(get_native_responses())

    assert wsgi_list_response.status_code == native_list_response.status_code == 500
    assert wsgi_list_response.get_json() == native_list_response.json()
    assert wsgi_write_response.status_code == native_write_response.status_code == 500
    assert wsgi_write_response.get_json() == native_write_response.json()
    for response in (wsgi_list_response, wsgi_write_response):
        assert 'synthetic-secret-db-detail' not in response.get_data(as_text=True)
    for response in (native_list_response, native_write_response):
        assert 'synthetic-secret-db-detail' not in response.text


@pytest.mark.parametrize(
    'failure',
    [
        RuntimeError('synthetic-secret-db-detail'),
        OperationalError(
            'COMMIT synthetic_notification_preferences',
            {},
            Exception('synthetic-secret-db-detail'),
        ),
    ],
    ids=['unexpected-runtime-error', 'sqlalchemy-operational-error'],
)
def test_notification_preferences_commit_failure_matches_wsgi_and_native_asgi(
    app, client, db_session, failure, monkeypatch,
):
    import asyncio
    from contextlib import nullcontext

    import httpx
    from fastapi import FastAPI

    import asgi
    from oneirodex import login_manager
    from oneirodex.runtime_native.notifications import create_notifications_router
    from oneirodex.runtime_native.session_compat import dump_session_cookie
    from oneirodex.routes_apis import notifications as notification_routes

    user_key = str(uuid4())
    flask_user = User(
        name=f'notification-pref-failure-{user_key[:8]}',
        email=f'notification-pref-failure-{user_key[:8]}@example.test',
        password_hash='unused',
        role='user',
        user_id=user_key,
        avatarpath='newstyle/avatar_default.jpg',
        state=True,
    )
    db_session.add(flask_user)
    db_session.commit()

    def fail_commit(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(notification_routes.db.session, 'commit', fail_commit)
    with client.session_transaction() as session:
        session['_user_id'] = str(flask_user.id)
        session['_fresh'] = True
    wsgi_response = client.post(
        '/api/notifications/preferences', json={'notify_chat': False},
    )

    native_user = SimpleNamespace(
        id=flask_user.id,
        role='user',
        state=True,
        is_active=True,
        is_authenticated=True,
        preferences=None,
        session_fingerprint=lambda: 'notification-preference-failure-fingerprint',
    )

    class FailingNotificationData:
        def update_preferences(self, _user, _payload):
            raise failure

    native_app = FastAPI()
    native_app.include_router(create_notifications_router(
        app,
        find_user=lambda user_id: native_user if user_id == native_user.id else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: (
            native_user
            if value.split(':', 1)[0] == str(native_user.id)
            else None
        ),
        login_manager=login_manager,
        data_access=FailingNotificationData(),
        database_scope=lambda _flask_app: nullcontext(),
    ))
    asgi._install_native_api_error_handlers(native_app, app.config, app.logger)
    native_cookie = dump_session_cookie(
        {
            '_user_id': f'{native_user.id}:{native_user.session_fingerprint()}',
            '_fresh': True,
        },
        app.config['SECRET_KEY'],
    )

    async def post_native_response():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=native_app,
                raise_app_exceptions=False,
            ),
            base_url='http://localhost',
        ) as native_client:
            native_client.cookies.set('session', native_cookie)
            return await native_client.post(
                '/api/notifications/preferences',
                json={'notify_chat': False},
            )

    native_response = asyncio.run(post_native_response())

    assert wsgi_response.status_code == native_response.status_code == 500
    assert wsgi_response.get_json() == native_response.json()
    assert 'synthetic-secret-db-detail' not in wsgi_response.get_data(as_text=True)
    assert 'synthetic-secret-db-detail' not in native_response.text
