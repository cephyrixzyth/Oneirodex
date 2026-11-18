"""Emulator .cht library helpers."""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

from oneirodex.runtime_native.emulator_mutations import EmulatorMutationData
from oneirodex.utils.emulator_cheats import (
    build_cht_text,
    create_cheat_file,
    delete_cheat_file,
    list_cheat_files,
    read_cheat_file,
    store_cheat_file,
)


def test_store_list_read_delete_cheat(app, tmp_path, monkeypatch):
    game_uuid = str(uuid4())
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))

    with app.app_context():
        storage = FileStorage(
            stream=BytesIO(b'cheat "inf"\n'),
            filename='inf codes.cht',
            content_type='text/plain',
        )
        stored = store_cheat_file(game_uuid, storage)
        assert stored['name'].endswith('.cht')
        assert stored['size'] > 0

        listed = list_cheat_files(game_uuid)
        assert len(listed) == 1
        assert listed[0]['name'] == stored['name']

        raw = read_cheat_file(game_uuid, stored['name'])
        assert b'inf' in raw

        delete_cheat_file(game_uuid, stored['name'])
        assert list_cheat_files(game_uuid) == []


def test_store_rejects_non_cht(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    with app.app_context():
        storage = FileStorage(
            stream=BytesIO(b'nope'),
            filename='codes.txt',
            content_type='text/plain',
        )
        with pytest.raises(ValueError, match='\\.cht'):
            store_cheat_file(str(uuid4()), storage)


def test_invalid_game_uuid_rejected(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    with app.app_context():
        with pytest.raises(ValueError, match='Invalid game UUID'):
            list_cheat_files('not-a-uuid')


def test_build_cht_text_basic():
    body = build_cht_text(
        name='Infinite Lives',
        codes=[{'desc': 'Inf lives', 'code': 'AABB-CCDD'}],
        dialect='game_genie',
    )
    assert 'cheats = 1' in body
    assert 'cheat0_desc = "GG-style: Inf lives"' in body
    assert 'cheat0_code = "AABB-CCDD"' in body
    assert 'cheat0_enable = false' in body


def test_build_cht_dialect_desc_prefixes():
    """Desc prefixes use UI capability labels (Raw / GG / AR / GS), not Class-A names."""
    raw = build_cht_text(
        name='Raw Code',
        codes=[{'desc': 'Patch', 'code': 'DEAD'}],
        dialect='raw',
    )
    assert 'cheat0_desc = "Raw: Patch"' in raw

    gg = build_cht_text(
        name='GG',
        codes=[{'desc': 'Lives', 'code': 'AABB'}],
        dialect='game_genie',
    )
    assert 'cheat0_desc = "GG-style: Lives"' in gg
    assert 'Game Genie' not in gg

    ar = build_cht_text(
        name='AR',
        codes=[{'desc': 'HP', 'code': '01 02'}],
        dialect='action_replay',
    )
    assert 'cheat0_desc = "AR-style: HP"' in ar
    assert 'Action Replay' not in ar

    gs = build_cht_text(
        name='GS',
        codes=[{'desc': 'Cash', 'code': '800966B4 FFFF'}],
        dialect='gameshark',
    )
    assert 'cheat0_desc = "GS-style: Cash"' in gs
    assert 'Gameshark' not in gs
    assert 'GameShark' not in gs


def test_build_cht_normalizes_spaced_codes():
    body = build_cht_text(
        name='Max Cash',
        codes=[{'code': '800966B4 FFFF'}],
        dialect='gameshark',
    )
    assert 'cheat0_code = "800966B4+FFFF"' in body
    assert 'cheat0_desc = "GS-style: Max Cash"' in body


def test_create_cheat_file_writes_under_uuid(app, tmp_path, monkeypatch):
    game_uuid = str(uuid4())
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))

    with app.app_context():
        row = create_cheat_file(
            game_uuid,
            name='My Codes',
            codes=[
                {'desc': 'Inf HP', 'code': '01 02'},
                {'code': 'DEADBEEF'},
            ],
            dialect='action_replay',
        )
        assert row['name'] == 'My_Codes.cht'
        assert row['created'] is True
        assert row['dialect'] == 'action_replay'
        assert row['url'] == f'/api/games/{game_uuid}/cheats/My_Codes.cht'

        dest = Path(tmp_path) / game_uuid / 'My_Codes.cht'
        assert dest.is_file()
        text = dest.read_text(encoding='utf-8')
        assert 'cheats = 2' in text
        assert 'cheat0_desc = "AR-style: Inf HP"' in text
        assert 'cheat0_code = "01+02"' in text
        assert 'cheat1_desc = "AR-style: Code 2"' in text
        assert 'cheat1_code = "DEADBEEF"' in text
        assert 'Action Replay' not in text
        assert list_cheat_files(game_uuid)[0]['name'] == 'My_Codes.cht'


def test_create_rejects_empty_codes(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    with app.app_context():
        with pytest.raises(ValueError, match='codes required'):
            create_cheat_file(str(uuid4()), name='x', codes=[])


def test_create_rejects_bad_dialect(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    with app.app_context():
        with pytest.raises(ValueError, match='dialect must be'):
            create_cheat_file(
                str(uuid4()),
                name='x',
                codes=[{'code': '1'}],
                dialect='trainer',
            )


def test_create_path_acl_uuid_and_traversal(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    outside = tmp_path / 'outside.cht'
    outside.write_text('sentinel\n', encoding='utf-8')

    with app.app_context():
        with pytest.raises(ValueError, match='Invalid game UUID'):
            create_cheat_file('../escape', name='x', codes=[{'code': '1'}])

        with pytest.raises(ValueError, match='Invalid game UUID'):
            create_cheat_file('not-a-uuid', name='x', codes=[{'code': '1'}])

        game_uuid = str(uuid4())
        # Path traversal in name is stripped by secure_filename → safe write under uuid dir
        row = create_cheat_file(
            game_uuid,
            name='../../etc/passwd.cht',
            codes=[{'code': 'AA'}],
        )
        written = Path(tmp_path) / game_uuid / row['name']
        assert written.is_file()
        assert written.resolve().is_relative_to(Path(tmp_path).resolve())
        assert not (tmp_path / 'etc').exists()
        assert outside.read_text(encoding='utf-8') == 'sentinel\n'

        # Traversal-style read/delete filenames cannot escape the uuid folder
        with pytest.raises((ValueError, FileNotFoundError)):
            read_cheat_file(game_uuid, '../../../outside.cht')


def test_cheat_surface_is_pc_wand_for_native_pc_and_retroarch_otherwise(app):
    """Wave 19 GM: NATIVE_PC games use the PC trainer surface, not .cht files."""
    pc_game = SimpleNamespace(
        library=SimpleNamespace(platform=SimpleNamespace(name='PCWIN')),
    )
    nes_game = SimpleNamespace(
        library=SimpleNamespace(platform=SimpleNamespace(name='NES')),
    )
    data = EmulatorMutationData()
    assert data.cheat_surface(pc_game) == 'pc_wand'
    assert data.cheat_surface(nes_game) == 'retroarch'
