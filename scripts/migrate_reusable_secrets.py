#!/usr/bin/env python3
"""Encrypt legacy GlobalSettings integration secrets and rotate old keys.

Run after ``alembic upgrade head`` and configure
ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE (or the existing store-key alias).
The script never loads dotenv files, uses TEST_DATABASE_URL, prints credential
values, or makes provider requests. It commits one GlobalSettings row at a
time so interrupted runs can be safely repeated.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from oneirodex.utils.secret_store import migrate_reusable_secrets
from oneirodex.utils.store_credentials import StoreCredentialError, load_store_credential_keyring
from scripts.migrate_store_credentials import resolve_database_url


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
            result = migrate_reusable_secrets(session)
    except Exception:  # noqa: BLE001 - do not print DB URLs or bound values
        print('Reusable credential conversion could not complete; check redacted server logs.', file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        'Reusable credential conversion: '
        f"rows_changed={result['rows_changed']} "
        f"encrypted={result['secrets_encrypted']} "
        f"rotated={result['secrets_rotated']} "
        f"already_current={result['rows_already_current']} "
        f"remaining_legacy={result['remaining_legacy']} "
        f"failures={result['failures']}"
    )
    return 1 if result['remaining_legacy'] or result['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
