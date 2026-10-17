from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from oneirodex.runtime_native.social_writes import SocialWriteData


class _Result:
    def scalars(self):
        return self

    def first(self):
        return None


class _ResultWithFriend(_Result):
    def __init__(self, friend):
        self.friend = friend

    def first(self):
        return self.friend


class _Session:
    def __init__(self):
        self.row = None
        self.query_count = 0

    def get(self, model, _identity):
        from oneirodex.models import User

        return SimpleNamespace(id=8, name='Friend') if model is User else None

    def execute(self, _statement):
        self.query_count += 1
        if self.query_count == 1:
            return _ResultWithFriend(SimpleNamespace(id=8, name='Friend'))
        return _Result()

    def add(self, row):
        self.row = row

    def commit(self):
        self.row.id = 10
        self.row.created_at = datetime.now(timezone.utc)
        self.row.updated_at = self.row.created_at

    def refresh(self, row):
        row.created_at = row.created_at.replace(tzinfo=None)
        row.updated_at = row.updated_at.replace(tzinfo=None)


def test_friend_request_refreshes_committed_timestamp_before_serializing(monkeypatch):
    from oneirodex.runtime_native import db_session
    from oneirodex.utils import notifications

    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=_Session()))
    monkeypatch.setattr(notifications, 'notify_friend_request', lambda *_args: None)

    result, status, refusal = SocialWriteData().request(
        SimpleNamespace(id=7), {'username': 'Friend'},
    )

    assert status == 201
    assert refusal is None
    assert result['friendship']['created_at']
    assert not result['friendship']['created_at'].endswith('+00:00')
