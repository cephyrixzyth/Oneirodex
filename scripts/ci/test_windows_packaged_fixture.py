"""Package orchestration faults use fake installers, accounts, browser and IPC."""
import inspect
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import probe_windows_packaged as probe


class PackagedFixtureTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(probe, '_open_standard_fixture', None)),
                        'Actual package execution requires the qualified ordinary-account fixture')
        self.assertTrue(callable(getattr(probe, '_controller_metadata', None)))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.fixture = mock.Mock()
        self.fixture.work = self.work / 'ordinary-account'
        self.fixture.work.mkdir()
        self.profile = self.work / 'ordinary-profile'
        self.directory = self.profile / 'installs'
        self.directory.mkdir(parents=True)
        self.fixture.profile_root = str(self.profile)
        self.fixture.environment = {'USERPROFILE': str(self.profile)}
        self.fixture.receipt = {'standard_user_verified': True, 'profile_environment_verified': True,
                                'private_desktop_created': True, 'cleanup_verified': False,
                                'cleanup_errors': [], 'PRIVATE': 'PRIVATE'}
        self.fixture.close.side_effect = lambda: self.fixture.receipt.update(cleanup_verified=True)
        self.install_status, self.uninstall_status = 0, 0
        self.calls = []
        self.installer = self.work / 'Oneirodex_1.1.9_x64-setup.exe'
        self.installer.write_bytes(b'controlled pinned installer')
        self.fixture.start.side_effect = self.start

    def start(self, executable, environment, arguments):
        result = self.command([str(executable), *arguments], env=environment)
        process = mock.Mock(security={'elevated': False, 'integrity_rid': 8192,
                                      'same_fixture_account': True})
        process.wait.return_value = result.returncode
        return process

    def command(self, args, **kwargs):
        self.calls.append(args)
        self.assertNotIn('GH_TOKEN', kwargs['env'])
        installed = self.fixture.work / 'installed'
        if str(args[0]).endswith('uninstall.exe'):
            if self.uninstall_status == 0:
                for child in installed.glob('*.exe'):
                    child.unlink()
            return subprocess.CompletedProcess(args, self.uninstall_status)
        self.assertEqual(args[-1], '/D=' + str(installed))
        installed.mkdir()
        (installed / 'oneirodex-desktop.exe').write_bytes(b'controlled installed binary')
        (installed / 'uninstall.exe').write_bytes(b'controlled uninstaller')
        return subprocess.CompletedProcess(args, self.install_status)

    def execute(self, cold):
        self.progress = {'installed_runtime_acceptance': False}
        with mock.patch.object(probe, 'require_ci_execution'), \
             mock.patch.object(probe, '_open_standard_fixture', return_value=self.fixture), \
             mock.patch.object(probe, '_controller_metadata', return_value={'ci_account_elevated': True, 'windows_build': 1}), \
             mock.patch.object(probe, '_cold_start', cold), \
             mock.patch.object(probe.subprocess, 'run', side_effect=AssertionError('privileged installer execution forbidden')), \
             mock.patch.object(probe, '_wait', side_effect=lambda check, *args: self.assertTrue(check())), \
             mock.patch.object(probe, 'start_standard_user', side_effect=AssertionError('retired token path forbidden')):
            return probe.execute_cold_probe(self.installer, self.work, self.progress)

    def test_two_rounds_use_one_qualified_fixture_then_uninstall_before_profile_cleanup(self):
        cold = mock.Mock(return_value=(self.directory, {'native_ipc': True}))
        result = self.execute(cold)
        self.assertEqual(cold.call_count, 2)
        self.assertTrue(all(call.args[-1] is self.fixture for call in cold.call_args_list))
        self.assertTrue(result['standard_user_fixture']['cleanup_verified'])
        self.assertTrue(result['owned_application_uninstalled'])
        self.assertTrue(result['fixture_installer_copy_verified'])
        self.assertFalse(result['installer_launch_security']['elevated'])
        self.assertFalse(result['uninstaller_launch_security']['elevated'])
        self.assertTrue(result['owned_installs_marker_retained_by_uninstaller'])
        self.assertFalse(result['installed_runtime_acceptance'])
        self.assertFalse(list(self.directory.iterdir()))
        self.fixture.close.assert_called_once_with()
        self.assertNotIn('PRIVATE', repr(result))
        self.assertNotIn(str(self.profile), repr(result))

    def test_unqualified_fixture_prevents_installer_execution(self):
        self.fixture.receipt['standard_user_verified'] = False
        with self.assertRaisesRegex(probe.ProbeFailure, 'fixture_not_verified'):
            self.execute(mock.Mock())
        self.assertEqual(self.calls, [])
        self.fixture.close.assert_called_once_with()

    def test_native_ui_failure_survives_uninstaller_failure_and_fixture_is_closed(self):
        self.uninstall_status = 1
        with self.assertRaisesRegex(probe.ProbeFailure, 'synthetic_native_ui_failure') as failed:
            self.execute(mock.Mock(side_effect=probe.ProbeFailure('synthetic_native_ui_failure')))
        self.assertIn('owned_package_cleanup_failed', failed.exception.__notes__)
        self.assertIn('owned_uninstall_failed', self.progress['package_cleanup_errors'])
        self.fixture.close.assert_called_once_with()

    def test_partial_install_failure_attempts_owned_uninstall_and_preserves_primary_error(self):
        self.install_status = 1
        cold = mock.Mock()
        with self.assertRaisesRegex(probe.ProbeFailure, 'silent_install_failed'):
            self.execute(cold)
        cold.assert_not_called()
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(self.progress['owned_application_uninstalled'])
        self.fixture.close.assert_called_once_with()

    def test_profile_cleanup_failure_prevents_success_after_passing_cold_rounds(self):
        def failed_close():
            self.fixture.receipt.update(cleanup_verified=False, cleanup_errors=['fixture_cleanup_failed'])
            raise RuntimeError('PRIVATE cleanup details')
        self.fixture.close.side_effect = failed_close
        with self.assertRaisesRegex(probe.ProbeFailure, 'standard_user_fixture_cleanup_failed'):
            self.execute(mock.Mock(return_value=(self.directory, {'native_ipc': True})))
        self.assertFalse(self.progress['standard_user_fixture']['cleanup_verified'])
        self.assertFalse(self.progress['installed_runtime_acceptance'])
        self.assertNotIn('PRIVATE', repr(self.progress))

    def test_missing_cleanup_verification_prevents_success_even_without_an_exception(self):
        self.fixture.close.side_effect = None
        self.fixture.close.return_value = None
        with self.assertRaisesRegex(probe.ProbeFailure, 'standard_user_fixture_cleanup_failed'):
            self.execute(mock.Mock(return_value=(self.directory, {'native_ipc': True})))
        self.assertFalse(self.progress['standard_user_fixture']['cleanup_verified'])

    def test_controlled_fixture_launch_error_keeps_its_code_in_package_failure(self):
        from windows_user_fixture import FixtureFailure
        with self.assertRaises(Exception) as failed:
            self.execute(mock.Mock(side_effect=FixtureFailure('fixture_create_logon_child_winerror_740')))
        self.assertIsInstance(failed.exception, probe.ProbeFailure)
        self.assertEqual(str(failed.exception), 'fixture_create_logon_child_winerror_740')
        self.assertTrue(self.progress['standard_user_fixture']['cleanup_verified'])


class ColdStartProfileTests(unittest.TestCase):
    def test_native_ipc_directory_must_belong_to_fixture_profile_and_launch_uses_its_environment(self):
        self.assertIn('fixture', inspect.signature(probe._cold_start).parameters,
                      'Cold-start must use the actual fixture identity/profile')
        for inside in (True, False):
            with self.subTest(inside=inside), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                profile, foreign = root / 'profile', root / 'foreign'
                profile.mkdir(); foreign.mkdir()
                directory = (profile if inside else foreign) / 'installs'
                directory.mkdir()
                page = mock.Mock(url='http://tauri.localhost/')
                page.evaluate.return_value = {'bridge': True, 'fresh': True, 'emptyToken': True,
                                              'parentDenied': True, 'directory': str(directory)}
                browser = mock.Mock(contexts=[mock.Mock(pages=[page])], version='fixture')
                client = mock.Mock()
                client.chromium.connect_over_cdp.return_value = browser
                module = mock.Mock()
                module.sync_playwright.return_value.start.return_value = client
                process = mock.Mock(pid=123, security={'elevated': False, 'integrity_rid': 8192})
                process.poll.return_value = None
                context = mock.Mock(profile_root=str(profile), environment={'USERPROFILE': str(profile)})
                context.start.return_value = process
                progress = {}
                with mock.patch.dict('sys.modules', {'playwright': mock.Mock(), 'playwright.sync_api': module}), \
                     mock.patch.object(probe, 'begin_startup_trace', return_value=None), \
                     mock.patch.object(probe, '_wait'), \
                     mock.patch.object(probe, '_listener_snapshot', return_value=([{'address': '127.0.0.1', 'pid': 123}], {})), \
                     mock.patch.object(probe, '_startup_diagnostics', return_value={'observation': 'synthetic'}), \
                     mock.patch.object(probe, 'start_standard_user', side_effect=AssertionError('retired token path forbidden')):
                    if inside:
                        result, _ = probe._cold_start(root / 'never-run.exe', root, 1, progress, context)
                        self.assertEqual(result, directory.resolve())
                    else:
                        with self.assertRaisesRegex(probe.ProbeFailure, 'installs_directory_not_owned'):
                            probe._cold_start(root / 'never-run.exe', root, 1, progress, context)
                self.assertEqual(context.start.call_args.args[1]['USERPROFILE'], str(profile))
                arguments = context.start.call_args.args[1]['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS']
                self.assertIn('--enable-logging', arguments)
                self.assertIn('--log-file=', arguments)
                self.assertIn('webview-startup-1.log', arguments)
                self.assertEqual(progress['app_launch_token_policy'], 'ordinary_fixture_account_required')
                self.assertIn('native_ipc_checks', progress)
                self.assertEqual(progress['native_ipc_checks'][0]['directory_owned'], inside)
                self.assertNotIn(str(profile), repr(progress))
                process.close.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
