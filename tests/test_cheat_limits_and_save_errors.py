"""Cheat-file limits (LOW: no per-file or per-game cap) and the save-read error leak.

``routes_apis/emulator_saves.py`` answered ``Failed to read save: {exc}`` and an
OSError carries the on-disk path. ``store_cheat_file`` / ``create_cheat_file``
wrote whatever they were given, as many files as they were given.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

from oneirodex.models import EmulatorSave, Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils import emulator_cheats
from oneirodex.utils.emulator_cheats import (
    MAX_CHEAT_FILE_BYTES,
    MAX_CHEAT_FILES_PER_GAME,
    CheatLimitError,
    create_cheat_file,
    delete_cheat_file,
    list_cheat_files,
    store_cheat_file,
)


def _upload(name: str, data: bytes) -> FileStorage:
    return FileStorage(stream=BytesIO(data), filename=name, content_type='text/plain')


# --------------------------------------------------------------------------
# limits (utility level)
# --------------------------------------------------------------------------

def test_limits_are_the_documented_defaults():
    assert MAX_CHEAT_FILE_BYTES == 1024 * 1024
    assert MAX_CHEAT_FILES_PER_GAME == 200


def test_upload_over_the_size_limit_is_refused_and_leaves_nothing(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    game_uuid = str(uuid4())
    with app.app_context():
        with pytest.raises(CheatLimitError) as exc:
            store_cheat_file(game_uuid, _upload('big.cht', b'x' * (MAX_CHEAT_FILE_BYTES + 1)))
        assert exc.value.code == 'payload_too_large'
        assert isinstance(exc.value, ValueError), 'older handlers still see a refusal'
        assert 'too large' in str(exc.value)
        assert list_cheat_files(game_uuid) == []
        assert [p.name for p in (tmp_path / game_uuid).iterdir()] == [], 'no partial or temp file left behind'


def test_upload_exactly_at_the_size_limit_is_accepted(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    game_uuid = str(uuid4())
    with app.app_context():
        row = store_cheat_file(game_uuid, _upload('edge.cht', b'x' * MAX_CHEAT_FILE_BYTES))
        assert row['size'] == MAX_CHEAT_FILE_BYTES


def test_easy_create_over_the_size_limit_is_refused(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    game_uuid = str(uuid4())
    with app.app_context():
        with pytest.raises(CheatLimitError) as exc:
            create_cheat_file(
                game_uuid, name='huge',
                codes=[{'desc': 'x', 'code': 'A' * (MAX_CHEAT_FILE_BYTES + 10)}],
            )
        assert exc.value.code == 'payload_too_large'
        assert list_cheat_files(game_uuid) == []


def test_per_game_file_count_is_capped_but_replacing_a_file_is_not(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    monkeypatch.setattr(emulator_cheats, 'MAX_CHEAT_FILES_PER_GAME', 3)
    game_uuid = str(uuid4())
    with app.app_context():
        for index in range(3):
            store_cheat_file(game_uuid, _upload(f'c{index}.cht', b'cheats = 0\n'))

        with pytest.raises(CheatLimitError) as exc:
            store_cheat_file(game_uuid, _upload('c3.cht', b'cheats = 0\n'))
        assert exc.value.code == 'conflict'
        assert 'maximum of 3' in str(exc.value)
        with pytest.raises(CheatLimitError):
            create_cheat_file(game_uuid, name='one more', codes=[{'code': 'AA'}])
        assert len(list_cheat_files(game_uuid)) == 3

        # Replacing an existing name never counts against the cap...
        replaced = store_cheat_file(game_uuid, _upload('c1.cht', b'cheats = 1\n'))
        assert replaced['name'] == 'c1.cht'
        assert len(list_cheat_files(game_uuid)) == 3

        # ...and deleting one frees a slot.
        delete_cheat_file(game_uuid, 'c0.cht')
        create_cheat_file(game_uuid, name='fresh', codes=[{'code': 'AA'}])
        assert len(list_cheat_files(game_uuid)) == 3


def test_the_cap_is_per_game(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    monkeypatch.setattr(emulator_cheats, 'MAX_CHEAT_FILES_PER_GAME', 1)
    first, second = str(uuid4()), str(uuid4())
    with app.app_context():
        store_cheat_file(first, _upload('a.cht', b'x'))
        store_cheat_file(second, _upload('a.cht', b'x'))
        with pytest.raises(CheatLimitError):
            store_cheat_file(first, _upload('b.cht', b'x'))


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

def _library(db_session):
    library = Library(name=f'NES {uuid4().hex[:8]}', platform=LibraryPlatform.NES, display_order=1)
    db_session.add(library)
    db_session.commit()
    return library


def _game(db_session, tmp_path):
    game = Game(
        uuid=str(uuid4()),
        name=f'Route probe {uuid4().hex[:6]}',
        library_uuid=_library(db_session).uuid,
        full_disk_path=str(tmp_path / 'g.nes'),
    )
    db_session.add(game)
    db_session.commit()
    return game


def _user(db_session):
    tag = uuid4().hex[:8]
    user = User(
        name=f'u-{tag}', email=f'u-{tag}@example.com', password_hash='unused',
        role='admin', user_id=str(uuid4()), state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True


def test_cheat_routes_answer_with_a_clear_4xx(client, app, db_session, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path / 'cheats'))
    monkeypatch.setattr(emulator_cheats, 'MAX_CHEAT_FILES_PER_GAME', 1)
    game = _game(db_session, tmp_path)
    _login(client, _user(db_session))
    url = f'/api/games/{game.uuid}/cheats'

    too_big = client.post(
        url,
        data={'file': (BytesIO(b'x' * (MAX_CHEAT_FILE_BYTES + 1)), 'big.cht')},
        content_type='multipart/form-data',
    )
    assert too_big.status_code == 413, too_big.get_json()
    body = too_big.get_json()
    assert body['error_code'] == 'payload_too_large' and 'too large' in body['error']

    created = client.post(url, json={'name': 'first', 'codes': [{'code': 'AA'}]})
    assert created.status_code == 201, created.get_json()

    full = client.post(url, json={'name': 'second', 'codes': [{'code': 'BB'}]})
    assert full.status_code == 409, full.get_json()
    assert full.get_json()['error_code'] == 'conflict'

    full_upload = client.post(
        url,
        data={'file': (BytesIO(b'cheats = 0\n'), 'third.cht')},
        content_type='multipart/form-data',
    )
    assert full_upload.status_code == 409


# --------------------------------------------------------------------------
# save read errors
# --------------------------------------------------------------------------

def test_unreadable_save_does_not_leak_the_storage_path(client, app, db_session, tmp_path, monkeypatch):
    game = _game(db_session, tmp_path)
    user = _user(db_session)
    now = datetime.now(timezone.utc)
    db_session.add(EmulatorSave(
        user_id=user.id, game_uuid=game.uuid, slot_name='slot1', filename='s.state',
        size_bytes=3, storage_path='/srv/oneirodex/saves/secret/path/s.state', encrypted=False,
        created_at=now, updated_at=now,
    ))
    db_session.commit()
    _login(client, user)

    def boom(row):
        raise PermissionError(13, 'Permission denied', '/srv/oneirodex/saves/secret/path/s.state')

    monkeypatch.setattr('oneirodex.routes_apis.emulator_saves.read_save_bytes', boom)
    resp = client.get(f'/api/games/{game.uuid}/saves/slot1')

    assert resp.status_code == 500
    body = resp.get_json()
    assert body['error'] == 'Failed to read save'
    assert body['error_code'] == 'internal'
    assert '/srv' not in resp.get_data(as_text=True)
    assert 'secret' not in resp.get_data(as_text=True)
