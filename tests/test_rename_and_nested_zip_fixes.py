"""Regression tests: rename ordering, rename-plan checks, record repointing,
and zip-in-zip ROM packs."""

import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, GameUpdate, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.disk_rename import (
    apply_rename_plan,
    build_rename_plan,
    validate_plan_for_game,
)
from oneirodex.utils.rom_archive import resolve_playable_rom_path


def _game_dir(root: Path, name: str, media: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    if media:
        (folder / media).write_bytes(b'x')
    return folder


# --- rename ordering -------------------------------------------------------

def test_root_and_media_rename_both_succeed(app, tmp_path):
    lib = tmp_path / 'lib'
    folder = _game_dir(lib, 'zelda_v1 (USA)', 'zelda_v1 (USA).iso')
    plan = build_rename_plan(str(folder), title='Zelda', rename_top_level_media=True)
    assert {item['kind'] for item in plan} == {'root_folder', 'top_level_media'}

    with app.app_context():
        results = apply_rename_plan(plan, [str(lib)])

    assert all(r['ok'] for r in results), results
    assert (lib / 'Zelda' / 'Zelda.iso').is_file()
    assert not folder.exists()


def test_media_listed_before_root_still_works(app, tmp_path):
    lib = tmp_path / 'lib'
    folder = _game_dir(lib, 'zelda_v1 (USA)', 'zelda_v1 (USA).iso')
    plan = list(reversed(build_rename_plan(str(folder), title='Zelda', rename_top_level_media=True)))

    with app.app_context():
        results = apply_rename_plan(plan, [str(lib)])

    assert all(r['ok'] for r in results), results
    assert (lib / 'Zelda' / 'Zelda.iso').is_file()


def test_rename_refuses_the_library_root_as_source(app, tmp_path):
    lib = tmp_path / 'lib'
    lib.mkdir()
    plan = [{'kind': 'root_folder', 'from_path': str(lib), 'to_path': str(lib / 'x')}]
    with app.app_context():
        results = apply_rename_plan(plan, [str(lib)])
    assert results[0]['ok'] is False
    assert lib.is_dir()


# --- plan validation -------------------------------------------------------

def test_preview_plan_validates_for_its_game(tmp_path):
    folder = _game_dir(tmp_path / 'lib', 'zelda_v1 (USA)', 'zelda_v1 (USA).iso')
    plan = build_rename_plan(str(folder), title='Zelda', rename_top_level_media=True)
    assert validate_plan_for_game(plan, str(folder)) == []


def test_letter_bucket_move_validates(tmp_path):
    folder = _game_dir(tmp_path / 'lib' / '_z', 'old name')
    plan = build_rename_plan(str(folder), title='Barony', move_letter_bucket=True)
    assert plan[0]['to_path'].endswith(str(Path('_b') / 'Barony'))
    assert validate_plan_for_game(plan, str(folder)) == []


def test_plan_for_another_game_is_rejected(tmp_path):
    lib = tmp_path / 'lib'
    mine = _game_dir(lib, 'Mine')
    other = _game_dir(lib, 'Other')
    plan = [{'kind': 'root_folder', 'from_path': str(other), 'to_path': str(lib / 'Renamed')}]
    assert validate_plan_for_game(plan, str(mine))


def test_plan_moving_folder_elsewhere_is_rejected(tmp_path):
    lib = tmp_path / 'lib'
    mine = _game_dir(lib, 'Mine')
    plan = [{'kind': 'root_folder', 'from_path': str(mine), 'to_path': str(lib / 'deep' / 'Mine')}]
    assert validate_plan_for_game(plan, str(mine))


def test_plan_with_unsanitized_name_is_rejected(tmp_path):
    lib = tmp_path / 'lib'
    mine = _game_dir(lib, 'Mine')
    plan = [{'kind': 'root_folder', 'from_path': str(mine), 'to_path': str(lib / 'bad:name?')}]
    assert validate_plan_for_game(plan, str(mine))


def test_media_from_outside_the_game_is_rejected(tmp_path):
    lib = tmp_path / 'lib'
    mine = _game_dir(lib, 'Mine')
    other = _game_dir(lib, 'Other', 'other.iso')
    plan = [{'kind': 'top_level_media', 'from_path': str(other / 'other.iso'), 'to_path': str(mine / 'Mine.iso')}]
    assert validate_plan_for_game(plan, str(mine))


# --- routes: records follow the folder -------------------------------------

@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'rename_admin_{uid[:8]}',
        email=f'rename_admin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def library_game(db_session, tmp_path):
    lib_dir = tmp_path / 'lib'
    folder = _game_dir(lib_dir, 'zelda_v1 (USA)', 'zelda_v1 (USA).iso')
    (folder / 'update.zip').write_bytes(b'u')
    library = Library(
        name=f'Rename Lib {uuid4().hex[:8]}',
        image_url='/static/library_test.jpg',
        platform=LibraryPlatform.PCWIN,
        display_order=1,
    )
    db_session.add(library)
    db_session.commit()
    game = Game(uuid=str(uuid4()), name='Zelda', library_uuid=library.uuid, full_disk_path=str(folder))
    db_session.add(game)
    db_session.commit()
    update = GameUpdate(uuid=str(uuid4()), game_uuid=game.uuid, file_path=str(folder / 'update.zip'))
    db_session.add(update)
    db_session.commit()
    with patch(
        'oneirodex.routes_apis.library_tools.get_allowed_base_directories',
        return_value=[str(lib_dir)],
    ):
        yield lib_dir, folder, game, update


def _stored_path(game):
    return db.session.execute(select(Game.full_disk_path).filter_by(uuid=game.uuid)).scalar_one()


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_rename_apply_moves_game_and_update_records(client, db_session, admin_user, library_game):
    lib_dir, folder, game, update = library_game
    _login(client, admin_user)
    plan = build_rename_plan(str(folder), title='Zelda', rename_top_level_media=True)

    response = client.post('/api/library_tools/rename/apply', json={'game_uuid': game.uuid, 'plan': plan})

    assert response.status_code == 200, response.get_data(as_text=True)
    db.session.expire_all()
    assert _stored_path(game) == str(lib_dir / 'Zelda')
    stored = db.session.execute(select(GameUpdate).filter_by(uuid=update.uuid)).scalar_one()
    assert stored.file_path == str(lib_dir / 'Zelda' / 'update.zip')
    assert (lib_dir / 'Zelda' / 'Zelda.iso').is_file()


def test_rename_apply_rejects_a_plan_for_another_folder(client, db_session, admin_user, library_game):
    lib_dir, folder, game, _ = library_game
    other = _game_dir(lib_dir, 'Other Game')
    _login(client, admin_user)
    plan = [{'kind': 'root_folder', 'from_path': str(other), 'to_path': str(lib_dir / 'Hijacked')}]

    response = client.post('/api/library_tools/rename/apply', json={'game_uuid': game.uuid, 'plan': plan})

    assert response.status_code == 400
    assert other.is_dir()
    db.session.expire_all()
    assert _stored_path(game) == str(folder)


def test_doctor_rename_repoints_the_game(client, db_session, admin_user, library_game):
    lib_dir, folder, game, _ = library_game
    _login(client, admin_user)

    response = client.post(
        '/api/library_tools/doctor/apply_renames',
        json={'rows': [{'path': str(folder), 'cleaned_name': 'Zelda'}]},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert (lib_dir / 'Zelda').is_dir()
    db.session.expire_all()
    assert _stored_path(game) == str(lib_dir / 'Zelda')


# --- zip-in-zip ------------------------------------------------------------

def _nested_pack(tmp_path: Path, inner_member: str, payload: bytes) -> Path:
    inner = tmp_path / 'inner.zip'
    with zipfile.ZipFile(inner, 'w') as zf:
        zf.writestr(inner_member, payload)
    outer = tmp_path / 'outer.zip'
    with zipfile.ZipFile(outer, 'w') as zf:
        zf.write(inner, arcname='pack/inner.zip')
    return outer


def test_console_pack_unwraps_the_inner_zip(tmp_path):
    outer = _nested_pack(tmp_path, 'deep/Hero.gba', b'GBAROM')
    path, name = resolve_playable_rom_path(str(outer), cache_dir=str(tmp_path / 'cache'), platform='GBA')
    assert name == 'Hero.gba'
    assert Path(path).read_bytes() == b'GBAROM'


def test_arcade_pack_keeps_the_inner_zip_as_the_rom(tmp_path):
    outer = _nested_pack(tmp_path, 'game.bin', b'ARCADE')
    _, name = resolve_playable_rom_path(str(outer), cache_dir=str(tmp_path / 'cache'), platform='ARCADE')
    assert name == 'inner.zip'
