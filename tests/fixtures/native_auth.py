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
def persistent_login_store(monkeypatch, request):
    import oneirodex
    from oneirodex.models import PersistentLoginSession

    # Mixed modules also exercise real database adapters. Keep their actual
    # transaction instead of replacing it with the session-only SQLite store.
    if 'db_session' in request.fixturenames:
        yield request.getfixturevalue('db_session')
        return

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


def login_identity_for(user_id, *, fingerprint='0123456789abcdef'):
    """Issue a real persisted test login matching the caller's synthetic user.

    Requires persistent_login_store; numeric IDs alone never bypass validation.
    """
    from oneirodex.utils.persistent_sessions import issue_login_identity

    user = SimpleNamespace(id=user_id, session_fingerprint=lambda: fingerprint)
    return issue_login_identity(user)
