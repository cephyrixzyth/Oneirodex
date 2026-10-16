"""Assist packs, and the companion overlay links (INSP-45 / H4f): maps, guides,
clips, a wiki -- pages beside the game, never a hand inside it."""
from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.routes_apis.assists import (
    _pack_path,
    assists_enabled,
    default_overlay_links,
    load_assist_pack,
    overlay_links_for,
)


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(name=f'adm_{uid[:8]}', email=f'adm_{uid[:8]}@example.com', role='admin', user_id=uid, state=True)
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def member(db_session):
    uid = str(uuid4())
    row = User(name=f'mem_{uid[:8]}', email=f'mem_{uid[:8]}@example.com', role='user', user_id=uid, state=True)
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def _game(db_session, tmp_path, platform=LibraryPlatform.PCWIN, name='Hollow Knight'):
    lib = Library(name=f'L_{uuid4().hex[:6]}', platform=platform)
    db_session.add(lib)
    db_session.flush()
    row = Game(uuid=str(uuid4()), name=name, library_uuid=lib.uuid, full_disk_path=str(tmp_path / uuid4().hex[:6]))
    db_session.add(row)
    db_session.commit()
    return row


def test_assist_configuration_helpers_accept_explicit_config_without_flask_context(tmp_path):
    root = tmp_path / 'configured-assists'
    config = {'ENABLE_GAME_ASSISTS': 'false', 'GAME_ASSISTS_PATH': str(root)}

    assert not assists_enabled(config=config)
    assert _pack_path('12345678-1234-1234-1234-123456789abc', config=config) == str(
        root / '12345678-1234-1234-1234-123456789abc' / 'pack.json'
    )
    assert load_assist_pack('12345678-1234-1234-1234-123456789abc', config=config) is None


def test_default_overlay_is_a_wiki_search_for_pc_titles_only(db_session, tmp_path):
    pc = _game(db_session, tmp_path)
    links = default_overlay_links(pc)
    assert len(links) == 1 and links[0]['kind'] == 'wiki'
    assert links[0]['url'] == 'https://www.pcgamingwiki.com/w/index.php?search=Hollow+Knight'
    assert default_overlay_links(_game(db_session, tmp_path, LibraryPlatform.SNES, 'Chrono Trigger')) == []
    # A pack wiki row replaces the default; other kinds add to it
    pack = {'overlay_links': [{'label': 'Fandom wiki', 'url': 'https://hollowknight.wiki/', 'kind': 'wiki'}, {'label': 'Map', 'url': 'https://example.invalid/map', 'kind': 'map'}]}
    rows = overlay_links_for(pc, pack)
    assert [r['kind'] for r in rows] == ['wiki', 'map']
    assert overlay_links_for(pc, None)[0]['label'] == 'PCGamingWiki'


def test_admin_writes_a_validated_pack_and_members_read_the_overlay(client, app, db_session, admin, member, tmp_path):
    app.config['GAME_ASSISTS_PATH'] = str(tmp_path / 'assists')
    game = _game(db_session, tmp_path)
    url = f'/api/games/{game.uuid}/assists'

    _login(client, app, admin)
    body = {
        'title': 'Knight helpers',
        'toggles': [{'id': 'slow_time', 'label': 'Slow time', 'description': 'offline only'}],
        'overlay_links': [
            {'label': 'Interactive map', 'url': 'https://example.invalid/map', 'kind': 'map'},
            {'label': 'Speedrun clips', 'url': 'https://example.invalid/clips', 'kind': 'clip'},
        ],
    }
    resp = client.put(url, json=body)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data['pack']['overlay_links'][0]['kind'] == 'map'
    kinds = [r['kind'] for r in data['overlay_links']]
    assert kinds == ['map', 'clip', 'wiki']  # pack rows first, the default wiki appended

    # Never a file, a process or anything but an http(s) page
    assert client.put(url, json={'overlay_links': [{'label': 'x', 'url': 'file:///C:/trainer.exe'}]}).status_code == 422
    assert client.put(url, json={'overlay_links': [{'label': 'x', 'url': 'https://ok/', 'kind': 'inject'}]}).status_code == 422
    assert client.put(url, json={'memory_patch': True}).status_code == 422

    member_client = app.test_client()
    _login(member_client, app, member)
    resp = member_client.get(url)
    assert resp.status_code == 200
    got = resp.get_json()
    assert got['enabled'] is True and got['pack']['title'] == 'Knight helpers'
    assert [r['kind'] for r in got['overlay_links']] == ['map', 'clip', 'wiki']
    assert member_client.put(url, json=body).status_code in (302, 403)
