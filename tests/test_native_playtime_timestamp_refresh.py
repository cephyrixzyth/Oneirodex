from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from oneirodex.runtime_native.playtime import PlaytimeData


class _Session:
    def refresh(self, row):
        for field in ('started_at', 'last_heartbeat_at', 'ended_at'):
            value = getattr(row, field, None)
            if value is not None:
                setattr(row, field, value.replace(tzinfo=None))


def _row():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        started_at=now,
        last_heartbeat_at=now,
        ended_at=now,
        status='ended',
        to_dict=lambda: {},
    )


@pytest.mark.parametrize('operation', ['start', 'heartbeat', 'stop'])
def test_session_mutations_refresh_committed_timestamps(monkeypatch, operation):
    from oneirodex.runtime_native import db_session
    from oneirodex.utils import playtime as playtime_utils

    row = _row()
    monkeypatch.setattr(
        db_session, 'native_db', SimpleNamespace(session=_Session()),
    )
    utility_name = {
        'start': 'start_session',
        'heartbeat': 'heartbeat_session',
        'stop': 'end_session',
    }[operation]
    monkeypatch.setattr(playtime_utils, utility_name, lambda *_args, **_kwargs: row)
    data = PlaytimeData()
    data.flask_app = SimpleNamespace(config={})

    if operation == 'start':
        result = data.start(
            SimpleNamespace(id=7),
            SimpleNamespace(game_uuid='game-1', client='web'),
        )
    else:
        result = getattr(data, operation)(row)

    assert result is row
    assert row.started_at.tzinfo is None
    assert row.last_heartbeat_at.tzinfo is None
    assert row.ended_at.tzinfo is None
