"""Fake-session CAS/ownership checks; never opens an application or DB."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from oneirodex.runtime_native.room_game_store import RoomGameProgressData, RoomProgressConflict


class Session:
    def __init__(self, row=None, rowcount=1):
        self.row = row
        self.rowcount = rowcount
        self.keys = []
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def get(self, model, key):
        self.keys.append(key)
        return self.row

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(rowcount=self.rowcount)

    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


class ProgressStoreTests(unittest.TestCase):
    def test_read_uses_authenticated_member_and_game_composite_key(self):
        session = Session()
        result = RoomGameProgressData(session).read(SimpleNamespace(id=41), 'moonfall-pinball')
        self.assertEqual(session.keys, [(41, 'moonfall-pinball')])
        self.assertEqual(result['revision'], 0)
        self.assertIsNone(result['state'])

    def test_update_predicate_has_owner_game_and_expected_revision(self):
        session = Session()
        result = RoomGameProgressData(session).write(SimpleNamespace(id=41), 'moonfall-pinball', 7, {'score': 1})
        query = session.statements[0].compile()
        self.assertEqual(query.params['user_id_1'], 41)
        self.assertEqual(query.params['game_id_1'], 'moonfall-pinball')
        self.assertEqual(query.params['revision_1'], 7)
        self.assertEqual(result['revision'], 8)
        self.assertEqual(session.commits, 1)

    def test_stale_revision_is_not_silently_overwritten(self):
        session = Session(rowcount=0)
        with self.assertRaises(RoomProgressConflict):
            RoomGameProgressData(session).write(SimpleNamespace(id=41), 'moonfall-pinball', 7, {})
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)

    def test_new_save_is_owned_and_revision_one(self):
        session = Session()
        result = RoomGameProgressData(session).write(SimpleNamespace(id=41), 'moonfall-pinball', 0, {})
        params = session.statements[0].compile().params
        self.assertEqual(params['user_id'], 41)
        self.assertEqual(params['game_id'], 'moonfall-pinball')
        self.assertEqual(params['revision'], 1)
        self.assertEqual(result['revision'], 1)

    def test_reset_erases_payload_but_keeps_a_monotonic_revision(self):
        session = Session()
        result = RoomGameProgressData(session).write(SimpleNamespace(id=41), 'moonfall-pinball', 7, None)
        self.assertEqual(result['revision'], 8)
        self.assertIsNone(result['state'])
        self.assertIsNone(session.statements[0].compile().params['state'])

    def test_zero_revision_reset_cannot_erase_an_existing_run(self):
        session = Session(row=SimpleNamespace(revision=3, state={}, updated_at=datetime.now(timezone.utc)))
        with self.assertRaises(RoomProgressConflict):
            RoomGameProgressData(session).write(SimpleNamespace(id=41), 'moonfall-pinball', 0, None)
        self.assertEqual(session.statements, [])


if __name__ == '__main__': unittest.main()
