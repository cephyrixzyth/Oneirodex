from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4
from xml.etree import ElementTree

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from tests.fixtures.native_auth import login_identity_for, persistent_login_store

from oneirodex.runtime_native.library_exports import create_library_export_router
from oneirodex.runtime_native.library_exports import LibraryExportData
from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.models import Game, Library, User, UserLibraryAccess
from oneirodex.platform import LibraryPlatform


class FakeExports:
    def esde(self, user, platform, _flask_app):
        assert user.id == 4
        return b'<?xml version="1.0"?><gameList />'

    def pegasus(self, user, platform, _flask_app):
        assert user.id == 4
        return f'collection: {platform or "Library"}'


def _client(*, authenticated=True):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-library-exports', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.app_context = lambda: (_ for _ in ()).throw(AssertionError('unexpected Flask app context'))
    user = SimpleNamespace(
        id=4, user_id='member', role='user', state=True, is_active=True,
        is_authenticated=True, session_fingerprint=lambda: '0123456789abcdef',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    router = create_library_export_router(
        flask_app, find_user=lambda user_id: user if user_id == 4 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '4' else None,
        login_manager=manager, data_access=FakeExports(),
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    if authenticated:
        client.cookies.set(
            'session', dump_session_cookie(
                {'_user_id': login_identity_for(4), '_fresh': True}, flask_app.config['SECRET_KEY'],
            ),
        )
    return client


def test_esde_export_preserves_download_response_and_head():
    client = _client()
    response = client.get('/api/export/esde?platform=nes')
    head = client.head('/api/export/esde?platform=nes')
    assert response.status_code == 200
    assert response.content.startswith(b'<?xml')
    assert response.headers['content-type'].startswith('application/xml')
    assert response.headers['content-disposition'] == 'attachment; filename="gamelist-nes.xml"'
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_pegasus_export_defaults_collection_and_requires_member_session():
    response = _client().get('/api/export/pegasus')
    anonymous = _client(authenticated=False).get('/api/export/esde', follow_redirects=False)
    assert response.status_code == 200
    assert response.text == 'collection: Library'
    assert response.headers['content-disposition'] == 'attachment; filename="metadata-Library.pegasus.txt"'
    assert anonymous.status_code == 302
    assert anonymous.headers['location'].startswith('/login')


def test_exports_dispatch_through_outer_lazy_asgi_selector():
    import asyncio
    import httpx
    import asgi

    client = _client()
    runtime = asgi.LazyASGIApp()
    runtime._native_read_api_app = client.app
    runtime._native_read_api_routes = frozenset({
        '/api/export/esde', '/api/export/pegasus',
    })
    async def ensure_flask():
        return None
    runtime._ensure_flask = ensure_flask

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://localhost',
        ) as request_client:
            request_client.cookies.set('session', client.cookies.get('session'), path='/')
            return await request_client.get('/api/export/esde')

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.headers['content-disposition'] == 'attachment; filename="gamelist-all.xml"'


def test_exports_include_all_authorized_games_and_filter_platform_before_iteration(
    db_session, monkeypatch,
):
    user = User(
        name=f'export-{uuid4().hex[:8]}', email=f'{uuid4().hex}@example.test',
        role='user', user_id=str(uuid4()), state=True,
    )
    user.set_password('password123')
    nes = Library(name=f'NES-{uuid4().hex[:6]}', platform=LibraryPlatform.NES, display_order=1)
    psx = Library(name=f'PSX-{uuid4().hex[:6]}', platform=LibraryPlatform.PSX, display_order=2)
    db_session.add_all([user, nes, psx])
    db_session.flush()
    db_session.add_all([
        Game(
            uuid=str(uuid4()), name=f'NES title {index:03}', library_uuid=nes.uuid,
            full_disk_path=f'/games/nes/{index:03}.nes',
        )
        for index in range(501)
    ])
    only_psx = Game(
        uuid=str(uuid4()), name='The final PSX title', library_uuid=psx.uuid,
        full_disk_path='/games/psx/final.chd',
    )
    db_session.add(only_psx)
    db_session.commit()

    service = LibraryExportData()
    flask_app = Flask(__name__)
    flask_app.config.update(LIBRARY_HOST_PATH='/games')
    all_xml = ElementTree.fromstring(service.esde(user, None, flask_app))
    psx_xml = ElementTree.fromstring(service.esde(user, 'PSX', flask_app))
    assert len(all_xml.findall('game')) == 502
    assert [node.findtext('id') for node in psx_xml.findall('game')] == [only_psx.uuid]

    from oneirodex.routes_apis import wave8_11
    monkeypatch.setattr(wave8_11, 'current_user', user)
    assert len(list(wave8_11._games_for_platform(None))) == 502
    assert [game.uuid for game in wave8_11._games_for_platform('PSX')] == [only_psx.uuid]

    child = User(
        name=f'child-{uuid4().hex[:8]}', email=f'{uuid4().hex}@example.test',
        role='child', user_id=str(uuid4()), state=True,
    )
    child.set_password('password123')
    db_session.add(child)
    db_session.flush()
    db_session.add(UserLibraryAccess(user_id=child.id, library_uuid=nes.uuid))
    db_session.commit()
    child_xml = ElementTree.fromstring(service.esde(child, None, flask_app))
    child_ids = [node.findtext('id') for node in child_xml.findall('game')]
    assert len(child_ids) == 501
    assert only_psx.uuid not in child_ids
