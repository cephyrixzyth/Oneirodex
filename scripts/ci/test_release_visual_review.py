"""Release capture fencing and artifact-name validation; no local app runs."""
import importlib.util
from pathlib import Path
import unittest
import json
import tempfile
from unittest import mock

from probe_linux_packaged import ProbeFailure

spec = importlib.util.find_spec('release_visual_review')
visual = __import__('release_visual_review') if spec else None


class ReleaseVisualGuards(unittest.TestCase):
    def test_checkpoint_persists_an_incomplete_source_bound_report(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            report = {'status':'failed','source_sha':'a'*40}
            visual.capture_checkpoint(Path(directory),report,'room_opening')
            value = json.loads((Path(directory)/'report-in-progress.json').read_text())
            self.assertEqual(value['phase'],'room_opening')
            self.assertEqual(value['source_sha'],'a'*40)
            self.assertEqual(value['status'],'failed')

    def setUp(self): self.assertIsNotNone(visual, 'release visual guards must exist')

    def test_local_execution_is_refused_before_paths_or_processes(self):
        with mock.patch.object(visual, 'require_backend_ci', side_effect=ProbeFailure('no_local_capture')):
            with self.assertRaisesRegex(ProbeFailure, 'no_local_capture'):
                visual.require_capture_ci(Path('PRIVATE'), {}, 'win32', 1001)

    def test_visual_capture_requires_explicit_selection_even_in_ci(self):
        with mock.patch.object(visual, 'require_backend_ci'):
            with self.assertRaises(ProbeFailure): visual.require_capture_ci(Path('PRIVATE'), {}, 'linux', 1001)
            visual.require_capture_ci(Path('PRIVATE'), {'RELEASE_VISUAL_ALLOWED':'1'}, 'linux', 1001)

    def test_theme_artifact_names_cannot_escape_output(self):
        self.assertEqual(visual.capture_slug('mosslight'), 'mosslight')
        for value in ('../private','/absolute','one/two','two\\three','x\n','a'*65):
            with self.assertRaises(ProbeFailure): visual.capture_slug(value)


if __name__ == '__main__': unittest.main()
