"""DB/UI-free contracts for the packaged Windows acceptance probe."""
import hashlib
import io
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock
import zipfile
import contextlib
import probe_windows_packaged as probe

from probe_windows_packaged import (
    ProbeFailure, create_workspace, extract_installer, require_ci_execution,
    validate_source, verify_digest, listener_is_owned, runtime_environment, safe_process_diagnostic,
)

SOURCE = '6a03c6fbdadcdc8f585d0012b3a36879e408fa0b'
DIGEST = 'a' * 64
INSTALLER = 'Oneirodex_1.1.9_x64-setup.exe'


class PackageGuardTests(unittest.TestCase):
    def metadata(self):
        return ({'head_sha': SOURCE, 'head_branch': 'codex/release-v1.1.9',
                 'event': 'push', 'status': 'completed', 'conclusion': 'success'},
                [{'id': 123, 'name': 'oneirodex-full-windows', 'expired': False,
                  'digest': 'sha256:' + DIGEST, 'size_in_bytes': 200}])

    def test_only_the_expected_successful_push_artifact_is_selected(self):
        run, artifacts = self.metadata()
        self.assertEqual(validate_source(run, artifacts, SOURCE, DIGEST)['id'], 123)

    def test_wrong_source_branch_event_or_non_success_cannot_install(self):
        for key, value in [('head_sha', 'b' * 40), ('head_branch', 'main'),
                           ('event', 'pull_request'), ('status', 'in_progress'),
                           ('conclusion', 'failure')]:
            with self.subTest(key=key):
                run, artifacts = self.metadata()
                run[key] = value
                with self.assertRaises(ProbeFailure):
                    validate_source(run, artifacts, SOURCE, DIGEST)

    def test_wrong_flavor_expired_mismatched_oversized_or_ambiguous_artifacts_fail(self):
        for key, value in [('name', 'oneirodex-thin-windows'), ('expired', True),
                           ('digest', 'sha256:' + 'b' * 64), ('size_in_bytes', 100_000_000)]:
            with self.subTest(key=key):
                run, artifacts = self.metadata()
                artifacts[0][key] = value
                with self.assertRaises(ProbeFailure):
                    validate_source(run, artifacts, SOURCE, DIGEST)
        run, artifacts = self.metadata()
        with self.assertRaises(ProbeFailure):
            validate_source(run, artifacts + artifacts, SOURCE, DIGEST)

    def test_actual_archive_bytes_must_match_the_pinned_digest(self):
        data = b'owned fixture'
        verify_digest(data, hashlib.sha256(data).hexdigest())
        with self.assertRaises(ProbeFailure):
            verify_digest(data + b'corrupt', hashlib.sha256(data).hexdigest())

    def archive(self, names):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name in names:
                archive.writestr(name, b'owned fixture; never executed')
        return stream.getvalue()

    def test_one_regular_installer_is_written_without_extractall(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = extract_installer(self.archive([INSTALLER]), Path(tmp))
            self.assertEqual(path.name, INSTALLER)
            self.assertEqual(path.read_bytes(), b'owned fixture; never executed')

    def test_traversal_absolute_backslash_and_ambiguous_payloads_fail(self):
        cases = [['../' + INSTALLER], ['/' + INSTALLER], ['C:/' + INSTALLER],
                 ['folder\\' + INSTALLER], [INSTALLER, 'other/' + INSTALLER],
                 ['not-an-installer.txt']]
        with tempfile.TemporaryDirectory() as tmp:
            for names in cases:
                with self.subTest(names=names), self.assertRaises(ProbeFailure):
                    extract_installer(self.archive(names), Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_symlink_payload_is_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            entry = zipfile.ZipInfo(INSTALLER)
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, b'outside')
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProbeFailure):
            extract_installer(stream.getvalue(), Path(tmp))

    def test_workspace_is_fresh_and_strictly_under_the_owned_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = create_workspace(root / 'owned', root)
            self.assertEqual(work, (root / 'owned').resolve())
            for path in [root, root / '..' / 'outside', work]:
                with self.subTest(path=path), self.assertRaises(ProbeFailure):
                    create_workspace(path, root)

    def test_execute_is_fenced_to_an_explicit_windows_github_runner(self):
        env = {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Windows',
               'GITHUB_REPOSITORY': 'cephyrixzyth/Oneirodex', 'GITHUB_RUN_ID': '123'}
        require_ci_execution('nt', env)
        for platform, values in [('posix', env), ('nt', {}), ('nt', {**env, 'RUNNER_OS': 'Linux'}),
                                 ('nt', {**env, 'GITHUB_REPOSITORY': 'other/repo'})]:
            with self.subTest(platform=platform, values=values), self.assertRaises(ProbeFailure):
                require_ci_execution(platform, values)

    def test_debug_endpoint_must_be_loopback_and_descended_from_the_live_app(self):
        self.assertTrue(listener_is_owned([{'address': '127.0.0.1', 'pid': 12}], {12: 11, 11: 10}, 10))
        self.assertTrue(listener_is_owned([{'address': '::1', 'pid': 11}], {11: 10}, 10))
        for listeners, parents in [([], {}), ([{'address': '0.0.0.0', 'pid': 11}], {11: 10}),
                                   ([{'address': '127.0.0.1', 'pid': 11}], {11: 9}),
                                   ([{'address': '127.0.0.1', 'pid': 11}], {11: 12, 12: 11})]:
            with self.subTest(listeners=listeners):
                self.assertFalse(listener_is_owned(listeners, parents, 10))

    def test_installer_and_app_environment_does_not_receive_ci_credentials(self):
        selected = runtime_environment({'SystemRoot': 'system', 'PATH': 'tools',
                                        'USERPROFILE': 'profile', 'GH_TOKEN': 'do-not-forward',
                                        'ACTIONS_RUNTIME_TOKEN': 'do-not-forward', 'DATABASE_URL': 'private'})
        self.assertEqual(selected, {'SystemRoot': 'system', 'PATH': 'tools', 'USERPROFILE': 'profile'})

    def test_runtime_failure_is_not_reported_as_a_successful_inspection(self):
        # Both installer paths are replaced: this fault test cannot launch an app.
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            argv = ['probe', '--source-run', '1', '--expected-source', SOURCE,
                    '--artifact-digest', DIGEST, '--work-dir', str(work), '--execute']
            output = io.StringIO()
            with mock.patch('sys.argv', argv), contextlib.redirect_stdout(output), \
                 mock.patch.object(probe, 'require_ci_execution'), \
                 mock.patch.object(probe, 'inspect_package', return_value=(work, work / 'never-run.exe', {})), \
                 mock.patch.object(probe, 'execute_cold_probe', side_effect=ProbeFailure('synthetic_runtime_failure')):
                code = probe.main()
            self.assertEqual(code, 1)
            self.assertEqual(__import__('json').loads(output.getvalue())['status'], 'failed')

    def test_failure_diagnostics_do_not_serialize_command_lines_or_paths(self):
        raw = {'pid': 12, 'parent': 10, 'name': 'msedgewebview2.exe',
               'command': 'browser --remote-debugging-port=1234 --user-data-dir=private/webview-profile SECRET-VALUE'}
        selected = safe_process_diagnostic(raw, 1234)
        self.assertTrue(selected['expected_debug_port_flag'])
        self.assertTrue(selected['probe_profile_flag'])
        self.assertNotIn('SECRET-VALUE', repr(selected))
        self.assertNotIn('private/', repr(selected))
        self.assertNotIn('command', selected)

    def test_browser_client_stop_failure_still_reaps_and_closes_the_owned_app(self):
        client = mock.Mock()
        client.chromium.connect_over_cdp.side_effect = ProbeFailure('synthetic_connect_failure')
        client.stop.side_effect = RuntimeError('synthetic_client_stop_failure')
        module = mock.Mock()
        module.sync_playwright.return_value.start.return_value = client
        process = mock.Mock(pid=123, security={'elevated': False, 'integrity_rid': 8192})
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict('sys.modules', {'playwright': mock.Mock(), 'playwright.sync_api': module}), \
             mock.patch.object(probe, 'start_standard_user', return_value=process), \
             mock.patch.object(probe, '_wait'), \
             mock.patch.object(probe, '_listener_snapshot', return_value=(
                 [{'address': '127.0.0.1', 'pid': 123}], {})), \
             mock.patch.object(probe, '_startup_diagnostics', return_value={'observation': 'synthetic'}):
            with self.assertRaisesRegex(RuntimeError, 'synthetic_client_stop_failure'):
                probe._cold_start(Path('never-executed.exe'), Path(tmp), 1, {})
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=20)
        process.close.assert_called_once_with()




class StandardUserLaunchTests(unittest.TestCase):
    """No Win32 calls: verify suspended launch policy and owned-handle lifetime."""
    class API:
        def __init__(self, security=None, fail=None):
            self.security = security or {'elevated': False, 'integrity_rid': 8192}
            self.fail = fail
            self.events = []
            self.exited = False

        def restricted_token(self):
            self.events.append('restricted_token')
            return 'token'

        def create_suspended(self, token, executable, env):
            self.events.append('create_suspended')
            if self.fail == 'create':
                raise ProbeFailure('synthetic_create_failure')
            return 'process_handle', 'thread_handle', 123

        def process_security(self, handle):
            self.events.append(('security', handle))
            return self.security

        def resume(self, handle):
            self.events.append(('resume', handle))
            if self.fail == 'resume':
                raise ProbeFailure('synthetic_resume_failure')

        def terminate(self, handle):
            self.events.append(('terminate', handle))
            self.exited = True

        def wait(self, handle, milliseconds):
            self.events.append(('wait', handle, milliseconds))
            return self.exited

        def exit_code(self, handle):
            return 259  # A legitimate final exit code, not an "alive" assertion.

        def close_handle(self, handle):
            self.events.append(('close', handle))

    def setUp(self):
        self.assertTrue(callable(getattr(probe, '_start_standard_user', None)),
                        'A suspended, verified non-elevated launch path is required')

    def test_medium_non_elevated_token_is_checked_before_the_app_can_execute(self):
        api = self.API()
        process = probe._start_standard_user(Path('never-executed.exe'), {}, api)
        self.assertEqual(api.events, ['restricted_token', 'create_suspended', ('close', 'token'),
                                     ('security', 'process_handle'), ('resume', 'thread_handle'),
                                     ('close', 'thread_handle')])
        self.assertEqual(process.pid, 123)
        self.assertEqual(process.security, {'elevated': False, 'integrity_rid': 8192})
        process.close()

    def test_elevated_or_wrong_integrity_child_never_resumes_and_is_reaped(self):
        for state in [{'elevated': True, 'integrity_rid': 8192},
                      {'elevated': False, 'integrity_rid': 12288},
                      {'elevated': False, 'integrity_rid': 4096}]:
            with self.subTest(state=state):
                api = self.API(state)
                with self.assertRaisesRegex(ProbeFailure, 'child_not_standard_integrity'):
                    probe._start_standard_user(Path('never-executed.exe'), {}, api)
                self.assertNotIn(('resume', 'thread_handle'), api.events)
                self.assertIn(('terminate', 'process_handle'), api.events)
                self.assertIn(('wait', 'process_handle', 20000), api.events)
                for handle in ['token', 'process_handle', 'thread_handle']:
                    self.assertEqual(api.events.count(('close', handle)), 1)

    def test_failed_creation_closes_token_without_inventing_a_process_handle(self):
        api = self.API(fail='create')
        with self.assertRaisesRegex(ProbeFailure, 'synthetic_create_failure'):
            probe._start_standard_user(Path('never-executed.exe'), {}, api)
        self.assertEqual(api.events, ['restricted_token', 'create_suspended', ('close', 'token')])

    def test_failed_resume_terminates_only_the_retained_child_handle(self):
        api = self.API(fail='resume')
        with self.assertRaisesRegex(ProbeFailure, 'synthetic_resume_failure'):
            probe._start_standard_user(Path('never-executed.exe'), {}, api)
        self.assertIn(('terminate', 'process_handle'), api.events)
        for handle in ['token', 'process_handle', 'thread_handle']:
            self.assertEqual(api.events.count(('close', handle)), 1)

    def test_timeout_keeps_the_owned_handle_for_cleanup_and_final_259_is_an_exit(self):
        api = self.API()
        process = probe._start_standard_user(Path('never-executed.exe'), {}, api)
        self.assertIsNone(process.poll())
        with self.assertRaises(subprocess.TimeoutExpired):
            process.wait(timeout=1)
        self.assertNotIn(('close', 'process_handle'), api.events)
        process.terminate()
        self.assertEqual(process.poll(), 259)
        self.assertEqual(process.wait(timeout=1), 259)
        process.close()
        process.close()
        self.assertEqual(api.events.count(('close', 'process_handle')), 1)

    def test_native_factory_refuses_local_execution_before_loading_windows_api(self):
        with mock.patch.dict(probe.os.environ, {}, clear=True), \
             mock.patch.object(probe, '_WindowsStandardAPI') as native:
            with self.assertRaisesRegex(ProbeFailure, 'execution_requires_disposable_windows_ci'):
                probe.start_standard_user(Path('never-executed.exe'), {})
            native.assert_not_called()

    def test_unicode_environment_has_a_double_terminator_and_no_ambiguous_keys(self):
        block = probe.windows_environment_block({'z': 'last', 'APPDATA': 'owned-é'})
        self.assertEqual(block, 'APPDATA=owned-é\0z=last\0\0')
        for env in [{'A': 'one', 'a': 'two'}, {'bad=key': 'value'},
                    {'key': 'bad\0value'}, {'': 'value'}, {'key': 42}]:
            with self.subTest(env=env), self.assertRaises(ProbeFailure):
                probe.windows_environment_block(env)


if __name__ == '__main__':
    unittest.main()
