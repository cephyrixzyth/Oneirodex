"""The details payload must say whether the reader may edit (v11 follow-up).

`GameDetailsPage` has read `game.can_edit` since the PC cheats panel shipped —
for the cheats form, the mods panel and the headset-record editor — but the
payload never sent the field, so every one of those controls was gated on
`undefined`. Librarian or above, the same rule their routes apply.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.game_details_payload import build_game_details_payload


def _user(db_session, role):
    uid = str(uuid4())
    row = User(name=f'{role}_{uid[:6]}', email=f'{role}_{uid[:6]}@example.com', role=role, user_id=uid, state=True)
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture
def game(db_session, tmp_path):
    lib = Library(name=f'CE_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    row = Game(uuid=str(uuid4()), name='Edit Me', library_uuid=lib.uuid, full_disk_path=str(tmp_path / 'g'))
    db_session.add(row)
    db_session.commit()
    return row


@pytest.mark.parametrize('role,expected', [('admin', True), ('librarian', True), ('user', False), ('child', False)])
def test_can_edit_follows_the_librarian_rule(app, db_session, game, role, expected):
    user = _user(db_session, role)
    with app.app_context():
        payload = build_game_details_payload(game, user)
    assert payload['can_edit'] is expected
    assert payload['is_admin'] is (role == 'admin')
    assert payload['can_cleanup_versions'] is expected
