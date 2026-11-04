#!/usr/bin/env python3
"""Encrypt legacy StoreAccount credentials without displaying secret values.

Run after `alembic upgrade head` with ONEIRODEX_STORE_CREDENTIAL_KEYRING_FILE
present in the process environment. External-database installs must also set
DATABASE_URL. Single-container installs can resolve their embedded database
from ONEIRODEX_CONFIG_DIR when embedded mode is enabled or auto-selected. This
script never loads `.env`, falls back to TEST_DATABASE_URL, or makes provider
requests.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import sys

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from oneirodex.utils.store_credentials import (
    StoreCredentialError,
    load_store_credential_keyring,
    migrate_legacy_store_credentials,
)


def resolve_database_url(env: dict[str, str] | None = None):
    """Resolve only an explicit external URL or the app's embedded DB contract.

    This mirrors ``docker/embedded-db.sh``'s embedded selection rules and
    connection defaults. It intentionally does not load dotenv files or use
    the test database setting.
    """
    env = os.environ if env is None else env
    mode = (env.get('ONEIRODEX_EMBEDDED_DB') or 'auto').strip().lower()
    if mode in {'true', '1', 'yes', 'on'}:
        embedded = True
    elif mode in {'false', '0', 'no', 'off'}:
        embedded = False
    else:
        embedded = not (
            (env.get('DATABASE_URL') or '').strip()
            or (env.get('DATABASE_HOST') or '').strip()
        )

    if not embedded:
        database_url = (env.get('DATABASE_URL') or '').strip()
        if not database_url:
            raise ValueError('DATABASE_URL is required for external database mode')
        return database_url

    config_dir = Path(env.get('ONEIRODEX_CONFIG_DIR') or '/config')
    data_dir = config_dir / 'pgdata'
    version_file = data_dir / 'PG_VERSION'
    secrets_dir = config_dir / 'secrets'
    secret_file = secrets_dir / 'db_password'
    if data_dir.is_symlink() or not data_dir.is_dir():
        raise ValueError('Embedded database cluster is unavailable')
    if version_file.is_symlink() or not version_file.is_file():
        raise ValueError('Embedded database cluster is not initialized')
    try:
        version = version_file.read_text(encoding='ascii').strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError('Embedded database cluster is invalid') from exc
    if not re.fullmatch(r'\d{1,3}', version):
        raise ValueError('Embedded database cluster is invalid')

    if secrets_dir.is_symlink() or not secrets_dir.is_dir():
        raise ValueError('Embedded database secrets directory is unavailable')
    if secret_file.is_symlink() or not secret_file.is_file():
        raise ValueError('Embedded database password file is unavailable')
    try:
        if os.name != 'nt':
            if stat.S_IMODE(secrets_dir.stat().st_mode) & 0o077:
                raise ValueError('Embedded database secrets directory permissions are unsafe')
            if stat.S_IMODE(secret_file.stat().st_mode) & 0o077:
                raise ValueError('Embedded database password file permissions are unsafe')
        password = secret_file.read_text(encoding='ascii').rstrip('\r\n')
    except (OSError, UnicodeError) as exc:
        raise ValueError('Embedded database password file is invalid') from exc
    if not password or '\n' in password or '\r' in password or '\x00' in password:
        raise ValueError('Embedded database password file is invalid')

    raw_port = (env.get('ONEIRODEX_EMBEDDED_DB_PORT') or '55432').strip()
    if not re.fullmatch(r'\d{1,5}', raw_port) or not 1 <= int(raw_port) <= 65535:
        raise ValueError('Embedded database port is invalid')
    database = (env.get('POSTGRES_DB') or 'oneirodex').strip()
    if not database or '\x00' in database:
        raise ValueError('Embedded database name is invalid')
    return URL.create(
        'postgresql',
        username='oneirodex',
        password=password,
        host='127.0.0.1',
        port=int(raw_port),
        database=database,
    )


def main() -> int:
    try:
        database_url = resolve_database_url()
        load_store_credential_keyring()
    except (StoreCredentialError, ValueError) as exc:
        print(f'{exc}; no rows were modified.', file=sys.stderr)
        return 2

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            result = migrate_legacy_store_credentials(session)
    except Exception:  # noqa: BLE001 - do not print DB URLs or bound parameters
        print('Credential conversion could not complete; check redacted server logs.', file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        'Store credential conversion: '
        f"encrypted={result['encrypted']} "
        f"rotated={result['rotated']} "
        f"already_encrypted={result['already_encrypted']} "
        f"remaining_legacy={result['remaining_legacy']} "
        f"failures={result['failures']}"
    )
    return 1 if result['remaining_legacy'] or result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
