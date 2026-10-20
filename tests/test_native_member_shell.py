from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from oneirodex.runtime_native import admin_pilot, db_session, member_shell


class Member:
    id = 14
    name = 'Home <Player>'
    role = 'librarian'
    avatarpath = 'newstyle/avatars/controller.svg'
    preferences = SimpleNamespace(
        theme='default', icon_pack='outline', tile_size=75,
        show_tile_titles=False, locale='en-CA', items_per_page=40,
        default_sort='last_played', default_sort_order='desc',
    )


def _app_config(**overrides):
    config = {
        'SECRET_KEY': 'member-shell-test',
        'PERMANENT_SESSION_LIFETIME': timedelta(days=31),
        'SESSION_COOKIE_NAME': 'session',
        'SESSION_COOKIE_PATH': '/',
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SECURE': False,
        'SESSION_COOKIE_SAMESITE': 'Lax',
        'SESSION_COOKIE_PARTITIONED': False,
        'WTF_CSRF_FIELD_NAME': 'csrf_token',
        'CSP_ENABLED': True,
        'CSP_ENFORCE': True,
        'ENABLE_VR_BROWSE': True,
        'ENABLE_ACTIVITY_FEED': True,
        'ENABLE_NEW_CHROME': True,
        'ONEIRODEX_SOURCE_URL': 'https://example.invalid/source',
    }
    config.update(overrides)
    return SimpleNamespace(
        config=config,
        root_path=str(Path(__file__).resolve().parents[1] / 'oneirodex'),
        static_url_path='/static',
        login_manager=None,
    )


def _native_client(monkeypatch, *, config=None, query_result=None, user=None, native_session=None):
    user = user or Member()
    session_data = {
        '_user_id': '14:fingerprint',
        '_fresh': True,
        '_flashes': [('error', '<Scan failed>'), ('image-refresh', 'Cover ready')],
        'image_refresh_game_uuid': 'game-14',
    }
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda _user_id: user, lambda _prefix: None, lambda _token: None,
    ))
    monkeypatch.setattr(member_shell, 'request_auth_context', lambda *_args, **_kwargs: SimpleNamespace(
        user=user, session_data=session_data, should_set_session_cookie=True, token=None,
    ))

    @contextmanager
    def database_scope(_app):
        session = native_session or SimpleNamespace(
            added=[], commits=0,
        )
        session.execute = lambda _statement: SimpleNamespace(
            scalars=lambda: SimpleNamespace(first=lambda: query_result),
        )
        session.add = lambda row: session.added.append(row)
        session.commit = lambda: setattr(session, 'commits', session.commits + 1)
        token = db_session._native_session.set(session)
        try:
            yield
        finally:
            db_session._native_session.reset(token)

    app = FastAPI()
    app.include_router(member_shell.create_member_shell_router(
        config or _app_config(), database_scope=database_scope,
    ))
    return TestClient(app), session_data


def test_member_shell_preserves_authenticated_spa_bootstrap_and_session(monkeypatch):
    client, session_data = _native_client(monkeypatch)
    response = client.get('/systems')

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/html')
    assert response.headers['vary'] == 'Cookie'
    assert response.headers['content-security-policy']
    assert response.cookies.get('session')
    assert 'data-user-id="14"' in response.text
    assert 'data-is-librarian="true"' in response.text
    assert 'data-show-tile-titles="false"' in response.text
    assert 'data-username="Home &lt;Player&gt;"' in response.text
    assert 'class="alert alert-danger' in response.text
    assert '&lt;Scan failed&gt;' in response.text
    assert 'data-game-uuid="game-14"' in response.text
    assert 'name="csrf_token" value="' in response.text
    assert 'member-app/member-app.css' in response.text
    assert 'member-app/member-app.js' in response.text
    assert '_flashes' not in session_data
    assert 'image_refresh_game_uuid' not in session_data


def test_member_shell_head_feature_redirect_and_route_selector(monkeypatch):
    client, _session_data = _native_client(
        monkeypatch,
        config=_app_config(ENABLE_ACTIVITY_FEED='false'),
    )
    head = client.head('/activity', follow_redirects=False)
    assert head.status_code == 302
    assert head.headers['location'] == '/library'
    assert head.headers['content-security-policy']

    vr_client, _session_data = _native_client(
        monkeypatch,
        config=_app_config(ENABLE_VR_BROWSE='false'),
    )
    vr_response = vr_client.get('/vr', follow_redirects=False)
    assert vr_response.status_code == 302
    assert vr_response.headers['location'] == '/library'

    for path in (
        '/discover', '/discover/row', '/discover/zone/popular',
        '/discover/hub/genre/role-playing', '/collections/collection-1',
        '/members/12', '/systems/completion', '/trailers', '/downloads',
        '/playromtest',
    ):
        assert member_shell.member_shell_route(path)
    assert member_shell.member_shell_route('/game_details/not-a-uuid')
    assert not member_shell.member_shell_route('/api/auth/runtime-bootstrap')


def test_game_details_shell_keeps_uuid_existence_and_library_acl(monkeypatch):
    from oneirodex.utils import library_acl

    valid_uuid = '7de1040c-42d9-4f42-904b-f469e68a9673'
    game = SimpleNamespace(uuid=valid_uuid, library_uuid='library-1')
    monkeypatch.setattr(library_acl, 'user_can_access_game', lambda *_args: True)
    client, _ = _native_client(monkeypatch, query_result=game)
    response = client.get(f'/game_details/{valid_uuid}')
    assert response.status_code == 200
    assert 'id="member-app-root"' in response.text

    assert client.get('/game_details/not-a-uuid').status_code == 404
    missing, _ = _native_client(monkeypatch, query_result=None)
    assert missing.get(f'/game_details/{valid_uuid}').status_code == 404

    monkeypatch.setattr(library_acl, 'user_can_access_game', lambda *_args: False)
    denied, _ = _native_client(monkeypatch, query_result=game)
    assert denied.get(f'/game_details/{valid_uuid}').status_code == 403


def test_game_details_missing_resource_keeps_legacy_html_error_for_get_and_head(monkeypatch):
    from werkzeug.exceptions import NotFound

    valid_uuid = '7de1040c-42d9-4f42-904b-f469e68a9673'
    client, _ = _native_client(monkeypatch, query_result=None)

    get_response = client.get(f'/game_details/{valid_uuid}')
    head_response = client.head(f'/game_details/{valid_uuid}')

    assert get_response.status_code == head_response.status_code == 404
    assert get_response.headers['content-type'] == 'text/html; charset=utf-8'
    assert head_response.headers['content-type'] == 'text/html; charset=utf-8'
    assert get_response.content == NotFound().get_response().get_data()
    assert head_response.content == b''


def test_library_shell_preserves_filters_preferences_and_empty_state(monkeypatch):
    from oneirodex.utils.helpers import counts
    import json
    from urllib.parse import quote

    monkeypatch.setattr(counts, 'get_library_count', lambda: 4)
    monkeypatch.setattr(counts, 'get_games_count', lambda: 72)
    monkeypatch.setattr(counts, 'get_first_run_state', lambda: {
        'scan_has_run': True, 'unmatched_count': 5,
    })
    client, _ = _native_client(monkeypatch)
    saved = quote(json.dumps({
        'library_uuid': 'library-saved', 'theme': 'arcade', 'rating': '3',
        'game_mode': 'co-op',
    }))
    response = client.get(
        '/library?genre=Platformer&per_page=60&sort_by=rating&sort_order=desc',
        cookies={'libraryFilters': saved},
    )

    assert response.status_code == 200
    assert 'data-per-page="60"' in response.text
    assert 'data-default-sort="rating"' in response.text
    assert 'data-default-sort-order="desc"' in response.text
    assert 'data-library-count="4"' in response.text
    assert 'data-games-count="72"' in response.text
    assert 'data-scan-has-run="1"' in response.text
    assert 'data-unmatched-count="5"' in response.text
    assert 'Platformer' in response.text and 'arcade' in response.text
    assert 'library-saved' in response.text and 'co-op' in response.text


def test_library_shell_creates_missing_preferences_in_native_session(monkeypatch):
    from oneirodex.models import UserPreference
    from oneirodex.utils.helpers import counts

    monkeypatch.setattr(counts, 'get_library_count', lambda: 0)
    monkeypatch.setattr(counts, 'get_games_count', lambda: 0)
    monkeypatch.setattr(counts, 'get_first_run_state', lambda: {
        'scan_has_run': False, 'unmatched_count': 0,
    })
    user = Member()
    user.preferences = None
    session = SimpleNamespace(added=[], commits=0)
    client, _ = _native_client(monkeypatch, user=user, native_session=session)

    response = client.get('/library')
    assert response.status_code == 200
    assert len(session.added) == 1
    assert isinstance(session.added[0], UserPreference)
    assert session.added[0].user_id == user.id
    assert session.commits == 1
    assert user.preferences is session.added[0]


def test_member_shell_dispatches_from_the_outer_asgi_app(monkeypatch):
    import asyncio

    import httpx
    import asgi

    client, _session_data = _native_client(monkeypatch)
    runtime = asgi.LazyASGIApp()
    runtime._native_member_shell_app = client.app
    runtime._flask_app = _app_config()

    async def initialized():
        return None

    runtime._ensure_flask = initialized

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as http:
            return await http.get('/discover/zone/popular')

    response = asyncio.run(request())
    assert response.status_code == 200
    assert 'id="member-app-root"' in response.text

    async def downloads_request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as http:
            return await http.get('/downloads')

    downloads_response = asyncio.run(downloads_request())
    assert downloads_response.status_code == 200
    assert 'id="member-app-root"' in downloads_response.text

    async def playromtest_request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime),
            base_url='http://localhost',
        ) as http:
            return await http.get('/playromtest')

    playromtest_response = asyncio.run(playromtest_request())
    assert playromtest_response.status_code == 200
    assert 'Use Play from a game details page for browser emulation.' in playromtest_response.text
