"""PostgreSQL races for per-member save quota and slot-count serialization."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from oneirodex import db
from oneirodex.models import EmulatorSave, EmulatorSaveGeneration, Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.emulator_saves import (
    SaveQuotaExceeded,
    SaveRevisionConflict,
    read_save_bytes,
    store_save,
)
from oneirodex.utils.save_crypto import context_for_row, maybe_decrypt


def _seed_owner_game(session):
    tag = uuid4().hex
    user = User(
        name=f'save-race-{tag[:8]}', email=f'save-race-{tag}@example.com',
        password_hash='unused', role='user', user_id=str(uuid4()), state=True,
    )
    library = Library(
        name=f'Save race {tag[:8]}', platform=LibraryPlatform.NES, display_order=1,
    )
    session.add_all([user, library])
    session.flush()
    game = Game(
        uuid=str(uuid4()), name=f'Save race {tag[:8]}', library_uuid=library.uuid,
        full_disk_path=f'/test/save-race/{tag}.nes',
    )
    session.add(game)
    session.commit()
    return user.id, game.uuid


def _race_two_writes(
    app, user_id, game_uuid, slots, payloads, expected_revisions=(None, None),
):
    barrier = Barrier(len(slots))

    def write(slot, payload, expected_revision):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                store_save(
                    user_id=user_id,
                    game_uuid=game_uuid,
                    slot_name=slot,
                    file_storage=BytesIO(payload),
                    expected_revision=expected_revision,
                )
                return 'saved'
            except SaveRevisionConflict as exc:
                return ('conflict', exc.current_revision)
            except SaveQuotaExceeded:
                return 'quota'
            except ValueError as exc:
                return str(exc)

    with ThreadPoolExecutor(max_workers=len(slots)) as pool:
        return list(pool.map(write, slots, payloads, expected_revisions))


def _assert_postgresql(app):
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('save row-lock acceptance requires PostgreSQL')


def test_concurrent_new_slots_cannot_exceed_per_game_cap(
    app, no_savepoint_db, tmp_path,
):
    _assert_postgresql(app)
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    app.config['EMULATOR_SAVES_USER_QUOTA_MB'] = 1024
    app.config['ENABLE_EMULATOR_SAVE_SYNC'] = True
    user_id, game_uuid = _seed_owner_game(no_savepoint_db)
    no_savepoint_db.add_all([
        EmulatorSave(
            user_id=user_id, game_uuid=game_uuid, slot_name=f'existing-{index}',
            filename='existing.state', size_bytes=0,
            storage_path=str(tmp_path / f'existing-{index}.save'), encrypted=False,
        )
        for index in range(9)
    ])
    no_savepoint_db.commit()

    outcomes = _race_two_writes(
        app, user_id, game_uuid, ('racer-a', 'racer-b'), (b'a', b'b'),
    )

    assert outcomes.count('saved') == 1
    assert outcomes.count(f'Maximum of 10 save slots per game') == 1
    rows = no_savepoint_db.query(EmulatorSave).filter_by(
        user_id=user_id, game_uuid=game_uuid,
    ).all()
    assert len(rows) == 10
    assert len({row.storage_path for row in rows}) == 10


def test_concurrent_uploads_cannot_bypass_aggregate_quota(
    app, no_savepoint_db, tmp_path,
):
    _assert_postgresql(app)
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    app.config['EMULATOR_SAVES_USER_QUOTA_MB'] = 1
    app.config['ENABLE_EMULATOR_SAVE_SYNC'] = True
    user_id, game_uuid = _seed_owner_game(no_savepoint_db)

    outcomes = _race_two_writes(
        app,
        user_id,
        game_uuid,
        ('quota-a', 'quota-b'),
        (b'a' * (600 * 1024), b'b' * (600 * 1024)),
    )

    assert outcomes.count('saved') == 1
    assert outcomes.count('quota') == 1
    rows = no_savepoint_db.query(EmulatorSave).filter_by(
        user_id=user_id, game_uuid=game_uuid,
    ).all()
    assert len(rows) == 1
    assert rows[0].size_bytes == 600 * 1024


def test_concurrent_stale_revision_allows_only_one_replacement(
    app, no_savepoint_db, tmp_path,
):
    _assert_postgresql(app)
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    app.config['EMULATOR_SAVES_USER_QUOTA_MB'] = 1024
    app.config['ENABLE_EMULATOR_SAVE_SYNC'] = True
    user_id, game_uuid = _seed_owner_game(no_savepoint_db)
    initial_path = tmp_path / 'committed.state'
    initial_path.write_bytes(b'initial')
    row = EmulatorSave(
        user_id=user_id, game_uuid=game_uuid, slot_name='shared-slot',
        filename='committed.state', size_bytes=7, storage_path=str(initial_path),
        encrypted=False, revision=1,
    )
    no_savepoint_db.add(row)
    no_savepoint_db.commit()

    outcomes = _race_two_writes(
        app,
        user_id,
        game_uuid,
        ('shared-slot', 'shared-slot'),
        (b'writer-a', b'writer-b'),
        expected_revisions=(1, 1),
    )

    assert outcomes.count('saved') == 1
    assert outcomes.count(('conflict', 2)) == 1
    no_savepoint_db.expire_all()
    current = no_savepoint_db.query(EmulatorSave).filter_by(id=row.id).one()
    history = no_savepoint_db.query(EmulatorSaveGeneration).filter_by(save_id=row.id).one()
    assert current.revision == 2
    assert initial_path.read_bytes() == b'initial'
    assert Path(history.storage_path).read_bytes() == b'initial'


def test_sustained_concurrent_replacements_preserve_every_committed_generation(
    app, no_savepoint_db, tmp_path,
):
    _assert_postgresql(app)
    app.config['EMULATOR_SAVES_PATH'] = str(tmp_path)
    app.config['EMULATOR_SAVES_USER_QUOTA_MB'] = 1
    app.config['ENABLE_EMULATOR_SAVE_SYNC'] = True
    user_id, game_uuid = _seed_owner_game(no_savepoint_db)

    writer_count = 4
    writes_per_writer = 8
    barrier = Barrier(writer_count)
    expected_payloads = {
        f'writer-{writer}-write-{write}'.encode()
        for writer in range(writer_count)
        for write in range(writes_per_writer)
    }

    def replace_repeatedly(writer):
        with app.app_context():
            barrier.wait(timeout=10)
            for write in range(writes_per_writer):
                store_save(
                    user_id=user_id,
                    game_uuid=game_uuid,
                    slot_name='shared-slot',
                    file_storage=BytesIO(f'writer-{writer}-write-{write}'.encode()),
                )

    with ThreadPoolExecutor(max_workers=writer_count) as pool:
        list(pool.map(replace_repeatedly, range(writer_count)))

    no_savepoint_db.expire_all()
    current = no_savepoint_db.query(EmulatorSave).filter_by(
        user_id=user_id, game_uuid=game_uuid, slot_name='shared-slot',
    ).one()
    generations = no_savepoint_db.query(EmulatorSaveGeneration).filter_by(
        save_id=current.id,
    ).all()

    assert current.revision == len(expected_payloads)
    assert len(generations) == len(expected_payloads) - 1
    all_paths = [current.storage_path, *(row.storage_path for row in generations)]
    assert len(set(all_paths)) == len(expected_payloads)
    payloads = {read_save_bytes(current)}
    payloads.update(
        maybe_decrypt(Path(row.storage_path).read_bytes(), context=context_for_row(row, owner=current))
        for row in generations
    )
    assert payloads == expected_payloads
    assert len(list(Path(tmp_path).rglob('*.save'))) == len(expected_payloads)
