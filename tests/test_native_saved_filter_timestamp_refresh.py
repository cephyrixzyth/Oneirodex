from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from oneirodex.models import SavedFilter
from oneirodex.runtime_native.saved_filters import SavedFilterData


class _Session:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    def commit(self):
        now = datetime.now(timezone.utc)
        for row in self.rows:
            if row.created is None:
                row.created = now
            row.updated = now

    def refresh(self, row):
        # The database columns are TIMESTAMP WITHOUT TIME ZONE.
        row.created = row.created.replace(tzinfo=None)
        row.updated = row.updated.replace(tzinfo=None)


def test_create_refreshes_database_timestamp_representation(monkeypatch):
    from oneirodex.runtime_native import db_session

    session = _Session()
    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=session))

    row = SavedFilterData().create(
        SimpleNamespace(id=7), name='Saved', tree={'field': 'is_vr', 'value': True},
        is_collection=False,
    )

    assert isinstance(row, SavedFilter)
    assert row.created.tzinfo is None
    assert row.updated.tzinfo is None
    assert row.to_dict()['created'] == row.created.isoformat()
    assert row.to_dict()['updated'] == row.updated.isoformat()


def test_update_refreshes_database_timestamp_representation(monkeypatch):
    from oneirodex.runtime_native import db_session

    session = _Session()
    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=session))
    row = SimpleNamespace(
        created=datetime.now(timezone.utc), updated=datetime.now(timezone.utc),
    )

    SavedFilterData().save(row)

    assert row.created.tzinfo is None
    assert row.updated.tzinfo is None
