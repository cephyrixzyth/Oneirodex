"""Rotation preserves shared blobs, committed writers and read-only inventory."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from oneirodex.models import EmulatorSave, EmulatorSaveGeneration, Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.runtime_native.runtime_context import runtime_config_scope
from oneirodex.utils import save_crypto
from oneirodex.utils.save_keyring import load_save_keyring
from scripts import migrate_emulator_save_keys as migration


@dataclass
class RotationCase:
    engine: object
    root: Path
    user_id: int
    game_uuid: str
    initial_ring: Path
    active_ring: Path
    config: dict


@pytest.fixture
def rotation_case(app, no_savepoint_db, tmp_path):
    root = tmp_path / 'saves'
    root.mkdir()
    keys = tmp_path / 'keys'
    keys.mkdir(mode=0o700)
    initial, active = keys / 'initial.json', keys / 'active.json'
    migration.initialize_keyring(initial, 'synthetic-rotation-secret')
    migration.rotate_keyring(initial, active)
    config = {
        'SECRET_KEY': 'synthetic-rotation-secret',
        'SAVE_KEYRING_FILE': str(active),
        'ENCRYPT_EMULATOR_SAVES': 'true',
        'ENABLE_EMULATOR_SAVE_SYNC': 'true',
        'EMULATOR_SAVES_PATH': str(root),
    }
    engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'], pool_pre_ping=True)
    try:
        with Session(engine) as db:
            owner = User(
                name='SyntheticRotationOwner', email='rotation@example.invalid',
                password_hash='unused', role='user', state=True, user_id=str(uuid4()),
            )
            library = Library(name='Synthetic Rotation', platform=LibraryPlatform.NES)
            db.add_all([owner, library])
            db.flush()
            game = Game(uuid=str(uuid4()), name='Synthetic Save', library_uuid=library.uuid)
            db.add(game)
            db.flush()
            user_id, game_uuid = owner.id, game.uuid
            db.commit()
        with runtime_config_scope(config):
            yield RotationCase(engine, root, user_id, game_uuid, initial, active, config)
    finally:
        engine.dispose()


def _seed(case, db, *, version='GTENC1', slot='slot1', path=None, plain=b'original-save'):
    path = path or case.root / (uuid4().hex + '.save')
    if version == 'GTENC1':
        payload = save_crypto.MAGIC + save_crypto.legacy_fernet(
            'synthetic-rotation-secret',
        ).encrypt(plain)
    else:
        ring = load_save_keyring(str(case.initial_ring))
        if version == 'GTENC2':
            payload = save_crypto.KEYED_MAGIC + ring.active_key_id.encode() + b':' + ring.keys[
                ring.active_key_id
            ].encrypt(plain)
        else:
            payload = save_crypto._encrypt_with_keyring(
                plain, ring,
                context=save_crypto.save_context(case.user_id, case.game_uuid, slot, path.stem),
            )
    path.write_bytes(payload)
    row = EmulatorSave(
        user_id=case.user_id, game_uuid=case.game_uuid, slot_name=slot,
        filename='state.sav', size_bytes=len(plain), storage_path=str(path),
        encrypted=True, revision=2,
    )
    db.add(row)
    db.flush()
    return row


def _read(db, row):
    owner = row if isinstance(row, EmulatorSave) else db.get(EmulatorSave, row.save_id)
    return save_crypto.maybe_decrypt(
        Path(row.storage_path).read_bytes(), context=save_crypto.context_for_row(row, owner=owner),
    )


@pytest.mark.parametrize('version', ['GTENC1', 'GTENC2'])
@pytest.mark.parametrize('alias', [False, True])
def test_rotation_preserves_both_shared_legacy_slots(rotation_case, version, alias):
    case = rotation_case
    with Session(case.engine) as db:
        first = _seed(case, db, version=version, slot='slot a')
        old_path = Path(first.storage_path)
        alternate = str(old_path)
        if alias:
            (case.root / 'alias').mkdir()
            alternate = str(case.root / 'alias') + '/../' + old_path.name
        second = EmulatorSave(
            user_id=case.user_id, game_uuid=case.game_uuid, slot_name='slot-a',
            filename='state.sav', size_bytes=13, storage_path=alternate,
            encrypted=True, revision=2,
        )
        db.add(second)
        db.commit()
        ids = first.id, second.id
        assert _read(db, first) == _read(db, second) == b'original-save'
        result = migration.migrate_rows(db, case.root, apply=True)
        assert result['failures'] == 0
        db.expire_all()
        rows = [db.get(EmulatorSave, key) for key in ids]
        assert [_read(db, row) for row in rows] == [b'original-save', b'original-save']
        assert [row.revision for row in rows] == [2, 2]
        assert len({row.storage_path for row in rows}) == 2
        assert not old_path.exists(), 'Unreferenced old ciphertext can be removed after both commits'


@pytest.mark.parametrize('alias', [False, True])
def test_rotation_preserves_shared_bound_current_and_history(rotation_case, alias):
    case = rotation_case
    with Session(case.engine) as db:
        current = _seed(case, db, version='GTENC3')
        old_path = Path(current.storage_path)
        alternate = str(old_path)
        if alias:
            (case.root / 'alias').mkdir()
            alternate = str(case.root / 'alias') + '/../' + old_path.name
        history = EmulatorSaveGeneration(
            save_id=current.id, filename='old.sav', size_bytes=13,
            storage_path=alternate, encrypted=True,
        )
        db.add(history)
        db.commit()
        current_id, history_id = current.id, history.id
        assert _read(db, current) == _read(db, history) == b'original-save'
        result = migration.migrate_rows(db, case.root, apply=True)
        assert result['failures'] == 0
        db.expire_all()
        assert _read(db, db.get(EmulatorSave, current_id)) == b'original-save'
        assert _read(db, db.get(EmulatorSaveGeneration, history_id)) == b'original-save'
        assert not old_path.exists()


def test_rotation_refreshes_a_snapshot_older_than_a_committed_writer(rotation_case):
    from io import BytesIO
    from werkzeug.datastructures import FileStorage
    from oneirodex.runtime_native.db_session import _native_session
    from oneirodex.utils.emulator_saves import store_save

    case = rotation_case
    with Session(case.engine) as seed:
        row = _seed(case, seed)
        seed.commit()
        row_id = row.id
    with Session(case.engine) as stale:
        snapshot = stale.get(EmulatorSave, row_id)
        assert _read(stale, snapshot) == b'original-save'
        with Session(case.engine) as writer:
            token = _native_session.set(writer)
            try:
                store_save(
                    user_id=case.user_id, game_uuid=case.game_uuid, slot_name='slot1',
                    file_storage=FileStorage(stream=BytesIO(b'new-committed-save'), filename='new.sav'),
                    expected_revision=2,
                )
            finally:
                _native_session.reset(token)
        result = migration.migrate_rows(stale, case.root, apply=True)
        assert result['failures'] == 0
    with Session(case.engine) as check:
        current = check.get(EmulatorSave, row_id)
        assert current.revision == 3
        assert _read(check, current) == b'new-committed-save'
        history = check.execute(select(EmulatorSaveGeneration)).scalars().all()
        assert [_read(check, row) for row in history] == [b'original-save']


def test_rotation_waits_for_the_existing_owner_write_boundary(rotation_case, monkeypatch):
    case = rotation_case
    with Session(case.engine) as seed:
        _seed(case, seed)
        seed.commit()
    staged, release = Event(), Event()
    backend_pid = Queue()
    original_stage = migration._stage

    def stage(*args, **kwargs):
        staged.set()
        assert release.wait(10), 'Owned test stage was not released'
        return original_stage(*args, **kwargs)

    monkeypatch.setattr(migration, '_stage', stage)

    def rotate():
        with runtime_config_scope(case.config), Session(case.engine) as db:
            backend_pid.put(db.scalar(text('SELECT pg_backend_pid()')))
            return migration.migrate_rows(db, case.root, apply=True)

    with Session(case.engine) as owner, ThreadPoolExecutor(max_workers=1) as pool:
        owner.execute(select(User.id).where(User.id == case.user_id).with_for_update()).first()
        future = pool.submit(rotate)
        try:
            pid = backend_pid.get(timeout=5)
            deadline, blocked = monotonic() + 5, False
            while monotonic() < deadline and not staged.is_set():
                with case.engine.connect() as monitor:
                    blocked = monitor.scalar(
                        text('SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid'), {'pid': pid},
                    ) == 'Lock'
                if blocked:
                    break
                sleep(0.01)
            assert blocked and not staged.is_set(), 'Rotation staged data while the owner write lock was held'
        finally:
            owner.rollback()
            release.set()
            result = future.result(timeout=10)
        assert result['failures'] == 0


def test_report_only_rotation_preserves_files_in_read_only_transactions(rotation_case):
    case = rotation_case
    with Session(case.engine) as seed:
        row = _seed(case, seed)
        seed.commit()
        original_path = row.storage_path
    before = {path.name: path.read_bytes() for path in case.root.iterdir()}
    with case.engine.connect() as connection:
        connection.exec_driver_sql('SET default_transaction_read_only = on')
        connection.commit()
        try:
            with Session(bind=connection) as db:
                result = migration.migrate_rows(db, case.root, apply=False)
                assert result['rotated'] == 1 and result['failures'] == 0
                assert db.execute(select(EmulatorSave.storage_path)).scalar_one() == original_path
        finally:
            connection.rollback()
            connection.exec_driver_sql('SET default_transaction_read_only = off')
            connection.commit()
    assert {path.name: path.read_bytes() for path in case.root.iterdir()} == before


@pytest.mark.parametrize('kind', ['active', 'unencrypted', 'missing', 'stage-failure'])
def test_rotation_releases_owner_locks_on_every_non_commit_path(rotation_case, monkeypatch, kind):
    case = rotation_case
    with Session(case.engine) as db:
        row = _seed(case, db)
        if kind == 'active':
            generation_id = Path(row.storage_path).stem
            Path(row.storage_path).write_bytes(save_crypto._encrypt_with_keyring(
                b'original-save', load_save_keyring(str(case.active_ring)),
                context=save_crypto.save_context(case.user_id, case.game_uuid, 'slot1', generation_id),
            ))
        elif kind == 'unencrypted':
            Path(row.storage_path).write_bytes(b'original-save')
            row.encrypted = False
        elif kind == 'missing':
            Path(row.storage_path).unlink()
        elif kind == 'stage-failure':
            def fail(*args, **kwargs):
                raise OSError('Synthetic stage failure')
            monkeypatch.setattr(migration, '_stage', fail)
        db.commit()
        result = migration.migrate_rows(db, case.root, apply=True)
        assert result['failures'] == (1 if kind in ('missing', 'stage-failure') else 0)
        with case.engine.begin() as probe:
            assert probe.scalar(select(User.id).where(User.id == case.user_id).with_for_update(nowait=True)) == case.user_id


def test_rotation_keeps_both_files_when_commit_acknowledgement_is_lost(rotation_case, monkeypatch):
    case = rotation_case
    with Session(case.engine) as db:
        row = _seed(case, db)
        db.commit()
        row_id, old_path = row.id, Path(row.storage_path)
        original_commit = db.commit

        def committed_then_lost():
            original_commit()
            raise OSError('Synthetic acknowledgement loss')

        monkeypatch.setattr(db, 'commit', committed_then_lost)
        result = migration.migrate_rows(db, case.root, apply=True)
        assert result['failures'] == 1
    with Session(case.engine) as check:
        current = check.get(EmulatorSave, row_id)
        assert _read(check, current) == b'original-save'
        assert current.storage_path != str(old_path)
        assert old_path.exists() and Path(current.storage_path).exists()
