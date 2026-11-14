"""DB/UI-free contracts for the packaged Windows acceptance probe."""
import hashlib
import io
from pathlib import Path
import tempfile
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


if __name__ == '__main__':
    unittest.main()
