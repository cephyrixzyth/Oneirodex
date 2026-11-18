"""INSP-43 / H4b: the arcade launch profile.

ARCADE ships catalog-only; choosing a core in Admin → Emulators is the
operator's opt-in that makes the shelf companion-playable. ``input_family``
says how the cabinet was driven so the companion can pick a RetroArch remap.
No ROMs, no MAME sets, no file paths anywhere in this slice.
"""
from __future__ import annotations
from tests.fixtures.native_client import served_client

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Game, Library, User
from oneirodex.platform import (
    ARCADE_COMPANION_CORES,
    CATALOG_ONLY_PLATFORMS,
    Emulator,
    LibraryPlatform,
    arcade_core_override_configured,
    mapped_core_ids,
    platform_emulator_mapping,
    play_mode_for_platform,
)
from oneirodex.utils.secondary_scrapers import game_card_flags, game_input_family


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
def cabinet(db_session, tmp_path):
    lib = Library(name=f'Arcade_{uuid4().hex[:6]}', platform=LibraryPlatform.ARCADE)
    db_session.add(lib)
    db_session.flush()
    row = Game(uuid=str(uuid4()), name='Tempest', library_uuid=lib.uuid, full_disk_path=str(tmp_path / 'tempest'))
    db_session.add(row)
    db_session.commit()
    return row


def test_arcade_offers_cores_but_stays_catalog_until_one_is_chosen(app, db_session):
    from oneirodex.utils.emulator_profiles import resolve_emulators_for_platform, set_emulator_profiles

    # The cores are offered to the operator …
    assert ARCADE_COMPANION_CORES == (Emulator.MAME2003_PLUS, Emulator.MAME)
    assert resolve_emulators_for_platform('ARCADE')['emulators'] == ['mame2003_plus', 'mame']
    # … but never through the platform mapping: ARCADE is a locked, no-WASM
    # platform, and a mapped core is what makes a browser session look possible.
    assert platform_emulator_mapping[LibraryPlatform.ARCADE] == []
    assert mapped_core_ids('ARCADE') == []
    assert 'ARCADE' in CATALOG_ONLY_PLATFORMS
    with app.app_context():
        assert arcade_core_override_configured() is False
        assert play_mode_for_platform('ARCADE') == 'catalog'
        # … and choosing one is the operator's opt-in.
        set_emulator_profiles({'ARCADE': Emulator.MAME.value})
        assert arcade_core_override_configured() is True
        assert play_mode_for_platform('ARCADE') == 'companion'
        # The lock does not lift for anything else in the set.
        assert play_mode_for_platform('SWITCH') == 'catalog'
        assert play_mode_for_platform('NEOGEO') == 'catalog'
        set_emulator_profiles({'ARCADE': None})
        assert play_mode_for_platform('ARCADE') == 'catalog'


def test_input_family_is_stored_read_and_validated(client, app, db_session, librarian, member, cabinet):
    assert game_input_family(cabinet) is None
    assert game_card_flags(cabinet)['input_family'] is None

    _login(client, app, librarian)
    url = f'/api/games/{cabinet.uuid}/input_family'
    resp = client.patch(url, json={'input_family': 'spinner'})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body['input_family'] == 'spinner' and 'trackball' in body['families']
    db_session.refresh(cabinet)
    assert game_card_flags(cabinet)['input_family'] == 'spinner'

    assert client.patch(url, json={'input_family': None}).get_json()['input_family'] is None
    assert client.patch(url, json={'input_family': 'dance mat'}).status_code == 422
    assert client.patch(url, json={'rom_path': 'D:/sets/tempest.zip'}).status_code == 422
    assert client.patch(f'/api/games/{uuid4()}/input_family', json={'input_family': 'joystick'}).status_code == 404

    member_client = served_client(app)
    _login(member_client, app, member)
    assert member_client.patch(url, json={'input_family': 'lightgun'}).status_code in (302, 403)
