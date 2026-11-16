"""The data-only token migration preserves values while removing raw links."""
import hashlib
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine


def _migration():
    path = (
        Path(__file__).resolve().parents[1]
        / 'alembic/versions/c0f6e9a2d1b4_hash_email_verification_tokens.py'
    )
    spec = importlib.util.spec_from_file_location('email_verification_token_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == 'f9a04c1d7e32'
    return module


def test_upgrade_hashes_raw_tokens_idempotently_and_preserves_empty_states():
    migration = _migration()
    engine = create_engine('sqlite://')
    raw_token = 'signed.token.value'
    existing_digest = 'a' * 64
    with engine.begin() as conn:
        conn.exec_driver_sql(
            'CREATE TABLE users '
            '(id INTEGER PRIMARY KEY, email_verification_token VARCHAR(256))'
        )
        conn.exec_driver_sql(
            'INSERT INTO users (id, email_verification_token) VALUES (?, ?)',
            [
                (1, raw_token),
                (2, existing_digest),
                (3, ''),
                (4, None),
            ],
        )
        migration.op = Operations(MigrationContext.configure(conn))

        migration.upgrade()
        migration.upgrade()

        values = dict(conn.exec_driver_sql(
            'SELECT id, email_verification_token FROM users'
        ).all())
        assert values[1] == hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        assert values[2] == existing_digest
        assert values[3] == ''
        assert values[4] is None
        migration.downgrade()
        assert dict(conn.exec_driver_sql(
            'SELECT id, email_verification_token FROM users'
        ).all()) == values
    engine.dispose()
