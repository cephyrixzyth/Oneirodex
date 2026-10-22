from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from flask import Flask
from flask_login import LoginManager
from fastapi.testclient import TestClient

from oneirodex.routes_apis import apis_bp
import oneirodex.routes_apis.events  # register the legacy event routes
from oneirodex.runtime_native.notifications import create_notifications_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


@pytest.mark.parametrize('identity', [None, 'member', 'admin'])
def test_publish_test_event_auth_matches_legacy_flask(identity, monkeypatch):
    app = Flask('event-publish-parity')
    app.config.update(
        SECRET_KEY='event-publish-parity-secret',
        WTF_CSRF_ENABLED=False,
        CSP_ENABLED=False,
    )
    users = {
        'member': SimpleNamespace(
            id=8, name='ParityMember', role='member', state=True, is_active=True,
            is_authenticated=True, session_fingerprint=lambda: 'fp',
        ),
        'admin': SimpleNamespace(
            id=7, name='ParityAdmin', role='admin', state=True, is_active=True,
            is_authenticated=True, session_fingerprint=lambda: 'fp',
        ),
    }
    manager = LoginManager(app)
    manager.login_view = 'login.login'
    manager.user_loader(lambda key: next(
        (user for user in users.values() if key == f'{user.id}:fp'), None,
    ))
    app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    app.register_blueprint(apis_bp, url_prefix='/api')

    emitted = []
    event = {'type': 'test', 'message': 'ping', 'user': 'ParityAdmin'}
    monkeypatch.setattr(
        'oneirodex.utils.event_bus.event_bus.publish',
        lambda *args, **kwargs: emitted.append((args, kwargs)) or SimpleNamespace(to_dict=lambda: event),
    )
    native = FastAPI()
    native.include_router(create_notifications_router(
        app,
        find_user=lambda uid: next((user for user in users.values() if user.id == uid), None),
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda key: next(
            (user for user in users.values() if key == f'{user.id}:fp'), None,
        ),
        login_manager=manager,
        data_access=SimpleNamespace(publish_test_event=lambda user: (
            emitted.append((('test',), {'message': 'ping', 'user': user.name}))
            or {**event, 'user': user.name}
        )),
    ))

    legacy_client = app.test_client()
    current_client = TestClient(native, follow_redirects=False)
    if identity:
        user = users[identity]
        with legacy_client.session_transaction() as session:
            session['_user_id'] = f'{user.id}:fp'
            session['_fresh'] = True
        current_client.cookies.set(
            'session', dump_session_cookie(
                {'_user_id': f'{user.id}:fp', '_fresh': True}, app.config['SECRET_KEY'],
            ),
        )

    legacy = legacy_client.post('/api/events/publish_test')
    current = current_client.post('/api/events/publish_test')

    assert current.status_code == legacy.status_code
    assert current.headers.get('location') == legacy.headers.get('Location')
    assert current.headers.get('content-type') == legacy.headers.get('Content-Type')
    if legacy.status_code == 302:
        assert current.content == legacy.data
    else:
        assert current.json() == legacy.get_json()
    assert len(emitted) == (2 if identity == 'admin' else 0)
