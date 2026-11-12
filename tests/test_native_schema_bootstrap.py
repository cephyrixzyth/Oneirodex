"""Real native bootstrap must finish migrations without losing retained saves."""
from datetime import datetime, timezone
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from database_test_guard import validate_test_database_url
from oneirodex.init_manager import InitializationManager
from oneirodex.models import EmulatorSave, EmulatorSaveGeneration, Game, Library, User
from oneirodex.models.orm import ModelBase
from oneirodex.platform import LibraryPlatform


ROOT = Path(__file__).resolve().parents[1]


def _alembic_config():
    cfg = AlembicConfig(str(ROOT / 'alembic.ini'))
    cfg.set_main_option('script_location', str(ROOT / 'alembic'))
    return cfg


def _revision(engine):
    with engine.connect() as connection:
        return connection.scalar(sa.text('SELECT version_num FROM alembic_version'))


@pytest.fixture
def schema_case(monkeypatch):
    # Alembic's ini logging setup closes/replaces pytest's live capture handlers
    # and disables unrelated application loggers. Keep DDL and CLI diagnostics
    # real without leaking global logging reconfiguration into later tests.
    monkeypatch.setattr('logging.config.fileConfig', lambda *_args, **_kwargs: None)
    # The parent is the dedicated test DB, never the postgres/production DB.
    raw = os.environ.get('TEST_DATABASE_URL')
    validate_test_database_url(raw)
    # Import classes while the process still points to the parent test DB;
    # TestConfig captures its URI at import and is used by later app fixtures.
    from config import Config
    from oneirodex import updateschema

    parent_url = make_url(raw).set(drivername='postgresql+psycopg2')
    assert parent_url.host in {'127.0.0.1', 'localhost', '::1'}
    name = 'oneirodex_bootstrap_test_' + uuid4().hex[:12]
    assert name.startswith('oneirodex_bootstrap_test_') and 'test' in name
    child_url = parent_url.set(database=name)
    child_raw = child_url.render_as_string(hide_password=False)
    validate_test_database_url(child_raw)
    parent = sa.create_engine(parent_url, pool_pre_ping=True)
    child = None
    created = False
    try:
        with parent.connect().execution_options(isolation_level='AUTOCOMMIT') as admin:
            admin.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        monkeypatch.setenv('DATABASE_URL', child_raw)
        monkeypatch.setenv('TEST_DATABASE_URL', child_raw)
        monkeypatch.setattr(Config, 'SQLALCHEMY_DATABASE_URI', child_raw)
        # Earlier config reloads can leave this module holding the prior class.
        # Keep both aliases on the child, then restore both during teardown.
        monkeypatch.setattr(updateschema.Config, 'SQLALCHEMY_DATABASE_URI', child_raw)
        child = sa.create_engine(child_url, pool_pre_ping=True)
        yield SimpleNamespace(
            engine=child, manager=InitializationManager(),
            head=ScriptDirectory.from_config(_alembic_config()).get_current_head(),
        )
    finally:
        if child is not None:
            child.dispose()
        if created:
            with parent.connect().execution_options(isolation_level='AUTOCOMMIT') as admin:
                admin.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
                assert admin.scalar(sa.text(
                    'SELECT count(*) FROM pg_database WHERE datname=:name',
                ), {'name': name}) == 0
        parent.dispose()


def _owner_and_game(db):
    user = User(
        name='SyntheticSchemaOwner', email='schema@example.invalid',
        user_id=str(uuid4()), password_hash='unused', role='user', state=True,
    )
    library = Library(name='Synthetic Schema', platform=LibraryPlatform.NES)
    db.add_all([user, library])
    db.flush()
    game = Game(uuid=str(uuid4()), name='Synthetic Save', library_uuid=library.uuid)
    db.add(game)
    db.flush()
    return user.id, game.uuid


def test_native_fresh_schema_reaches_declared_head(schema_case):
    case = schema_case
    assert case.manager._phase2_database_structure() is True
    assert _revision(case.engine) == case.head


def test_native_bootstrap_keeps_stale_config_alias_on_owned_child(monkeypatch, request):
    # Configuration reloads leave the legacy module holding the prior class.
    # Simulate that identity split without globally reloading pytest's config.
    parent_raw = os.environ['TEST_DATABASE_URL']
    validate_test_database_url(parent_raw)
    parent_url = make_url(parent_raw).set(drivername='postgresql+psycopg2')
    from oneirodex import updateschema

    prior_config = type('PriorConfig', (), {'SQLALCHEMY_DATABASE_URI': parent_raw})
    monkeypatch.setattr(updateschema, 'Config', prior_config)
    case = request.getfixturevalue('schema_case')
    migration = updateschema.DatabaseManager()
    try:
        actual = make_url(migration.database_uri).database
        assert actual == case.engine.url.database, 'Legacy DDL must stay inside the owned child'
    finally:
        migration.engine.dispose()

    parent = sa.create_engine(parent_url)
    try:
        with parent.connect() as connection:
            before = connection.execute(sa.text(
                'SELECT identifier, name FROM discovery_sections ORDER BY id',
            )).all()
        assert case.manager._phase2_database_structure() is True
        assert _revision(case.engine) == case.head
        with parent.connect() as connection:
            assert connection.execute(sa.text(
                'SELECT identifier, name FROM discovery_sections ORDER BY id',
            )).all() == before
    finally:
        parent.dispose()


def test_native_current_metadata_preserves_revision_history_and_bytes(schema_case, tmp_path):
    case = schema_case
    ModelBase.metadata.create_all(case.engine)
    current_path, prior_path = tmp_path / 'current.save', tmp_path / 'prior.save'
    current_path.write_bytes(b'current revision seven')
    prior_path.write_bytes(b'retained generation')
    with Session(case.engine) as db:
        user_id, game_uuid = _owner_and_game(db)
        current = EmulatorSave(
            user_id=user_id, game_uuid=game_uuid, slot_name='slot1', filename='save.sav',
            storage_path=str(current_path), size_bytes=22, revision=7, encrypted=False,
        )
        db.add(current)
        db.flush()
        db.add(EmulatorSaveGeneration(
            save_id=current.id, filename='old.sav', storage_path=str(prior_path),
            size_bytes=19, encrypted=False,
        ))
        db.commit()
        save_id = current.id
    for _ in range(2):
        assert case.manager._phase2_database_structure() is True
        assert _revision(case.engine) == case.head
        with Session(case.engine) as db:
            assert db.get(EmulatorSave, save_id).revision == 7
            assert db.scalar(sa.select(sa.func.count()).select_from(EmulatorSaveGeneration)) == 1
        assert current_path.read_bytes() == b'current revision seven'
        assert prior_path.read_bytes() == b'retained generation'


def test_native_legacy_save_backfills_revision_without_losing_bytes(schema_case, tmp_path):
    case = schema_case
    command.upgrade(_alembic_config(), 'c0f6e9a2d1b4')
    path = tmp_path / 'legacy.save'
    path.write_bytes(b'legacy save')
    with Session(case.engine) as db:
        user_id, game_uuid = _owner_and_game(db)
        table = sa.Table('emulator_saves', sa.MetaData(), autoload_with=case.engine)
        now = datetime.now(timezone.utc)
        db.execute(table.insert().values(
            user_id=user_id, game_uuid=game_uuid, slot_name='slot1', filename='legacy.sav',
            storage_path=str(path), size_bytes=11, encrypted=False,
            created_at=now, updated_at=now,
        ))
        db.commit()
    assert case.manager._phase2_database_structure() is True
    assert _revision(case.engine) == case.head
    with case.engine.connect() as connection:
        assert connection.scalar(sa.text('SELECT revision FROM emulator_saves')) == 1
    assert path.read_bytes() == b'legacy save'


@pytest.mark.parametrize('shape', [
    'revision-type', 'history-shape', 'history-index', 'history-type',
    'history-nullable', 'history-foreign-key', 'history-primary-key',
])
def test_native_incompatible_existing_save_schema_fails_closed(schema_case, shape):
    case = schema_case
    ModelBase.metadata.create_all(case.engine)
    with case.engine.begin() as connection:
        if shape == 'revision-type':
            connection.exec_driver_sql(
                'ALTER TABLE emulator_saves ALTER COLUMN revision TYPE text USING revision::text',
            )
        elif shape == 'history-shape':
            connection.exec_driver_sql('ALTER TABLE emulator_save_generations DROP COLUMN filename')
        elif shape == 'history-index':
            connection.exec_driver_sql('DROP INDEX ix_emulator_save_generations_save_id')
            connection.exec_driver_sql(
                'CREATE INDEX ix_emulator_save_generations_save_id '
                'ON emulator_save_generations (filename)',
            )
        elif shape == 'history-type':
            connection.exec_driver_sql(
                'ALTER TABLE emulator_save_generations ALTER COLUMN filename TYPE varchar(8)',
            )
        elif shape == 'history-nullable':
            connection.exec_driver_sql(
                'ALTER TABLE emulator_save_generations ALTER COLUMN save_id DROP NOT NULL',
            )
        else:
            inspector = sa.inspect(connection)
            constraint = (
                inspector.get_foreign_keys('emulator_save_generations')[0]['name']
                if shape == 'history-foreign-key'
                else inspector.get_pk_constraint('emulator_save_generations')['name']
            )
            quoted = connection.dialect.identifier_preparer.quote(constraint)
            connection.exec_driver_sql(
                f'ALTER TABLE emulator_save_generations DROP CONSTRAINT {quoted}',
            )
    assert case.manager._phase2_database_structure() is False
    assert _revision(case.engine) != case.head


def test_native_partial_schema_backfills_null_and_repairs_missing_index(schema_case):
    case = schema_case
    ModelBase.metadata.create_all(case.engine)
    with case.engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE emulator_saves ALTER COLUMN revision DROP NOT NULL')
        connection.exec_driver_sql('DROP INDEX ix_emulator_save_generations_save_id')
    with Session(case.engine) as db:
        user_id, game_uuid = _owner_and_game(db)
        table = sa.Table('emulator_saves', sa.MetaData(), autoload_with=case.engine)
        now = datetime.now(timezone.utc)
        db.execute(table.insert().values(
            user_id=user_id, game_uuid=game_uuid, slot_name='slot1', filename='save.sav',
            storage_path='synthetic-only', size_bytes=0, encrypted=False, revision=None,
            created_at=now, updated_at=now,
        ))
        db.commit()
    assert case.manager._phase2_database_structure() is True
    assert _revision(case.engine) == case.head
    with case.engine.connect() as connection:
        assert connection.scalar(sa.text('SELECT revision FROM emulator_saves')) == 1
    indexes = sa.inspect(case.engine).get_indexes('emulator_save_generations')
    assert any(index['name'] == 'ix_emulator_save_generations_save_id'
               and index['column_names'] == ['save_id'] for index in indexes)


def test_native_upgrade_error_blocks_startup_without_raw_detail(schema_case, monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise RuntimeError('SYNTHETIC_PRIVATE_MIGRATION_DETAIL')

    monkeypatch.setattr(command, 'upgrade', fail)
    assert schema_case.manager._phase2_database_structure() is False
    captured = capsys.readouterr()
    assert 'SYNTHETIC_PRIVATE_MIGRATION_DETAIL' not in captured.out + captured.err


def test_native_missing_alembic_config_is_not_success(schema_case, monkeypatch, tmp_path):
    from oneirodex import init_manager

    monkeypatch.setattr(init_manager, 'PACKAGE_ROOT', str(tmp_path / 'missing-package'))
    with pytest.raises(RuntimeError, match='migration|Alembic'):
        schema_case.manager._ensure_alembic_current(schema_case.engine)
