from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import asgi
from flask import redirect as flask_redirect

from oneirodex.runtime_native import db_session
from oneirodex.runtime_native import play_redirect


class _Result:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value


class _Session:
    def __init__(self, game):
        self.game = game

    def execute(self, _statement):
        return _Result(self.game)


def _client(monkeypatch, *, game, can_access=True, playable=False):
    user = SimpleNamespace(id=3, role='user')
    session_data = {'_user_id': '3:test-fingerprint', '_fresh': True}
    runtime_app = SimpleNamespace(
        config={
            'SECRET_KEY': 'play-redirect-secret',
            'SESSION_COOKIE_NAME': 'session',
            'PERMANENT_SESSION_LIFETIME': timedelta(days=1),
            'SESSION_REFRESH_EACH_REQUEST': True,
            'SESSION_PROTECTION': 'none',
            'CSP_ENABLED': False,
        },
        login_manager=None,
    )

    @contextmanager
    def database_scope(_app):
        token = db_session._native_session.set(_Session(game))
        try:
            yield
        finally:
            db_session._native_session.reset(token)

    monkeypatch.setattr(play_redirect, 'request_auth_context', lambda *_args, **_kwargs: (
        SimpleNamespace(
            user=user, session_data=session_data,
            should_set_session_cookie=True, token=None,
        )
    ))
    monkeypatch.setattr(
        'oneirodex.utils.library_acl.user_can_access_game',
        lambda _user, _game: can_access,
    )
    monkeypatch.setattr(
        'oneirodex.utils.play_url.browse_play_fields',
        lambda _game: {
            'can_play_in_browser': playable,
            'play_url': 'https://play.example.invalid/game' if playable else None,
        },
    )
    app = FastAPI()
    app.include_router(play_redirect.create_play_redirect_router(
        runtime_app,
        find_user=lambda _user_id: user,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        database_scope=database_scope,
    ))
    return TestClient(app), session_data


def test_missing_and_inaccessible_games_redirect_to_library_with_flash(monkeypatch):
    missing, missing_session = _client(monkeypatch, game=None)
    response = missing.get('/play_game/not-a-game', follow_redirects=False)
    legacy = flask_redirect('/library')
    assert response.status_code == 302
    assert response.headers['location'] == '/library'
    assert response.headers['content-type'] == legacy.headers['Content-Type']
    assert response.content == legacy.get_data()
    assert missing_session['_flashes'] == [('error', 'Game not found.')]
    assert response.cookies.get('session')

    denied, denied_session = _client(
        monkeypatch, game=SimpleNamespace(uuid='game-uuid'), can_access=False,
    )
    response = denied.get('/play_game/game-uuid', follow_redirects=False)
    legacy = flask_redirect('/library')
    assert response.headers['location'] == '/library'
    assert response.headers['content-type'] == legacy.headers['Content-Type']
    assert response.content == legacy.get_data()
    assert denied_session['_flashes'] == [
        ('error', 'You do not have access to this game.'),
    ]


def test_playable_and_non_playable_games_keep_legacy_redirects(monkeypatch):
    game = SimpleNamespace(uuid='game-uuid')
    playable, _ = _client(monkeypatch, game=game, playable=True)
    response = playable.get('/play_game/game-uuid', follow_redirects=False)
    legacy = flask_redirect('https://play.example.invalid/game')
    assert response.headers['location'] == 'https://play.example.invalid/game'
    assert response.headers['content-type'] == legacy.headers['Content-Type']
    assert response.content == legacy.get_data()

    details, session_data = _client(monkeypatch, game=game)
    response = details.get('/play_game/game-uuid', follow_redirects=False)
    legacy = flask_redirect('/game_details/game-uuid')
    assert response.headers['location'] == '/game_details/game-uuid'
    assert response.headers['content-type'] == legacy.headers['Content-Type']
    assert response.content == legacy.get_data()
    assert session_data['_flashes'] == [(
        'info',
        'This title is not playable in the browser. Open details for download/install.',
    )]


def test_outer_asgi_dispatch_keeps_play_redirect_off_wsgi(monkeypatch):
    game = SimpleNamespace(uuid='game-uuid')
    native_client, _ = _client(monkeypatch, game=game, playable=True)
    runtime = asgi.LazyASGIApp()
    runtime._native_read_api_app = native_client.app

    async def initialized():
        return None

    runtime._ensure_flask = initialized
    runtime._app = lambda *_args: (_ for _ in ()).throw(
        AssertionError('native play redirect fell through to WSGI')
    )

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://localhost',
        ) as client:
            return await client.get('/play_game/game-uuid', follow_redirects=False)

    response = asyncio.run(request())
    assert response.status_code == 302
    assert response.headers['location'] == 'https://play.example.invalid/game'
