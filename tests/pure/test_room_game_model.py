"""Read ORM metadata only: no engine, application or database creation."""
import unittest
import json
from pathlib import Path
from oneirodex.models.room_games import RoomGameProgress


class RoomGameModelTests(unittest.TestCase):
    def test_progress_is_keyed_by_member_and_game_with_delete_cascade(self):
        table = RoomGameProgress.__table__
        self.assertEqual(table.name, 'room_game_progress')
        self.assertEqual([column.name for column in table.primary_key], ['user_id', 'game_id'])
        fk = next(iter(table.c.user_id.foreign_keys))
        self.assertEqual(fk.target_fullname, 'users.id')
        self.assertEqual(fk.ondelete, 'CASCADE')

    def test_null_state_can_preserve_revision_tombstone(self):
        table = RoomGameProgress.__table__
        self.assertTrue(table.c.state.nullable)
        self.assertFalse(table.c.revision.nullable)
        self.assertFalse(table.c.updated_at.nullable)

    def test_deletion_inventory_declares_the_new_private_relation(self):
        manifest = json.loads((Path(__file__).resolve().parents[2] / 'docs/dev/parity-evidence/account-deletion-relation-manifest-r1994.json').read_text())
        relation = next((r for r in manifest['relations'] if r['foreign_key'] == 'room_game_progress.user_id'), None)
        self.assertIsNotNone(relation)
        self.assertEqual(relation['on_delete'], 'CASCADE')
        self.assertEqual(relation['disposition'], 'delete_account_linked_row')


if __name__ == '__main__':
    unittest.main()
