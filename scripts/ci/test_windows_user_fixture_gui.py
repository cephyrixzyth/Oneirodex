"""Pure/fake tests; never create a local native window, account or mutex."""
import importlib.util
import ctypes
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import probe_windows_user_fixture as control
from windows_user_fixture import FixtureFailure

spec = importlib.util.find_spec('windows_gui_prerequisites')
gui = __import__('windows_gui_prerequisites') if spec else None


class FakeAPI:
    def __init__(self, failures=None):
        self.failures = failures or {}
        self.calls = []

    def invoke(self, name, *args):
        self.calls.append((name, args))
        return self.failures.get(name, (True, 0))

    def own_mutex(self): return self.invoke('own_mutex')
    def browser_mutex(self): return self.invoke('browser_mutex')
    def message_window(self): return self.invoke('message_window')
    def lock_file(self, path): return self.invoke('lock_file', path)


class GuiPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(gui, 'bounded ordinary-account GUI prerequisites need an isolated helper')

    def test_prerequisites_and_foreign_mutex_observation_have_fixed_fields(self):
        api = FakeAPI({'browser_mutex': (False, 5)})
        result = gui.collect_checks(api, Path('PRIVATE'))
        self.assertTrue(result['owned_prerequisites_passed'])
        self.assertEqual(result['browser_mutex_open'], {'succeeded': False, 'win32_error': 5})
        self.assertEqual([x[0] for x in api.calls], ['own_mutex', 'browser_mutex', 'message_window', 'lock_file'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('acquire', repr(api.calls))

    def test_owned_failure_is_preserved_and_does_not_skip_other_checks(self):
        api = FakeAPI({'message_window': (False, 5)})
        result = gui.collect_checks(api, Path('PRIVATE'))
        self.assertFalse(result['owned_prerequisites_passed'])
        self.assertEqual(result['message_window'], {'succeeded': False, 'win32_error': 5})
        self.assertEqual(api.calls[-1][0], 'lock_file')

    def test_helper_local_cli_refuses_before_native_or_file_access(self):
        with mock.patch.dict(gui.os.environ, {}, clear=True), \
             mock.patch.object(gui, 'NativeGUIAPI') as native, \
             mock.patch.object(Path, 'open', side_effect=AssertionError('no local writes')):
            self.assertEqual(gui.main(['--output', 'never-created.json']), 2)
        native.assert_not_called()

    def test_controller_requires_verified_fixture_and_closes_failed_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = mock.Mock(work=Path(tmp), environment={})
            fixture.receipt = {'standard_user_verified': True, 'profile_environment_verified': True,
                               'private_desktop_created': True}
            child = fixture.start.return_value
            child.wait.side_effect = FixtureFailure('fixture_synthetic_wait_failed')
            child.close.side_effect = FixtureFailure('fixture_synthetic_close_failed')
            with self.assertRaisesRegex(FixtureFailure, 'wait_failed') as failed:
                control.observe_gui_prerequisites(fixture)
            self.assertIn('fixture_gui_child_cleanup_failed', failed.exception.__notes__)
            child.close.assert_called_once()
            fixture.receipt['standard_user_verified'] = False
            fixture.start.reset_mock()
            with self.assertRaisesRegex(FixtureFailure, 'prerequisite_not_verified'):
                control.observe_gui_prerequisites(fixture)
            fixture.start.assert_not_called()

    def test_controller_projects_fixed_receipt_and_bounds_untrusted_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = mock.Mock(work=Path(tmp), environment={})
            fixture.receipt = dict.fromkeys(('standard_user_verified', 'profile_environment_verified',
                                            'private_desktop_created'), True)
            def result_file(executable, env, arguments):
                data = gui.collect_checks(FakeAPI(), Path('PRIVATE'))
                data['PRIVATE'] = 'PRIVATE'
                Path(arguments[-1]).write_text(json.dumps(data), encoding='utf-8')
                child = mock.Mock(); child.wait.return_value = 0
                return child
            fixture.start.side_effect = result_file
            result = control.observe_gui_prerequisites(fixture)
            self.assertTrue(result['owned_prerequisites_passed'])
            self.assertNotIn('PRIVATE', json.dumps(result))
            for f in Path(tmp).iterdir(): f.unlink()
            def oversized(executable, env, arguments):
                Path(arguments[-1]).write_bytes(b'x' * 8193)
                child = mock.Mock(); child.wait.return_value = 0
                return child
            fixture.start.side_effect = oversized
            with self.assertRaisesRegex(FixtureFailure, 'receipt_invalid'):
                control.observe_gui_prerequisites(fixture)

    def test_native_bindings_open_foreign_mutex_without_creating_or_waiting(self):
        api = gui.NativeGUIAPI.__new__(gui.NativeGUIAPI)
        api.c = mock.Mock(get_last_error=lambda: 5, c_void_p=ctypes.c_void_p)
        api._open_mutex = mock.Mock(return_value=None)
        api._create_mutex = mock.Mock(side_effect=AssertionError('foreign mutation forbidden'))
        api._close = mock.Mock(return_value=True)
        self.assertEqual(api.browser_mutex(), (False, 5))
        api._open_mutex.assert_called_once_with(0x1F0001, False, 'Local\\ChromeProcessSingletonStartup!')
        api._close.assert_not_called()
        api._open_mutex.return_value = 123
        self.assertEqual(api.browser_mutex(), (True, 0))
        api._close.assert_called_once_with(123)

    def test_owned_collision_and_cleanup_failure_do_not_qualify(self):
        api = gui.NativeGUIAPI.__new__(gui.NativeGUIAPI)
        api.c = mock.Mock(get_last_error=lambda: 183, c_void_p=ctypes.c_void_p)
        api._create_mutex = mock.Mock(return_value=123)
        api._close = mock.Mock(return_value=True)
        self.assertEqual(api.own_mutex(), (False, 183))
        api._close.assert_called_once_with(123)
        args = api._create_mutex.call_args.args
        self.assertEqual(args[:2], (None, False))
        self.assertRegex(args[2], r'^Local\\oneirodex-fixture-[a-f0-9]{32}$')
        api.c.get_last_error = lambda: 5
        api._create_window = mock.Mock(return_value=456)
        api._destroy_window = mock.Mock(return_value=False)
        self.assertEqual(api.message_window(), (False, 5))
        api._destroy_window.assert_called_once_with(456)
        args = api._create_window.call_args.args
        self.assertEqual(args[:4], (0, 'STATIC', None, 0))
        self.assertEqual(args[8].value, ctypes.c_void_p(-3).value)

    def test_lock_control_requires_create_new_and_delete_on_close(self):
        api = gui.NativeGUIAPI.__new__(gui.NativeGUIAPI)
        api.c = mock.Mock(get_last_error=lambda: 5, c_void_p=ctypes.c_void_p)
        api._create_file = mock.Mock(return_value=123)
        api._close = mock.Mock(return_value=True)
        path = mock.Mock(__str__=lambda self: 'PRIVATE', exists=lambda: False)
        self.assertEqual(api.lock_file(path), (True, 0))
        api._create_file.assert_called_once_with('PRIVATE', 0x40010000, 1, None, 1, 0x04000080, None)
        api._close.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
