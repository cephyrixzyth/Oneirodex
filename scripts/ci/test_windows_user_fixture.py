"""Pure lifecycle checks: never create local users, profiles or desktops."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


spec = importlib.util.find_spec('windows_user_fixture')
fixture = __import__('windows_user_fixture') if spec else None
SID = 'S-1-5-21-100-200-300-1001'


class FakeAPI:
    def __init__(self, failure=None, state=None):
        self.events, self.failure, self.state_override = [], failure, state
        self.alive, self.next_handle = set(), 20

    def create_account(self, name, password, marker):
        self.events.append('account_created')
        if self.failure == 'collision':
            raise fixture.FixtureFailure('fixture_account_creation_failed')
        self.name = name
        return SID

    def open_desktop(self, sid, nonce):
        self.events.append('private_desktop')
        if self.failure == 'desktop':
            raise fixture.FixtureFailure('fixture_desktop_failed')
        return ('owned_station', 'owned_desktop', 'owned_station\\owned_desktop')

    def grant_work(self, work, sid):
        self.events.append(('grant_work', work, sid))

    def bootstrap_executable(self):
        return Path('never-run-cmd.exe')

    def spawn(self, name, password, executable, arguments, environment, desktop):
        self.events.append(('spawn', environment, desktop))
        self.next_handle += 2
        self.alive.add(self.next_handle)
        return self.next_handle, self.next_handle + 1, self.next_handle + 100

    def state(self, handle):
        self.events.append(('state', handle))
        profile = 'C:\\Users\\' + self.name
        return self.state_override or {
            'sid': SID, 'elevated': False, 'integrity_rid': 8192,
            'profile_root': profile, 'profiles_root': 'C:\\Users',
            'environment': {'USERPROFILE': profile, 'APPDATA': profile + '\\AppData\\Roaming',
                            'LOCALAPPDATA': profile + '\\AppData\\Local',
                            'GH_TOKEN': 'PRIVATE', 'ACTIONS_RUNTIME_TOKEN': 'PRIVATE'}}

    def resume(self, thread):
        self.events.append(('resume', thread))
        if self.failure == 'resume':
            raise fixture.FixtureFailure('fixture_resume_failed')

    def wait(self, handle, milliseconds):
        self.events.append(('wait', handle))
        if self.failure != 'wait' and milliseconds > 0:
            self.alive.discard(handle)
        return handle not in self.alive

    def exit_code(self, handle):
        return 0

    def terminate(self, handle):
        self.events.append(('terminate', handle))
        self.alive.discard(handle)

    def close_handle(self, handle):
        self.events.append(('close_handle', handle))

    def close_desktop(self, resources):
        self.events.append('desktop_closed')

    def delete_account(self, name, sid, marker, profile):
        self.events.append(('account_deleted', sid, profile))
        if self.failure == 'cleanup':
            raise fixture.FixtureFailure('fixture_account_cleanup_failed')


class FixtureLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(fixture, 'The identity-bound disposable fixture must be implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / 'fresh-owned-work'

    def make(self, api):
        return fixture.StandardUserFixture._open_for_api(self.work, Path(self.tmp.name), api)

    def test_profile_is_verified_before_resume_and_environment_is_filtered(self):
        api = FakeAPI()
        context = self.make(api)
        self.assertLess(api.events.index(('state', 22)), api.events.index(('resume', 23)))
        self.assertEqual(context.environment.get('USERPROFILE'), context.profile_root)
        self.assertNotIn('PRIVATE', repr(context.environment))
        self.assertNotIn('GH_TOKEN', context.environment)
        self.assertEqual(context.receipt['standard_user_verified'], True)
        context.close()
        context.close()
        self.assertEqual(api.events.count('desktop_closed'), 1)
        self.assertEqual(sum(isinstance(e, tuple) and e[0] == 'account_deleted' for e in api.events), 1)
        self.assertTrue(context.receipt['cleanup_verified'])

    def test_account_collision_does_not_delete_someone_elses_account(self):
        api = FakeAPI('collision')
        with self.assertRaisesRegex(fixture.FixtureFailure, 'creation_failed'):
            self.make(api)
        self.assertEqual(api.events, ['account_created'])

    def test_partial_desktop_failure_cleans_the_created_account(self):
        api = FakeAPI('desktop')
        with self.assertRaisesRegex(fixture.FixtureFailure, 'desktop_failed'):
            self.make(api)
        self.assertEqual(api.events[-1], ('account_deleted', SID, None))

    def test_wrong_user_or_elevation_or_profile_never_resumes(self):
        cases = [{'sid': 'S-1-5-21-999'}, {'elevated': True}, {'integrity_rid': 12288},
                 {'profile_root': 'C:\\Users\\someone-else'},
                 {'environment': {'USERPROFILE': 'C:\\Users\\runner'}}]
        for change in cases:
            with self.subTest(change=change):
                api = FakeAPI()
                original = api.state
                api.state = lambda handle: {**original(handle), **change}
                with self.assertRaises(fixture.FixtureFailure):
                    self.make(api)
                self.assertFalse(any(isinstance(e, tuple) and e[0] == 'resume' for e in api.events))
                self.assertEqual(api.events.count(('terminate', 22)), 1)
                self.assertEqual(api.events.count(('close_handle', 22)), 1)
                self.assertEqual(api.events.count(('close_handle', 23)), 1)
                self.assertFalse(api.alive)
                self.work.rmdir()

    def test_resume_failure_reaps_only_the_held_child_before_deleting_account(self):
        api = FakeAPI('resume')
        with self.assertRaisesRegex(fixture.FixtureFailure, 'resume_failed'):
            self.make(api)
        self.assertLess(api.events.index(('terminate', 22)), api.events.index('desktop_closed'))
        self.assertEqual(api.events.count(('close_handle', 22)), 1)
        self.assertEqual(api.events.count(('close_handle', 23)), 1)

    def test_close_reaps_an_owned_live_child_and_rejects_caller_credentials(self):
        api = FakeAPI()
        context = self.make(api)
        bad = {**context.environment, 'GH_TOKEN': 'PRIVATE'}
        with self.assertRaisesRegex(fixture.FixtureFailure, 'environment'):
            context.start(Path('never-run.exe'), bad, [])
        child = context.start(Path('never-run.exe'), context.environment, [])
        self.assertIn(child.handle, api.alive)
        context.close()
        self.assertFalse(api.alive)
        self.assertTrue(context.receipt['cleanup_verified'])

    def test_body_error_survives_a_cleanup_error_without_false_success(self):
        api = FakeAPI()
        context = self.make(api)
        api.failure = 'cleanup'
        with self.assertRaisesRegex(ValueError, 'body'):
            with context:
                raise ValueError('body')
        self.assertFalse(context.receipt['cleanup_verified'])
        self.assertEqual(context.receipt['cleanup_errors'], ['fixture_account_cleanup_failed'])
        self.assertNotIn('PRIVATE', repr(context.receipt))

    def test_failed_child_reap_preserves_account_and_desktop_instead_of_deleting_live_resources(self):
        api = FakeAPI()
        context = self.make(api)
        child = context.start(Path('never-run.exe'), context.environment, [])
        def cannot_terminate(handle):
            raise fixture.FixtureFailure('fixture_synthetic_termination_failure')
        api.terminate = cannot_terminate
        with self.assertRaises(fixture.FixtureFailure):
            context.close()
        self.assertIn(child.handle, api.alive)
        self.assertNotIn('desktop_closed', api.events)
        self.assertFalse(any(isinstance(e, tuple) and e[0] == 'account_deleted' for e in api.events))
        self.assertFalse(context.receipt['cleanup_verified'])

    def test_child_identity_error_survives_overlapping_termination_failure(self):
        api = FakeAPI()
        context = self.make(api)
        original_state, original_terminate = api.state, api.terminate
        api.state = lambda handle: {**original_state(handle), 'sid': 'S-1-5-18'}
        def cannot_terminate(handle):
            raise fixture.FixtureFailure('fixture_synthetic_termination_failure')
        api.terminate = cannot_terminate
        with self.assertRaisesRegex(fixture.FixtureFailure, 'child_identity_not_verified') as failed:
            context.start(Path('never-run.exe'), context.environment, [])
        self.assertIn('fixture_child_cleanup_failed', failed.exception.__notes__)
        api.terminate = original_terminate
        context.close()

    def test_reused_or_outside_workspace_is_rejected_before_account_creation(self):
        for work in (Path(self.tmp.name), Path(self.tmp.name).parent / 'outside-fixture'):
            api = FakeAPI()
            with self.assertRaises(fixture.FixtureFailure):
                fixture.StandardUserFixture._open_for_api(work, Path(self.tmp.name), api)
            self.assertEqual(api.events, [])

    def test_local_execution_is_refused_before_native_library_or_workspace_access(self):
        with mock.patch.dict(fixture.os.environ, {}, clear=True), \
             mock.patch.object(fixture, 'NativeFixtureAPI') as native:
            with self.assertRaisesRegex(fixture.FixtureFailure, 'disposable_windows_ci'):
                fixture.StandardUserFixture.open(self.work)
            native.assert_not_called()
        self.assertFalse(self.work.exists())


class NativeBindingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(fixture)

    def test_logon_uses_explicit_image_profile_unicode_suspension_and_private_desktop(self):
        import ctypes as c
        from ctypes import wintypes as w
        class Startup(c.Structure):
            _fields_ = [('cb', w.DWORD), ('lpDesktop', w.LPWSTR)]
        class Info(c.Structure):
            _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE), ('dwProcessId', w.DWORD)]
        api = object.__new__(fixture.NativeFixtureAPI)
        api.c, api.w, api.STARTUPINFO, api.PROCESSINFO = c, w, Startup, Info
        secret_buffers = []
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / 'not executed.exe'
            executable.write_bytes(b'not executable')
            def create(*args):
                self.assertEqual(len(args), 11)
                self.assertEqual((args[0], args[1]), ('odci0123456789ab', '.'))
                self.assertEqual(args[2].value, 'PRIVATE')
                secret_buffers.append(args[2])
                self.assertEqual(args[3], 1)
                self.assertEqual(args[4], str(executable.resolve()))
                self.assertEqual(args[5].value, '"' + str(executable.resolve()) + '" /d /c exit 37')
                self.assertEqual(args[6], 0x404)
                self.assertIn('USERPROFILE=owned', ''.join(args[7]))
                self.assertEqual(args[8], str(executable.resolve().parent))
                self.assertEqual(args[9]._obj.lpDesktop, 'odci-owned\\private')
                result = args[10]._obj
                result.hProcess, result.hThread, result.dwProcessId = 21, 22, 23
                return True
            api._create_logon = create
            self.assertTrue(callable(getattr(api, 'spawn', None)), 'Native logon binding must exist')
            self.assertEqual(api.spawn('odci0123456789ab', 'PRIVATE', executable,
                                       ['/d', '/c', 'exit', '37'], {'USERPROFILE': 'owned'},
                                       'odci-owned\\private'), (21, 22, 23))
            self.assertTrue(all(value == '\0' for value in secret_buffers[0]))

    def test_account_password_is_sent_only_through_stdin_and_raw_errors_are_not_returned(self):
        import subprocess
        api = object.__new__(fixture.NativeFixtureAPI)
        api.powershell = 'never-executed-powershell.exe'
        api.observer_env = {'SystemRoot': 'system'}
        self.assertTrue(callable(getattr(api, 'create_account', None)))
        with mock.patch.object(fixture.subprocess, 'run', return_value=subprocess.CompletedProcess(
                [], 1, stdout='PRIVATE', stderr='PRIVATE C:\\operator')) as run:
            with self.assertRaises(fixture.FixtureFailure) as failed:
                api.create_account('odci0123456789ab', 'PRIVATE', 'oneirodex-ci-' + 'a' * 32)
        self.assertNotIn('PRIVATE', str(failed.exception))
        self.assertNotIn('operator', str(failed.exception))
        args, kwargs = run.call_args_list[0]
        self.assertNotIn('PRIVATE', repr(args))
        self.assertNotIn('PRIVATE', repr(kwargs['env']))
        self.assertIn('PRIVATE', kwargs['input'])
        self.assertEqual(kwargs['timeout'], 60)
        for args, kwargs in run.call_args_list:
            self.assertNotIn('PRIVATE', repr(args))
            self.assertNotIn('PRIVATE', repr(kwargs['env']))

    def test_invalid_account_cleanup_identity_is_rejected_before_any_system_command(self):
        api = object.__new__(fixture.NativeFixtureAPI)
        self.assertTrue(callable(getattr(api, 'delete_account', None)))
        with mock.patch.object(fixture.subprocess, 'run') as run:
            for name, sid in [('Administrator', SID), ('odci0123456789ab', 'S-1-5-18')]:
                with self.subTest(name=name), self.assertRaises(fixture.FixtureFailure):
                    api.delete_account(name, sid, 'oneirodex-ci-' + 'a' * 32, None)
        run.assert_not_called()

    def test_account_failure_keeps_only_allowlisted_diagnostics_and_cleanup_result(self):
        import json
        import subprocess
        api = object.__new__(fixture.NativeFixtureAPI)
        api.powershell, api.observer_env = 'never-run.exe', {}
        response = {'stage': 'membership', 'category': 'ResourceExists', 'hresult': '0x80070089',
                    'message': 'PRIVATE', 'sid': SID}
        results = [subprocess.CompletedProcess([], 1, json.dumps(response), 'PRIVATE'),
                   subprocess.CompletedProcess([], 0, '{"removed":true}', '')]
        with mock.patch.object(fixture.subprocess, 'run', side_effect=results):
            with self.assertRaises(fixture.FixtureFailure) as failed:
                api.create_account('odci0123456789ab', 'PRIVATE', 'oneirodex-ci-' + 'a' * 32)
        self.assertEqual(getattr(failed.exception, 'diagnostic', None), {
            'stage': 'membership', 'category': 'ResourceExists', 'hresult': '0x80070089'})
        self.assertIs(getattr(failed.exception, 'cleanup_verified', None), True)
        self.assertNotIn('PRIVATE', repr(failed.exception.__dict__))

    def test_failed_desktop_creation_restores_borrowed_station_and_closes_only_new_objects(self):
        from contextlib import nullcontext
        api = object.__new__(fixture.NativeFixtureAPI)
        self.assertTrue(callable(getattr(api, 'open_desktop', None)))
        events = []
        api._security = lambda sid: nullcontext('explicit_owner_security')
        api._get_station, api._thread_id, api._get_desktop = lambda: 1, lambda: 3, lambda thread: 2
        api._create_station = lambda name, flags, rights, security: (
            self.assertEqual((flags, security), (1, 'explicit_owner_security')) or 4)
        api._set_station = lambda handle: events.append(('station', handle)) or True
        api._set_desktop = lambda handle: events.append(('desktop', handle)) or True
        api._create_desktop = lambda *args: 0
        api._close_station = lambda handle: events.append(('close_station', handle)) or True
        api._close_desktop = lambda handle: events.append(('close_desktop', handle)) or True
        def check(result, code):
            if not result:
                raise fixture.FixtureFailure(code)
        api._checked = check
        with self.assertRaises(fixture.FixtureFailure):
            api.open_desktop(SID, 'a' * 32)
        self.assertIn(('station', 1), events)
        self.assertIn(('desktop', 2), events)
        self.assertEqual(events.count(('close_station', 4)), 1)
        self.assertNotIn(('close_station', 1), events)
        self.assertNotIn(('close_desktop', 2), events)

    def test_new_desktop_security_has_explicit_medium_label_and_only_owned_principals(self):
        import ctypes as c
        from ctypes import wintypes as w
        class Attributes(c.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]
        api = object.__new__(fixture.NativeFixtureAPI)
        api.c, api.SecurityAttributes = c, Attributes
        captured = []
        def descriptor(sddl, revision, output, size):
            captured.append(sddl)
            output._obj.value = 111
            return True
        api._descriptor = descriptor
        api._free = lambda value: captured.append('descriptor_freed')
        with api._security(SID) as attributes:
            self.assertFalse(attributes._obj.inherit)
        self.assertIn('S:(ML;;NW;;;ME)', captured[0])
        self.assertEqual(captured[0].count('(A;;GA;;;'), 3)
        self.assertIn('(A;;GA;;;' + SID + ')', captured[0])
        self.assertNotIn(';;;WD)', captured[0])
        self.assertEqual(captured[-1], 'descriptor_freed')


if __name__ == '__main__':
    unittest.main()
