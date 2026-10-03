"""Every PostgreSQL connection must preserve UTC timestamp semantics."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


@pytest.mark.database
def test_new_postgres_engine_overrides_a_non_utc_session_timezone():
    engine = create_engine(
        os.environ['TEST_DATABASE_URL'],
        connect_args={'options': '-c timezone=America/New_York'},
    )
    try:
        with engine.connect() as conn:
            assert conn.execute(text('SHOW TIME ZONE')).scalar_one() == 'UTC'
            issued = datetime(2026, 10, 3, 17, 30, tzinfo=timezone(timedelta(hours=-5)))
            round_trip = conn.execute(
                text('SELECT CAST(:issued AS timestamptz)'), {'issued': issued}
            ).scalar_one()
            assert round_trip == issued.astimezone(timezone.utc)
    finally:
        engine.dispose()


def test_postgres_server_options_pin_timezone_to_utc():
    root = Path(__file__).resolve().parents[1]
    standalone = (root / 'oneirodex_standalone' / 'postgres.py').read_text(encoding='utf-8')
    embedded = (root / 'docker' / 'embedded-db.sh').read_text(encoding='utf-8')
    assert "'timezone=UTC'" in standalone
    assert '-c timezone=UTC' in embedded
