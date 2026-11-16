#!/usr/bin/env python3
"""Report missing and unreferenced emulator save files without changing them."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from oneirodex.utils.emulator_saves import audit_save_storage
from scripts.migrate_store_credentials import resolve_database_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='configured emulator save storage root')
    parser.add_argument('--entry-limit', type=int, default=100_000)
    args = parser.parse_args()
    try:
        database_url = resolve_database_url()
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with Session(engine) as session:
                result = audit_save_storage(session, args.root, entry_limit=args.entry_limit)
        finally:
            engine.dispose()
    except Exception as exc:  # do not print database URLs or filesystem paths
        print(
            json.dumps({'complete': False, 'error': type(exc).__name__, 'mutated_files': False}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
