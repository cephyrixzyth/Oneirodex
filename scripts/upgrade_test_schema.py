#!/usr/bin/env python3
"""Upgrade the configured loopback test DB and check the current save schema."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from database_test_guard import validate_test_database_url


def resolve_loopback_test_database_url(value: str | None) -> str:
    url = validate_test_database_url(value)
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Test-schema upgrade requires a loopback PostgreSQL host")
    return url


def upgrade_test_schema(database_url: str) -> None:
    """Upgrade only a loopback, test-named database and reject drifted heads."""
    url = resolve_loopback_test_database_url(database_url)
    # Alembic prefers DATABASE_URL. Override it only in this process so a
    # separate application URL loaded from .env cannot become the target.
    os.environ["DATABASE_URL"] = url
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        schema = inspect(engine)
        columns = {column["name"] for column in schema.get_columns("emulator_saves")}
        tables = set(schema.get_table_names())
    finally:
        engine.dispose()
    if "revision" not in columns or "emulator_save_generations" not in tables:
        raise RuntimeError(
            "Test database schema does not match Alembic head; create a fresh test-named database"
        )


def main() -> int:
    load_dotenv(ROOT / ".env")
    try:
        upgrade_test_schema(os.environ.get("TEST_DATABASE_URL"))
    except Exception as exc:  # never print a URL or driver error context
        print(
            f"Test-schema upgrade failed ({type(exc).__name__}); details withheld. "
            "If schema drift is reported, create a fresh test-named database as "
            "described in docs/runbooks/local-postgres-pytest.md.",
            file=sys.stderr,
        )
        return 1
    print("Loopback test database upgraded and current save schema verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
