"""Pure file-manager ownership/target checks; no GUI or system changes locally."""
import importlib.util
from pathlib import Path
import unittest
from unittest import mock

from probe_linux_packaged import ProbeFailure

spec = importlib.util.find_spec('linux_reveal_context')
reveal = __import__('linux_reveal_context') if spec else None


class RevealContracts(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(reveal, 'real file-manager target controls must exist')

    def test_only_directory_handler_for_real_thunar_is_accepted(self):
        valid = '[Desktop Entry]\nType=Application\nExec=thunar %F\nMimeType=inode/directory;\n'
        self.assertEqual(reveal.desktop_handler(valid), 'thunar')
        for value in (valid.replace('thunar %F','sh -c fake'), valid.replace('inode/directory','text/plain'),
                      valid.replace('Application','Link')):
            with self.assertRaises(ProbeFailure): reveal.desktop_handler(value)

    def test_location_bar_accepts_exact_path_or_uri_but_rejects_other_target(self):
        expected = Path('/owned/install').resolve()
        self.assertTrue(reveal.location_matches(str(expected), expected))
        self.assertTrue(reveal.location_matches(expected.as_uri(), expected))
        for value in ('/foreign/install','https://example.test/owned/install','file://foreign/owned/install','PRIVATE\nPRIVATE'):
            self.assertFalse(reveal.location_matches(value, expected))

    def test_invalid_or_oversized_window_identifier_is_refused(self):
        self.assertEqual(reveal.window_ids(b'123\n456\n'), [123,456])
        for value in (b'123;other', b'-1', b'0', b'1\n'*40):
            with self.assertRaises(ProbeFailure): reveal.window_ids(value)

    def test_local_execution_fence_precedes_native_commands(self):
        native = mock.Mock()
        with mock.patch.object(reveal, 'require_ci_execution', side_effect=ProbeFailure('no_local_gui')):
            with self.assertRaisesRegex(ProbeFailure, 'no_local_gui'): reveal.RevealContext(native,{})
        native.command.assert_not_called(); native.spawn.assert_not_called()

    def test_manager_failure_still_cleans_all_guardians_and_never_claims_success(self):
        context=reveal.RevealContext.__new__(reveal.RevealContext)
        context.closed=False; context.manager_handle=41; context.manager_attempted=True
        context.binary=Path('/owned/thunar'); context.guardians=[1,2]; context.progress={}
        context.native=mock.Mock(); context.native.command.side_effect=ProbeFailure('synthetic_quit_failure')
        context.api=mock.Mock(); context.api.close.side_effect=OSError('synthetic close failure')
        with self.assertRaises(ProbeFailure): context.close()
        self.assertEqual(context.native.stop.call_args_list,[mock.call(2),mock.call(1)])
        context.api.terminate.assert_called_once_with(41)
        self.assertFalse(context.progress['file_manager_cleanup_verified'])


if __name__ == '__main__': unittest.main()
