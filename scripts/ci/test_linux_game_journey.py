"""Pure ownership/race/observation tests; never execute native games locally."""
import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from probe_linux_packaged import ProbeFailure

spec = importlib.util.find_spec('linux_game_journey')
game = __import__('linux_game_journey') if spec else None


class FakeProc:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)
        self.closed = []
    def snapshot(self, pid): return next(self.snapshots)
    def open(self, pid): return 41
    def exited(self, handle): return False
    def close(self, handle): self.closed.append(handle)


class GameJourneyContracts(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(game, 'real game ownership controls must exist')

    def snapshot(self, **changes):
        return dict({'uid': 1001, 'start': '100', 'cwd': '/owned/install',
                     'argv': ['/bin/sh', '/owned/install/game.sh', 'child']}, **changes)

    def test_foreign_argv_cwd_or_uid_refused_before_pidfd_acquisition(self):
        for changes in ({'uid': 1002}, {'cwd': '/foreign'}, {'argv': ['/bin/sh', '/foreign/game.sh', 'child']}):
            api = FakeProc([self.snapshot(**changes)])
            api.open = mock.Mock(side_effect=AssertionError('must not acquire foreign process'))
            with self.assertRaises(ProbeFailure):
                game.verified_pidfd(123, 1001, Path('/owned/install'), ['/bin/sh', '/owned/install/game.sh', 'child'], api)

    def test_pid_reuse_during_acquisition_closes_handle_without_signalling(self):
        api = FakeProc([self.snapshot(), self.snapshot(start='101')])
        with self.assertRaises(ProbeFailure):
            game.verified_pidfd(123, 1001, Path('/owned/install'), ['/bin/sh', '/owned/install/game.sh', 'child'], api)
        self.assertEqual(api.closed, [41])

    def test_stable_verified_process_keeps_held_kernel_handle(self):
        api = FakeProc([self.snapshot(), self.snapshot()])
        handle = game.verified_pidfd(123, 1001, Path('/owned/install'), ['/bin/sh', '/owned/install/game.sh', 'child'], api)
        self.assertEqual(handle, 41)
        self.assertEqual(api.closed, [])

    def test_native_inventory_rejects_unknown_or_ambiguous_launch(self):
        record = {'pid': 123, 'launch_id': 'a5d4ff66-9284-45f3-842d-fca8b7cafb04', 'game_uuid': 'game'}
        self.assertEqual(game.require_launch({'supported': True, 'unverified': 0, 'launches': [record]}, 'game'), record)
        for value in ({'supported': False, 'unverified': 0, 'launches': [record]},
                      {'supported': True, 'unverified': 1, 'launches': [record]},
                      {'supported': True, 'unverified': 0, 'launches': []},
                      {'supported': True, 'unverified': 0, 'launches': [record, record]}):
            with self.assertRaises(ProbeFailure): game.require_launch(value, 'game')

    def test_database_projection_never_returns_raw_ids_dates_or_unknown_columns(self):
        row = SimpleNamespace(user_id=7, client='desktop', status='active', ended_at=None,
                              started_at=10, last_heartbeat_at=11, token='PRIVATE', id=888)
        value = game.session_projection([row], 7)
        self.assertEqual(value, {'total': 1, 'active': 1, 'ended': 0, 'orphaned': 0,
                                 'adult_owned': True, 'desktop_only': True, 'active_heartbeat_observed': True})
        self.assertNotIn('PRIVATE', repr(value)); self.assertNotIn('888', repr(value))

    def test_missing_heartbeat_or_foreign_account_is_not_success(self):
        row = SimpleNamespace(user_id=8, client='web', status='active', ended_at=None,
                              started_at=10, last_heartbeat_at=10)
        value = game.session_projection([row], 7)
        self.assertFalse(value['adult_owned']); self.assertFalse(value['desktop_only'])
        self.assertFalse(value['active_heartbeat_observed'])

    def test_real_execution_fence_runs_before_control_directory_operations(self):
        with mock.patch.object(game, 'require_ci_execution', side_effect=ProbeFailure('no_local_game')), \
             mock.patch.object(Path, 'mkdir', side_effect=AssertionError('no local directory')):
            with self.assertRaisesRegex(ProbeFailure, 'no_local_game'):
                game.GameFixture(SimpleNamespace(env={'HOME': 'PRIVATE'}), {})

    def test_unknown_started_family_cannot_be_marked_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = game.GameFixture.__new__(game.GameFixture)
            fixture.root = Path(tmp); fixture.nonce = 'a'*32
            fixture.handles = []; fixture.stopping = False; fixture.progress = {}
            fixture.launched = True; fixture.cleaned = False
            with self.assertRaises(ProbeFailure): fixture.stop()
            self.assertFalse(fixture.progress['game_fixture_cleanup_verified'])

    def test_archive_flow_invokes_real_game_continuation_after_file_verification(self):
        import linux_installed_journey as installed
        native = mock.Mock(); native.execute_js.return_value = {'ready': True, 'state_installed': True,
            'play_enabled': True, 'reveal_enabled': True, 'cached_shelf_disclosed': True}
        fixture = SimpleNamespace(private_data={'installed_fixture':{'game_uuid':'0c798a58-1087-4a32-a257-59e96f522445','manifest':{}},
            'base_url':'http://127.0.0.1:123','tokens':{'adult':'PRIVATE'}})
        report = {}; events = []
        def checked(*args): events.append('files'); return {}
        def continuation(*args): events.append('game'); raise ProbeFailure('synthetic_game_failed')
        with mock.patch('linux_connected_journey.connect'), mock.patch.object(installed, 'ui_action'), \
             mock.patch.object(installed, 'check_native_install', side_effect=checked), \
             mock.patch.object(game, 'run_game_journey', side_effect=continuation, create=True):
            with self.assertRaisesRegex(ProbeFailure, 'synthetic_game_failed'):
                installed.run_installed_journey(native, fixture, report)
        self.assertEqual(events, ['files','files','game'])

    def test_database_observer_refuses_local_context_before_url_or_database_operations(self):
        import linux_connected_server as server
        observer = getattr(server, 'observe_game_native_fixture', None)
        self.assertIsNotNone(observer, 'real marker-fenced database observer must exist')
        with mock.patch.object(server, 'require_backend_ci', side_effect=ProbeFailure('no_local_database')), \
             mock.patch.object(server, 'validate_control_url', side_effect=AssertionError('no URL access')):
            with self.assertRaisesRegex(ProbeFailure, 'no_local_database'):
                observer({'game_uuid':'PRIVATE','user_id':7})

    def test_transient_native_preparation_does_not_substitute_for_verified_launch(self):
        record = {'pid':123,'launch_id':'a5d4ff66-9284-45f3-842d-fca8b7cafb04','game_uuid':'game'}
        native = mock.Mock()
        native.execute_async.side_effect = [{'supported':True,'unverified':1,'launches':[]},
                                           {'supported':True,'unverified':0,'launches':[record]}]
        def two_checks(check, seconds, code):
            self.assertFalse(check()); self.assertTrue(check())
        helper = getattr(game, 'wait_native_launch', None)
        self.assertIsNotNone(helper, 'must wait for positive native identity, not a transient preparation phase')
        with mock.patch.object(game, 'wait_for', side_effect=two_checks):
            self.assertEqual(helper(native, 'profile', 'game'), record)

    def test_pidfd_cleanup_failure_still_closes_every_acquired_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = game.GameFixture.__new__(game.GameFixture)
            fixture.root=Path(tmp); fixture.nonce='b'*32; fixture.stopping=False
            fixture.cleaned=False; fixture.launched=True; fixture.handles=[41,42]; fixture.progress={}
            fixture.api=mock.Mock(); fixture.api.exited.return_value=False
            with mock.patch.object(game, 'wait_for', side_effect=ProbeFailure('synthetic_timeout')):
                with self.assertRaises(ProbeFailure): fixture.stop()
            self.assertEqual(fixture.api.close.call_args_list, [mock.call(41),mock.call(42)])
            self.assertEqual(fixture.api.terminate.call_args_list, [mock.call(41),mock.call(42)])
            self.assertFalse(fixture.progress['game_fixture_cleanup_verified'])


if __name__ == '__main__': unittest.main()
