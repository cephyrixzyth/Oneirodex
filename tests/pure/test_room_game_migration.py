"""Migration contract without a local database or application."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

file=Path(__file__).resolve().parents[2]/'alembic/versions/6a7b8c9d0e1f_room_game_progress.py'
spec=importlib.util.spec_from_file_location('room_progress_migration',file)
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)

class RoomMigrationTests(unittest.TestCase):
    def test_startweb_create_all_table_is_adopted_without_duplicate_creation(self):
        with patch.object(migration.op,'get_bind',return_value=object()), patch.object(migration.sa,'inspect',return_value=SimpleNamespace(has_table=lambda _:True)), patch.object(migration.op,'create_table',side_effect=AssertionError('table already exists')):
            migration.upgrade()

    def test_empty_database_still_creates_the_progress_table(self):
        with patch.object(migration.op,'get_bind',return_value=object()), patch.object(migration.sa,'inspect',return_value=SimpleNamespace(has_table=lambda _:False)), patch.object(migration.op,'create_table') as create:
            migration.upgrade()
            self.assertEqual(create.call_args.args[0],'room_game_progress')

if __name__=='__main__':unittest.main()
