"""Control-script safety contracts; every process/account is a fake."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import windows_user_fixture as fixture

spec = importlib.util.find_spec('probe_windows_user_fixture')
control = __import__('probe_windows_user_fixture') if spec else None


class FakeChild:
    def __init__(self, status):
        self.status, self.closed = status, False

    def wait(self, timeout):
        return self.status

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, profile, corrupt=False, fail=False):
        self.profile_root = str(profile)
        profile.mkdir()
        self.environment = {'USERPROFILE': str(profile)}
        self.receipt = {'standard_user_verified': True, 'profile_environment_verified': True,
                        'private_desktop_created': True, 'cleanup_verified': False,
                        'cleanup_errors': [], 'PRIVATE': 'PRIVATE'}
        self.api = mock.Mock(bootstrap_executable=lambda: Path('never-run-cmd.exe'))
        self.children, self.closed = [], False
        self.corrupt, self.fail = corrupt, fail

    def start(self, executable, environment, arguments):
        if len(self.children) == 1:
            if self.corrupt:
                for marker in Path(self.profile_root).glob('oneirodex-cli-*'):
                    marker.write_bytes(b'changed fixture data')
            if self.fail:
                raise fixture.FixtureFailure('fixture_synthetic_body_failure')
        child = FakeChild(int(arguments[-1]))
        self.children.append(child)
        return child

    def close(self):
        self.closed = True
        self.receipt['cleanup_verified'] = True
        if self.fail:
            self.receipt.update(cleanup_verified=False, cleanup_errors=['fixture_cleanup_failed'])
            raise fixture.FixtureFailure('fixture_cleanup_failed')


class FixtureControlTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(control, 'A separate fixture-only control is required before package integration')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name) / 'profile'

    def test_two_known_exits_reopen_marker_and_cleanup_are_required_without_private_fields(self):
        context = FakeContext(self.profile)
        progress = {}
        result = control.run_control(Path(self.tmp.name) / 'work', progress,
                                     factory=lambda path: context)
        self.assertEqual(result['cli_exit_codes'], [37, 38])
        self.assertTrue(result['owned_profile_marker_retained_between_cli_rounds'])
        self.assertTrue(result['cleanup_verified'])
        self.assertTrue(result['native_fixture_qualified'])
        self.assertTrue(all(child.closed for child in context.children))
        self.assertTrue(context.closed)
        self.assertFalse(list(self.profile.iterdir()))
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn(str(self.profile), json.dumps(result))
        self.assertFalse(result['installed_runtime_acceptance'])

    def test_changed_marker_does_not_qualify_the_fixture(self):
        context = FakeContext(self.profile, corrupt=True)
        progress = {}
        with self.assertRaisesRegex(fixture.FixtureFailure, 'marker'):
            control.run_control(Path(self.tmp.name) / 'work', progress, factory=lambda path: context)
        self.assertFalse(progress['native_fixture_qualified'])
        self.assertTrue(context.closed)

    def test_body_failure_survives_cleanup_failure_and_both_are_visible(self):
        context = FakeContext(self.profile, fail=True)
        progress = {}
        with self.assertRaisesRegex(fixture.FixtureFailure, 'body_failure'):
            control.run_control(Path(self.tmp.name) / 'work', progress, factory=lambda path: context)
        self.assertFalse(progress['native_fixture_qualified'])
        self.assertFalse(progress['cleanup_verified'])
        self.assertEqual(progress['cleanup_errors'], ['fixture_cleanup_failed'])

    def test_local_cli_refuses_before_factory_workspace_or_system_access(self):
        out = io.StringIO()
        work = Path(self.tmp.name) / 'must-not-exist'
        with mock.patch.dict(fixture.os.environ, {}, clear=True), \
             mock.patch.object(control.StandardUserFixture, 'open') as factory, \
             contextlib.redirect_stdout(out):
            status = control.main(['--execute', '--work-dir', str(work)])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(out.getvalue())['status'], 'unsupported')
        factory.assert_not_called()
        self.assertFalse(work.exists())
        self.assertNotIn(str(work), out.getvalue())

    def test_wrong_exit_is_not_hidden_by_a_child_close_error(self):
        context = FakeContext(self.profile)
        child = FakeChild(99)
        child.close = mock.Mock(side_effect=fixture.FixtureFailure('fixture_synthetic_close_failure'))
        context.start = mock.Mock(return_value=child)
        with self.assertRaisesRegex(fixture.FixtureFailure, 'exit_mismatch') as failed:
            control.run_control(Path(self.tmp.name) / 'work', {}, factory=lambda path: context)
        self.assertIn('fixture_child_cleanup_failed', failed.exception.__notes__)

    def test_provisioning_failure_reports_allowlisted_details_and_verified_abort_cleanup(self):
        failure = fixture.FixtureFailure('fixture_account_creation_failed')
        failure.diagnostic = {'stage': 'membership', 'category': 'ResourceExists',
                              'hresult': '0x80070089', 'message': 'PRIVATE'}
        failure.cleanup_verified = True
        output = io.StringIO()
        with mock.patch.object(control, 'require_fixture_ci'), \
             mock.patch.object(control.StandardUserFixture, 'open', side_effect=failure), \
             contextlib.redirect_stdout(output):
            status = control.main(['--execute', '--work-dir', str(Path(self.tmp.name) / 'not-created')])
        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(result.get('diagnostic'), {
            'stage': 'membership', 'category': 'ResourceExists', 'hresult': '0x80070089'})
        self.assertIs(result.get('cleanup_verified'), True)
        self.assertNotIn('PRIVATE', output.getvalue())
        self.assertFalse(result['native_fixture_qualified'])


if __name__ == '__main__':
    unittest.main()
