"""Shared native dispatch fixture with real persistent-login secret storage.

SQLite qualifies session issuance/hash/validation, not PostgreSQL FKs, locking
or concurrent native requests. Household/transaction assertions use PostgreSQL.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture(autouse=True)
def persistent_login_store(monkeypatch):
    import oneirodex
    from oneirodex.models import PersistentLoginSession

    engine = create_engine(
        'sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False},
    )
    PersistentLoginSession.__table__.create(engine)
    try:
        with Session(engine) as store:
            monkeypatch.setattr(oneirodex, 'db', SimpleNamespace(session=store))
            yield store
    finally:
        engine.dispose()
