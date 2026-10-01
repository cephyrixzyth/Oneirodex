"""Migration a7c1d9e2f3b4 (LIB-04): additive, idempotent, reversible without data loss.

Runs on SQLite, or on a dedicated loopback PostgreSQL given as P04_TEST_DATABASE_URL.
"""
import importlib.util
import os
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

LONG_ID = 'Microsoft.SeaofThieves_8wekyb3d8bbwe-and-then-some-more'


def _url():
    value = os.environ.get('P04_TEST_DATABASE_URL')
    if value:
        from database_test_guard import validate_test_database_url
        from sqlalchemy.engine import make_url
        validate_test_database_url(value)
        assert make_url(value).host == '127.0.0.1'
    return value or 'sqlite://'


def _migration():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/a7c1d9e2f3b4_add_store_sync_jobs.py'
    spec = importlib.util.spec_from_file_location('store_sync_jobs_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == 'd4e5f6a7b8c9'
    return module


def _length(conn):
    column = {c['name']: c for c in inspect(conn).get_columns('user_owned_titles')}['external_app_id']
    return getattr(column['type'], 'length', None)


def test_upgrade_downgrade_roundtrip_preserves_rows():
    migration = _migration()
    engine = create_engine(_url())
    postgres = engine.dialect.name == 'postgresql'
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql('CREATE TABLE store_accounts (id INTEGER PRIMARY KEY, user_id INTEGER, store VARCHAR(16), created_at TIMESTAMP)')
        conn.exec_driver_sql('CREATE TABLE user_owned_titles (id INTEGER PRIMARY KEY, user_id INTEGER, store VARCHAR(16), external_app_id VARCHAR(32) NOT NULL)')
        conn.exec_driver_sql("INSERT INTO users VALUES (1)")
        conn.exec_driver_sql("INSERT INTO store_accounts VALUES (1, 1, 'gog', CURRENT_TIMESTAMP)")
        conn.exec_driver_sql("INSERT INTO user_owned_titles VALUES (1, 1, 'gog', '1207658924')")
        migration.op = Operations(MigrationContext.configure(conn))
        migration.upgrade()
        migration.upgrade()  # idempotent
        assert inspect(conn).has_table('store_sync_jobs')
        assert conn.exec_driver_sql('SELECT updated_at FROM store_accounts').scalar() is None
        assert conn.exec_driver_sql('SELECT external_app_id FROM user_owned_titles').scalar() == '1207658924'
        if postgres:
            assert _length(conn) == 128
        conn.exec_driver_sql(f"INSERT INTO user_owned_titles VALUES (2, 1, 'xbox', '{LONG_ID}')")
        conn.exec_driver_sql(
            "INSERT INTO store_sync_jobs (user_id, store, trigger, status, started_at, heartbeat_at) "
            "VALUES (1, 'gog', 'member', 'running', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        defaults = conn.exec_driver_sql('SELECT cancellable, cancel_requested, pages, items_seen FROM store_sync_jobs').one()
        assert tuple(bool(v) if i < 2 else v for i, v in enumerate(defaults)) == (False, False, 0, 0)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO store_sync_jobs (user_id, store, trigger, status, started_at, heartbeat_at) "
                "VALUES (1, 'gog', 'schedule', 'running', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO store_sync_jobs (user_id, store, trigger, status, started_at, heartbeat_at) "
            "VALUES (1, 'gog', 'schedule', 'failed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        migration.op = Operations(MigrationContext.configure(conn))
        migration.downgrade()
        assert not inspect(conn).has_table('store_sync_jobs')
        assert 'updated_at' not in {c['name'] for c in inspect(conn).get_columns('store_accounts')}
        assert conn.exec_driver_sql('SELECT COUNT(*) FROM user_owned_titles').scalar() == 2
        if postgres:
            assert _length(conn) == 128, 'never narrow below a stored ID'
        conn.exec_driver_sql('DELETE FROM user_owned_titles WHERE id = 2')
        migration.upgrade()
        migration.downgrade()
        migration.downgrade()  # idempotent
        if postgres:
            assert _length(conn) == 32
        conn.exec_driver_sql('DROP TABLE user_owned_titles')
        conn.exec_driver_sql('DROP TABLE store_accounts')
        conn.exec_driver_sql('DROP TABLE users')
    engine.dispose()
