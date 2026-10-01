"""Run without the app/database: python tests/test_sync_prompt_trees.py."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prompt_sync', Path(__file__).resolve().parents[1] / 'scripts/sync_prompt_trees.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class PromptSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.src = self.root / '.cursor/skills'
        self.dst = self.root / '.agents/skills'
        self.src.mkdir(parents=True)
        self.src.joinpath('SKILL.md').write_text('canonical', encoding='utf-8')
        self.patch_root = patch.object(sync, 'REPO', self.root)
        self.patch_pairs = patch.object(sync, 'PAIRS', ((self.src, self.dst),))
        self.patch_root.start()
        self.patch_pairs.start()

    def tearDown(self):
        self.patch_pairs.stop()
        self.patch_root.stop()
        self.temp.cleanup()

    def test_sync_detects_drift_and_replaces_only_mirror(self):
        neighbor = self.root / '.agents/keep.txt'
        neighbor.parent.mkdir()
        neighbor.write_text('keep')
        self.assertTrue(sync.check())
        self.assertEqual(sync.sync(), 1)
        self.assertEqual(sync.check(), [])
        self.dst.joinpath('SKILL.md').write_text('different')
        self.dst.joinpath('stale').write_text('old')
        self.assertTrue(sync.check())
        sync.sync()
        self.assertEqual(sync.check(), [])
        self.assertEqual(neighbor.read_text(), 'keep')

    def test_missing_source_does_not_delete_generated_files(self):
        sync.sync()
        self.src.joinpath('SKILL.md').unlink()
        self.src.rmdir()
        with self.assertRaises(ValueError):
            sync.sync()
        self.assertEqual(self.dst.joinpath('SKILL.md').read_text(), 'canonical')
        self.assertTrue(sync.check())

    def test_outside_destination_is_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as outside:
            with patch.object(sync, 'PAIRS', ((self.src, Path(outside) / 'skills'),)):
                with self.assertRaises(ValueError):
                    sync.sync()
                self.assertFalse((Path(outside) / 'skills').exists())


if __name__ == '__main__':
    unittest.main()
