from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from oneirodex.runtime_native import collection_reads


class _Session:
    def add(self, row):
        self.row = row

    def commit(self):
        self.row.id = 8
        self.row.uuid = str(uuid4())
        self.row.created_at = datetime.now(timezone.utc)

    def refresh(self, row):
        row.created_at = row.created_at.replace(tzinfo=None)


def test_collection_create_refreshes_timestamp_before_serialization(monkeypatch):
    from oneirodex.runtime_native import db_session

    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=_Session()))
    monkeypatch.setattr(
        collection_reads, '_collection_payload',
        lambda collection, *_args, **_kwargs: {
            'created_at': collection.created_at.isoformat(),
        },
    )

    result = collection_reads.CollectionReadData().create(
        SimpleNamespace(id=7),
        SimpleNamespace(name='Shelf', description=None, is_public=False),
    )

    assert result['created_at']
    assert not result['created_at'].endswith('+00:00')
