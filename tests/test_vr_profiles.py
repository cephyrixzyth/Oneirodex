"""INSP-40 / H3a: ``GameVrProfile`` -- how a title plays in a headset, as a record.

Catalogue data and a deep link: the profile URL is a page, never a shim or a
path. ``vr_compat`` derives from the rows when a librarian did not set it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Game, GameVrProfile, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.secondary_scrapers import game_vr_compat, game_vr_profile_compat


@pytest.fixture
def librarian(db_session):
    uid = str(uuid4())
    row = User(name=f'lib_{uid[:8]}', email=f'lib_{uid[:8]}@example.com', role='librarian', user_id=uid, state=True)
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


@pytest.fixture
def game(db_session, tmp_path):
    lib = Library(name=f'VRP_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    row = Game(uuid=str(uuid4()), name=f'Headset Title {uuid4().hex[:6]}', library_uuid=lib.uuid, full_disk_path=str(tmp_path / 'h'))
    db_session.add(row)
    db_session.commit()
    return row



def test_vr_profile_updated_at_serializes_as_legacy_utc_naive():
    aware = datetime(2026, 10, 20, 22, 3, 21, 123456, tzinfo=timezone.utc)
    profile = GameVrProfile(kind='native', updated_at=aware)

    assert profile.to_dict()['updated_at'] == '2026-10-20T22:03:21.123456'


def test_vr_compat_derives_from_profile_rows_unless_stored(db_session, game):
    assert game_vr_compat(game) is None
    db_session.add(GameVrProfile(game_uuid=game.uuid, kind='injector', runtime='openvr', profile_url='https://example.invalid/p'))
    db_session.commit()
    db_session.refresh(game)
    assert game_vr_profile_compat(game) == 'injector_profile'
    assert game_vr_compat(game) == 'injector_profile'
    # A shipped VR mode beats a community profile
    db_session.add(GameVrProfile(game_uuid=game.uuid, kind='native', runtime='openxr'))
    db_session.commit()
    db_session.refresh(game)
    assert game_vr_compat(game) == 'native_vr'
    # A librarian's stored word still wins
    game.vr_compat = 'flat'
    db_session.commit()
    assert game_vr_compat(game) == 'flat'


def test_profile_routes_upsert_delete_and_validate(client, app, librarian, game, db_session):
    _login(client, app, librarian)
    base = f'/api/games/{game.uuid}/vr_profiles'
    assert client.get(base).get_json()['vr_profiles'] == []

    resp = client.put(f'{base}/injector', json={'runtime': 'openvr', 'profile_url': 'https://example.invalid/profile', 'notes': 'community list'})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body['profile']['kind'] == 'injector' and body['profile']['profile_url'] == 'https://example.invalid/profile'
    assert body['vr_compat'] == 'injector_profile' and body['vr_compat_stored'] is None

    # Replace, not duplicate
    resp = client.put(f'{base}/injector', json={'runtime': 'openxr', 'source': 'community'})
    assert resp.status_code == 200
    rows = resp.get_json()['vr_profiles']
    assert len(rows) == 1 and rows[0]['runtime'] == 'openxr' and rows[0]['source'] == 'community' and rows[0]['profile_url'] is None
    assert db_session.query(GameVrProfile).filter_by(game_uuid=game.uuid).count() == 1

    # Never a file, a path or a shim
    assert client.put(f'{base}/injector', json={'profile_url': 'file:///C:/shim.dll'}).status_code == 422
    assert client.put(f'{base}/injector', json={'profile_url': 'C:\\\\Games\\\\shim.dll'}).status_code == 422
    assert client.put(f'{base}/injector', json={'runtime': 'steamvr-dll'}).status_code == 422
    assert client.put(f'{base}/injector', json={'download': True}).status_code == 422
    assert client.put(f'{base}/dll', json={}).status_code == 400

    # The details payload carries the rows
    details = client.get(f'/api/games/{game.uuid}/details' if False else f'/api/vr/games/{game.uuid}')
    assert details.status_code == 200
    assert details.get_json()['vr_profiles'][0]['kind'] == 'injector'

    assert client.delete(f'{base}/injector').status_code == 200
    assert client.get(base).get_json()['vr_profiles'] == []
    assert client.delete(f'{base}/injector').status_code == 404


def test_profiles_are_readable_by_members_and_written_by_librarians(client, app, member, game, db_session):
    db_session.add(GameVrProfile(game_uuid=game.uuid, kind='flat'))
    db_session.commit()
    _login(client, app, member)
    base = f'/api/games/{game.uuid}/vr_profiles'
    assert client.get(base).get_json()['vr_profiles'][0]['kind'] == 'flat'
    assert client.put(f'{base}/native', json={}).status_code in (302, 403)
    assert client.delete(f'{base}/flat').status_code in (302, 403)


def test_hub_admits_a_title_whose_only_evidence_is_a_profile_row(client, app, member, game, db_session, monkeypatch):
    monkeypatch.setenv('ENABLE_VR_BROWSE', 'true')
    app.config['ENABLE_VR_BROWSE'] = True
    _login(client, app, member)

    def uuids(query=''):
        resp = client.get(f'/api/vr/catalog?per_page=200{query}')
        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        return {row['uuid'] for row in (body.get('games') or body.get('items') or [])}

    assert game.uuid not in uuids()
    db_session.add(GameVrProfile(game_uuid=game.uuid, kind='injector', profile_url='https://example.invalid/p'))
    db_session.commit()
    assert game.uuid in uuids()
    assert game.uuid in uuids('&vr_compat=injector_profile')
    assert game.uuid not in uuids('&vr_compat=native_vr')
