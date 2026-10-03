"""Cheat-file limits (LOW: no per-file or per-game cap) and the save-read error leak.

``routes_apis/emulator_saves.py`` answered ``Failed to read save: {exc}`` and an
OSError carries the on-disk path. ``store_cheat_file`` / ``create_cheat_file``
wrote whatever they were given, as many files as they were given.
"""

from __future__ import annotations

import os
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
# the sum across games, and the count-then-write race
# --------------------------------------------------------------------------

def test_storage_across_all_games_is_bounded(app, tmp_path, monkeypatch):
    """200 x 1 MB per game is not a bound when a member can reach hundreds of games."""
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    monkeypatch.setitem(app.config, 'CHEAT_STORAGE_MAX_BYTES', 100)
    first, second, third = (str(uuid4()) for _ in range(3))
    with app.app_context():
        store_cheat_file(first, _upload('a.cht', b'x' * 40))
        store_cheat_file(second, _upload('a.cht', b'x' * 40))
        with pytest.raises(CheatLimitError) as exc:
            store_cheat_file(third, _upload('a.cht', b'x' * 40))
        assert exc.value.code == 'conflict'
        assert 'storage' in str(exc.value).lower()
        assert not list((tmp_path / third).glob('*')), 'a refused upload leaves nothing behind'

        # The same bound applies to easy-create.
        with pytest.raises(CheatLimitError):
            create_cheat_file(third, name='more', codes=[{'code': 'A' * 80}])

        # A file that still fits is fine, and replacing counts only its growth.
        store_cheat_file(third, _upload('small.cht', b'x' * 20))
        store_cheat_file(first, _upload('a.cht', b'y' * 40))
        with pytest.raises(CheatLimitError):
            store_cheat_file(first, _upload('a.cht', b'y' * 90))
        assert (tmp_path / first / 'a.cht').read_bytes() == b'y' * 40, 'a refused replacement keeps the old file'

        # Deleting frees room.
        delete_cheat_file(second, 'a.cht')
        store_cheat_file(third, _upload('other.cht', b'x' * 40))


def test_the_storage_bound_defaults_without_configuration(app, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    monkeypatch.setitem(app.config, 'CHEAT_STORAGE_MAX_BYTES', 0)
    with app.app_context():
        assert emulator_cheats._storage_limit() == emulator_cheats.MAX_CHEAT_STORAGE_BYTES == 256 * 1024 * 1024
    monkeypatch.setitem(app.config, 'CHEAT_STORAGE_MAX_BYTES', 'not a number')
    with app.app_context():
        assert emulator_cheats._storage_limit() == emulator_cheats.MAX_CHEAT_STORAGE_BYTES


@pytest.mark.parametrize('raw', ['256MB', '1e9', '0x10', '-5'])
def test_a_malformed_storage_limit_in_the_environment_is_ignored_not_fatal(raw, monkeypatch, caplog):
    """`int(os.getenv(...))` ran at `import config`: a typo stopped the app from
    starting without naming the variable."""
    import config

    monkeypatch.setenv('CHEAT_STORAGE_MAX_BYTES', raw)
    with caplog.at_level('WARNING'):
        assert config._env_int('CHEAT_STORAGE_MAX_BYTES') == 0
    assert 'CHEAT_STORAGE_MAX_BYTES' in caplog.text
    monkeypatch.setenv('CHEAT_STORAGE_MAX_BYTES', ' 1048576 ')
    assert config._env_int('CHEAT_STORAGE_MAX_BYTES') == 1048576


def test_concurrent_uploads_cannot_exceed_the_per_game_cap(app, tmp_path, monkeypatch):
    """``_ensure_room`` was a bare count: N threads all saw room and all wrote."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    monkeypatch.setattr(emulator_cheats, 'MAX_CHEAT_FILES_PER_GAME', 5)
    game_uuid = str(uuid4())
    real_count = emulator_cheats._count_cht

    def slow_count(folder):
        import time

        found = real_count(folder)
        time.sleep(0.02)  # widen the check-to-write window the race lives in
        return found

    monkeypatch.setattr(emulator_cheats, '_count_cht', slow_count)

    def upload(index):
        with app.app_context():
            try:
                store_cheat_file(game_uuid, _upload(f'race{index}.cht', b'cheats = 0\n'))
                return True
            except CheatLimitError:
                return False

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(upload, range(24)))
    assert sum(results) == 5
    assert len(list((tmp_path / game_uuid).glob('*.cht'))) == 5
    assert not list((tmp_path / game_uuid).glob('*.tmp-*'))


def test_only_one_writer_is_ever_between_the_check_and_the_write(app, tmp_path, monkeypatch):
    """The caps hold only if check-then-write is one step: pin the lock itself,
    not just the end state."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path))
    inside, peak, guard = [0], [0], threading.Lock()
    real_write = emulator_cheats._write_atomic

    def tracked_write(*args, **kwargs):
        # The in-lock check runs just before this; overlapping writes mean the
        # lock is gone. (store_cheat_file also pre-checks, unlocked, to refuse
        # early before reading the body, so the check itself is not counted.)
        with guard:
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
        try:
            time.sleep(0.01)
            return real_write(*args, **kwargs)
        finally:
            with guard:
                inside[0] -= 1

    monkeypatch.setattr(emulator_cheats, '_write_atomic', tracked_write)

    def upload(index):
        with app.app_context():
            store_cheat_file(str(uuid4()), _upload(f'p{index}.cht', b'cheats = 0\n'))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(upload, range(16)))
    assert peak[0] == 1


_CHILD_UPLOAD = r'''
import os, sys, time
from io import BytesIO
from flask import Flask
from werkzeug.datastructures import FileStorage
from oneirodex.utils import emulator_cheats as ec

root, game, name, size, start = sys.argv[1:6]
app = Flask('cheat-worker')
app.config['EMULATOR_CHEATS_PATH'] = root
app.config['CHEAT_STORAGE_MAX_BYTES'] = int(os.environ['CHEAT_LIMIT'])
ec.MAX_CHEAT_FILES_PER_GAME = int(os.environ['CHEAT_PER_GAME'])

def slow(fn):
    def inner(*args):
        found = fn(*args)
        time.sleep(0.05)  # widen the check-to-write window the race lives in
        return found
    return inner

ec._count_cht, ec._storage_used = slow(ec._count_cht), slow(ec._storage_used)
while not os.path.exists(start):
    time.sleep(0.005)
with app.app_context():
    try:
        ec.store_cheat_file(game, FileStorage(stream=BytesIO(b'x' * int(size)), filename=name))
        print('ok')
    except ec.CheatLimitError:
        print('refused')
'''


def _race_in_processes(tmp_path, jobs, *, per_game, limit):
    """Run each (game, name, size) upload in its own Python process, all
    released at once, the way two server workers would race."""
    import subprocess
    import sys
    from pathlib import Path

    repo = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ, CHEAT_PER_GAME=str(per_game), CHEAT_LIMIT=str(limit),
               PYTHONPATH=repo + os.pathsep + os.environ.get('PYTHONPATH', ''))
    env.setdefault('SECRET_KEY', 'cheat-race-test')
    script, start = tmp_path / 'child.py', tmp_path / 'go'
    script.write_text(_CHILD_UPLOAD, encoding='utf-8')
    root = tmp_path / 'cheats'
    children = [
        subprocess.Popen([sys.executable, str(script), str(root), game, name, str(size), str(start)],
                         env=env, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for game, name, size in jobs
    ]
    import time

    time.sleep(3)  # let every child finish importing before the start signal
    start.write_text('go')
    outcomes = []
    for child in children:
        out, err = child.communicate(timeout=120)
        assert child.returncode == 0, err[-2000:]
        outcomes.append(out.strip().splitlines()[-1])
    return root, outcomes


def test_worker_processes_racing_for_the_last_slots_get_exactly_the_cap(tmp_path):
    """Separate processes passed the same per-game check: the cap was overshot,
    or (with the old re-count) every racer backed out of a slot that was free."""
    game = str(uuid4())
    root, outcomes = _race_in_processes(
        tmp_path, [(game, f'race{index}.cht', 10) for index in range(6)], per_game=3, limit=10**9)
    assert outcomes.count('ok') == 3
    assert len(list((root / game).glob('*.cht'))) == 3


def test_worker_processes_replacing_files_cannot_push_storage_past_the_limit(tmp_path):
    """Each worker grows its own existing file; together they passed the same total."""
    games = [str(uuid4()) for _ in range(5)]
    root = tmp_path / 'cheats'
    for game in games:
        (root / game).mkdir(parents=True)
        (root / game / 'mine.cht').write_bytes(b'x' * 50)
    root, outcomes = _race_in_processes(
        tmp_path, [(game, 'mine.cht', 150) for game in games], per_game=200, limit=600)
    total = sum(p.stat().st_size for p in root.rglob('*.cht'))
    assert total <= 600
    assert outcomes.count('ok') == 3, 'room for exactly three of the five 100-byte growths'


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


def _user(db_session, role='admin'):
    tag = uuid4().hex[:8]
    user = User(
        name=f'u-{tag}', email=f'u-{tag}@example.com', password_hash='unused',
        role=role, user_id=str(uuid4()), state=True,
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


def test_children_cannot_mutate_cheats(client, app, db_session, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path / 'cheats'))
    game = _game(db_session, tmp_path)
    url = f'/api/games/{game.uuid}/cheats'

    _login(client, _user(db_session, role='child'))
    refused = client.post(url, json={'name': 'child', 'codes': [{'code': 'AA'}]})
    assert refused.status_code == 403

def test_members_can_mutate_cheats(client, app, db_session, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'EMULATOR_CHEATS_PATH', str(tmp_path / 'cheats'))
    game = _game(db_session, tmp_path)
    _login(client, _user(db_session, role='user'))
    allowed = client.post(
        f'/api/games/{game.uuid}/cheats',
        json={'name': 'member', 'codes': [{'code': 'AA'}]},
    )
    assert allowed.status_code == 201, allowed.get_json()


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
