from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
from flask import Flask
from flask_login import LoginManager

import asgi
from oneirodex.runtime_native import admin_pilot, trailers
from oneirodex.runtime_native.session_compat import dump_session_cookie


class FakeTrailerData:
    def filters(self, _user):
        return {
            'libraries': [{'uuid': 'lib-1', 'name': 'Main'}],
            'genres': [], 'themes': [], 'date_range': {'min_year': None, 'max_year': None},
        }

    def random_game_ids(self, _user, _params):
        return []

    def game(self, _game_id):
        return None


def _run(app, path, *, cookie=None, method='GET'):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver'
        ) as client:
            if cookie:
                client.cookies.set('session', cookie)
            return await client.request(method, path, follow_redirects=False)
    return asyncio.run(perform())


def _runtime(monkeypatch, *, login_message='Please log in to access this page.'):
    monkeypatch.delenv('ONEIRODEX_NATIVE_ADMIN_PILOT', raising=False)
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-asgi-trailers-secret', TESTING=True)
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.login_message = login_message
    user = SimpleNamespace(
        id=7, role='user', state=True, is_active=True,
        session_fingerprint=lambda: 'fp',
    )
    manager.user_loader(lambda identity: user if identity == '7:fp' else None)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.add_url_rule('/api/trailers/filters', view_func=lambda: 'legacy')
    flask_app.before_request(lambda: (_ for _ in ()).throw(AssertionError('Flask request dispatch used')))
    monkeypatch.setattr(asgi, 'create_app', lambda: flask_app)
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda _user_id: user,
        lambda _prefix: None,
        lambda _token: None,
    ))
    monkeypatch.setattr(trailers, 'FlaskContextTrailerData', lambda _app: FakeTrailerData())
    from oneirodex.runtime_native import db_session

    monkeypatch.setattr(db_session, 'native_session_scope', lambda *_args: nullcontext())
    return flask_app, asgi.LazyASGIApp()


def _signed_session():
    return dump_session_cookie({'_user_id': '7:fp', '_fresh': True}, 'native-asgi-trailers-secret')


def test_lazy_asgi_dispatches_authenticated_trailer_api_without_flask_request(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/trailers/filters', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['libraries'] == [{'uuid': 'lib-1', 'name': 'Main'}]
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-security-policy']


def test_lazy_asgi_preserves_login_redirect_and_flash_for_anonymous_trailer_api(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/trailers/filters')

    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Fapi%2Ftrailers%2Ffilters'
    session_cookie = response.cookies.get('session')
    assert session_cookie
    decoded = flask_app.session_interface.get_signing_serializer(flask_app).loads(session_cookie)
    assert decoded['_flashes'] == [('message', 'Please log in to access this page.')]


def test_lazy_asgi_trailer_api_preserves_head_without_flask_request(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    get = _run(runtime, '/api/trailers/filters', cookie=_signed_session())
    head = _run(runtime, '/api/trailers/filters', cookie=_signed_session(), method='HEAD')

    assert get.status_code == head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))
