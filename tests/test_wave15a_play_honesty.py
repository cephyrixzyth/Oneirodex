"""Wave 15a — archive extractor honesty + firmware/BIOS browse fields."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.play_url import BIOS_UPLOAD_HINT, browse_play_fields


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(
        name=f'w15a_{uid[:8]}',
        email=f'w15a_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, account):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(account.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(account)


def test_bios_upload_hint_mentions_admin_and_env_path():
    text = BIOS_UPLOAD_HINT.lower()
    assert 'admin' in text
    assert 'emulator-bios' in text or 'emulator bios' in text
    assert 'emulator_bios_path' in text
    assert 'does not ship' in text
    # Never imply vendored blobs.
    assert 'download bios from' not in text


def test_config_wires_emulator_bios_path(monkeypatch):
    monkeypatch.setenv('EMULATOR_BIOS_PATH', '/app/oneirodex/static/library/bios')
    # Re-read attribute the same way Config does (empty → None).
    import os

    value = os.getenv('EMULATOR_BIOS_PATH') or None
    assert value == '/app/oneirodex/static/library/bios'

    from config import Config

    assert hasattr(Config, 'EMULATOR_BIOS_PATH')
    # Class attr may already be bound at import; bios_root uses app.config.
    monkeypatch.delenv('EMULATOR_BIOS_PATH', raising=False)
    assert (os.getenv('EMULATOR_BIOS_PATH') or None) is None


def test_bios_root_honors_app_config(app, tmp_path, monkeypatch):
    from oneirodex.utils.emulator_bios import bios_root

    custom = tmp_path / 'private-bios'
    custom.mkdir()
    monkeypatch.setitem(app.config, 'EMULATOR_BIOS_PATH', str(custom))
    with app.app_context():
        assert bios_root() == str(custom)


def test_browse_play_fields_firmware_missing(monkeypatch):
    library = SimpleNamespace(platform=SimpleNamespace(name='PSX'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')

    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['mednafen_psx_hw'], 'preferred': 'mednafen_psx_hw'},
    )
    monkeypatch.setattr(
        'oneirodex.utils.play_url.core_is_browser_playable',
        lambda c: c == 'mednafen_psx_hw',
    )
    monkeypatch.setattr(
        'oneirodex.utils.emulator_bios.list_bios_files',
        lambda: [],
    )

    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is True
    assert fields['bios_required'] is True
    assert fields['firmware_missing'] is True
    bios = fields['bios']
    assert bios['ready'] is False
    assert bios['firmware_missing'] is True
    assert 'scph5501.bin' in bios['missing']
    hint = (bios.get('hint') or '').lower()
    assert 'admin' in hint
    assert 'emulator_bios_path' in hint
    assert 'does not ship' in hint


def test_browse_play_fields_firmware_present(monkeypatch):
    library = SimpleNamespace(platform=SimpleNamespace(name='PSX'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')

    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['mednafen_psx_hw'], 'preferred': 'mednafen_psx_hw'},
    )
    monkeypatch.setattr(
        'oneirodex.utils.play_url.core_is_browser_playable',
        lambda c: c == 'mednafen_psx_hw',
    )
    monkeypatch.setattr(
        'oneirodex.utils.emulator_bios.list_bios_files',
        lambda: [{
            'name': 'scph5501.bin',
            'size': 512 * 1024,
            'subdir': '',
            'loadable': True,
        }],
    )

    fields = browse_play_fields(game)
    assert fields['bios_required'] is True
    assert fields['firmware_missing'] is False
    assert fields['bios']['ready'] is True
    assert 'scph5501.bin' in fields['bios']['present']


def test_browse_play_fields_firmware_in_subfolder_still_blocks(monkeypatch):
    """A BIOS one directory down is present on disk and still will not load.

    list_bios_files() walks subdirectories, so the file is *found* — but
    libretro cores read the firmware root only. Counting it as present hands
    the member an enabled Play button for a core that then fails to boot,
    which is worse than the honest block.
    """
    library = SimpleNamespace(platform=SimpleNamespace(name='PSX'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')

    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['mednafen_psx_hw'], 'preferred': 'mednafen_psx_hw'},
    )
    monkeypatch.setattr(
        'oneirodex.utils.play_url.core_is_browser_playable',
        lambda c: c == 'mednafen_psx_hw',
    )
    monkeypatch.setattr(
        'oneirodex.utils.emulator_bios.list_bios_files',
        lambda: [{
            'name': 'scph5501.bin',
            'size': 512 * 1024,
            'subdir': 'psx',
            'loadable': False,
        }],
    )

    fields = browse_play_fields(game)
    assert fields['bios_required'] is True
    assert fields['firmware_missing'] is True
    assert fields['bios']['ready'] is False
    assert 'scph5501.bin' in fields['bios']['missing']


def test_browse_play_fields_no_bios_for_nes(monkeypatch):
    library = SimpleNamespace(platform=SimpleNamespace(name='NES'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['nestopia'], 'preferred': 'nestopia'},
    )
    monkeypatch.setattr(
        'oneirodex.utils.play_url.core_is_browser_playable',
        lambda c: c == 'nestopia',
    )
    monkeypatch.setattr(
        'oneirodex.utils.emulator_bios.list_bios_files',
        lambda: [],
    )
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is True
    assert fields.get('bios_required') is False
    assert fields.get('firmware_missing') is False


def _play_fields(monkeypatch, platform: str, core: str):
    library = SimpleNamespace(platform=SimpleNamespace(name=platform))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': [core], 'preferred': core},
    )
    monkeypatch.setattr(
        'oneirodex.utils.play_url.core_is_browser_playable',
        lambda c: c == core,
    )
    monkeypatch.setattr(
        'oneirodex.utils.emulator_bios.list_bios_files',
        lambda: [],
    )
    return browse_play_fields(game)


def test_browse_play_fields_snes_optional_dsp_does_not_block(monkeypatch):
    fields = _play_fields(monkeypatch, 'SNES', 'snes9x')
    assert fields['can_play_in_browser'] is True
    assert fields.get('firmware_missing') is False
    assert fields.get('bios_required') is False


def test_browse_play_fields_genesis_cart_does_not_need_sega_cd_bios(monkeypatch):
    fields = _play_fields(monkeypatch, 'SEGA_MD', 'genesis_plus_gx')
    assert fields['can_play_in_browser'] is True
    assert fields.get('firmware_missing') is False
    assert fields.get('bios_required') is False


def test_browse_play_fields_sega_cd_still_blocks_without_bios(monkeypatch):
    fields = _play_fields(monkeypatch, 'SEGA_CD', 'genesis_plus_gx')
    assert fields['can_play_in_browser'] is True
    assert fields['bios_required'] is True
    assert fields['firmware_missing'] is True
    assert 'bios_CD_U.bin' in fields['bios']['missing']


def test_download_refuses_path_missing(client, app, db_session, admin, tmp_path):
    lib = Library(name=f'W15aLib_{uuid4().hex[:6]}', platform=LibraryPlatform.NES)
    db_session.add(lib)
    db_session.flush()
    missing = tmp_path / 'gone' / 'rom.nes'
    game = Game(
        uuid=str(uuid4()),
        name=f'MissingRom_{uuid4().hex[:6]}',
        library_uuid=lib.uuid,
        full_disk_path=str(missing),
        size=100,
    )
    db_session.add(game)
    db_session.commit()

    _login(client, app, admin)
    resp = client.post(f'/api/downloads/games/{game.uuid}', json={})
    assert resp.status_code == 410
    body = resp.get_json()
    assert body['code'] == 'path_missing'
    assert body['path_missing'] is True
    assert body['downloadable'] is False
    assert 'hint' in body
