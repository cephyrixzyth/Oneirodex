"""Real persistence/cascade checks for disposable CI; do not run on operator DBs."""
import json
from pathlib import Path
from uuid import uuid4

import pytest

from oneirodex.models import RoomGameProgress, User
from oneirodex.runtime_native.room_game_store import RoomGameProgressData, RoomProgressConflict


def _state():
    return json.loads((Path(__file__).parent / 'fixtures' / 'moonfall-save-v1.json').read_text())


def _member(session):
    suffix = uuid4().hex[:12]
    member = User(name=f'room-{suffix}', email=f'room-{suffix}@example.invalid',
                  role='user', state=True, password_hash='synthetic-not-a-login-credential')
    session.add(member)
    session.flush()
    return member


def test_room_progress_isolated_by_member_and_survives_revision_reset(db_session):
    first, second = _member(db_session), _member(db_session)
    data = RoomGameProgressData(db_session)
    original = data.write(first, 'moonfall-pinball', 0, _state())
    assert original['revision'] == 1
    assert data.read(second, 'moonfall-pinball')['state'] is None
    assert data.read(first, 'moonfall-pinball')['state'] == _state()
    reset = data.write(first, 'moonfall-pinball', 1, None)
    assert reset['revision'] == 2 and reset['state'] is None
    assert data.read(first, 'moonfall-pinball')['revision'] == 2
    with pytest.raises(RoomProgressConflict):
        data.write(first, 'moonfall-pinball', 1, _state())
    fresh = data.write(first, 'moonfall-pinball', 2, _state())
    assert fresh['revision'] == 3


def test_stale_empty_read_cannot_replace_an_already_inserted_run(db_session):
    member = _member(db_session)
    data = RoomGameProgressData(db_session)
    assert data.read(member, 'moonfall-pinball')['revision'] == 0
    assert data.read(member, 'moonfall-pinball')['revision'] == 0
    data.write(member, 'moonfall-pinball', 0, _state())
    with pytest.raises(RoomProgressConflict):
        data.write(member, 'moonfall-pinball', 0, _state())
    assert data.read(member, 'moonfall-pinball')['revision'] == 1


def test_deleting_one_account_cascades_only_its_progress(db_session):
    first, second = _member(db_session), _member(db_session)
    first_id, second_id = first.id, second.id
    data = RoomGameProgressData(db_session)
    data.write(first, 'moonfall-pinball', 0, _state())
    data.write(second, 'moonfall-pinball', 0, _state())
    db_session.delete(first)
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(RoomGameProgress, (first_id, 'moonfall-pinball')) is None
    assert db_session.get(RoomGameProgress, (second_id, 'moonfall-pinball')) is not None
