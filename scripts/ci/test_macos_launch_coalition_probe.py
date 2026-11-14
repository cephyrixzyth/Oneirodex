"""Controller safety regressions; these mocks do not qualify macOS APIs."""
import importlib.util
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    'coalition_probe', Path(__file__).with_name('probe-macos-launch-coalition.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
ROOT = Path(__file__).resolve().parents[2]
TEMP_FACTORY = tempfile.TemporaryDirectory


class OwnedProcess:
    def wait(self, timeout):
        return 0

    def kill(self):
        raise AssertionError('responsive owned outsider should not be killed')


class ControllerSafety(unittest.TestCase):
    def exercise(self, bootstrap, snapshots, cleanup_return=0, remains=False,
                 expected_exception=None, diagnostic='', domain='user'):
        calls = []
        report = {'api_and_job_isolation_passed': False}

        def command(*args):
            calls.append(args)
            if args[0] == 'bootstrap':
                if isinstance(bootstrap, Exception):
                    raise bootstrap
                return types.SimpleNamespace(returncode=bootstrap,
                                             stdout=diagnostic, stderr=diagnostic)
            if args[0] == 'bootout':
                return types.SimpleNamespace(returncode=cleanup_return)
            if args[0] == 'print':
                return types.SimpleNamespace(returncode=0 if remains else 113,
                                             stderr='Could not find service fixture')
            return types.SimpleNamespace(returncode=0)

        def temporary(**kwargs):
            return TEMP_FACTORY(dir=ROOT / '.artifacts', **kwargs)

        api = types.SimpleNamespace(own_snapshot=lambda: {'coalition_id': 100})
        with patch.object(probe, 'sys', types.SimpleNamespace(platform='darwin', executable='fixture-python')), \
                patch.object(probe, 'os', types.SimpleNamespace(geteuid=lambda: 501)), \
                patch.object(probe, 'CoalitionAPI', return_value=api), \
                patch.object(probe, 'ready', side_effect=snapshots), \
                patch.object(probe, 'launchctl', side_effect=command), \
                patch.object(probe.subprocess, 'Popen', return_value=OwnedProcess()), \
                patch.object(probe.tempfile, 'TemporaryDirectory', side_effect=temporary):
            expected = expected_exception or (probe.Unsupported, RuntimeError, subprocess.TimeoutExpired)
            with self.assertRaises(expected):
                probe.probe(report, domain=domain)
        return calls, report

    def test_partial_bootstrap_error_still_unloads_attempted_exact_job(self):
        calls, report = self.exercise(5, [{'coalition_id': 100}])
        bootstrap = next(c for c in calls if c[0] == 'bootstrap')
        label = Path(bootstrap[2]).stem
        self.assertIn(('bootout', 'user/501/' + label), calls)
        self.assertFalse(report['api_and_job_isolation_passed'])

    def test_bootstrap_timeout_still_unloads_attempted_exact_job(self):
        calls, _ = self.exercise(subprocess.TimeoutExpired('fixture', 1),
                                 [{'coalition_id': 100}])
        bootstrap = next(c for c in calls if c[0] == 'bootstrap')
        self.assertIn(('bootout', 'user/501/' + Path(bootstrap[2]).stem), calls)

    def test_shared_outside_coalition_cannot_pass_isolation(self):
        _, report = self.exercise(0, [{'coalition_id': 100},
                                     {'coalition_id': 100, 'active': 1},
                                     {'coalition_id': 200, 'active': 1}])
        self.assertFalse(report['api_and_job_isolation_passed'])

    def test_rejected_bootstrap_with_absent_job_preserves_unsupported(self):
        self.exercise(5, [{'coalition_id': 100}], cleanup_return=113,
                      expected_exception=probe.Unsupported)

    def test_bootout_success_with_still_loaded_job_cannot_pass(self):
        self.exercise(0, [{'coalition_id': 100},
                          {'coalition_id': 200, 'active': 1},
                          {'coalition_id': 300, 'active': 1}], remains=True,
                      expected_exception=RuntimeError)

    def test_bootstrap_failure_preserves_reason_with_host_paths_redacted(self):
        _, report = self.exercise(5, [{'coalition_id': 100}], diagnostic=(
            'Bootstrap failed: 5: Input/output error at /Users/fixture/private/job.plist '
            'and C:\\fixture\\private\\job.plist'))
        self.assertIn('bootstrap_diagnostics', report)
        entry = report['bootstrap_diagnostics'][0]
        self.assertEqual(entry['exit_code'], 5)
        for field in ('stdout', 'stderr'):
            self.assertIn('Input/output error', entry[field])
            self.assertNotIn('/Users/', entry[field])
            self.assertNotIn('C:\\', entry[field])
            self.assertLessEqual(len(entry[field]), 2048)
        self.assertFalse(report['api_and_job_isolation_passed'])

    def test_root_cannot_qualify_ordinary_user_capability(self):
        with patch.object(probe, 'sys', types.SimpleNamespace(platform='darwin')), \
                patch.object(probe, 'os', types.SimpleNamespace(geteuid=lambda: 0)), \
                patch.object(probe, 'CoalitionAPI') as api:
            with self.assertRaises(probe.Unsupported):
                probe.probe({})
            api.assert_not_called()

    def test_explicit_gui_probe_keeps_bootstrap_and_cleanup_in_own_gui_domain(self):
        calls, report = self.exercise(5, [{'coalition_id': 100}], domain='gui')
        bootstrap = next(call for call in calls if call[0] == 'bootstrap')
        self.assertEqual(bootstrap[1], 'gui/501')
        self.assertIn(('bootout', 'gui/501/' + Path(bootstrap[2]).stem), calls)
        self.assertEqual(report['bootstrap_diagnostics'][0]['domain'], 'gui/501')

    def test_system_domain_is_rejected_before_any_native_query(self):
        with patch.object(probe, 'sys', types.SimpleNamespace(platform='darwin')), \
                patch.object(probe, 'os', types.SimpleNamespace(geteuid=lambda: 501)), \
                patch.object(probe, 'CoalitionAPI', side_effect=AssertionError('system domain reached native query')) as api:
            with self.assertRaises(probe.Unsupported):
                probe.probe({}, domain='system')
            api.assert_not_called()

    def test_rejected_guardian_baseline_retains_its_observed_snapshot(self):
        _, report = self.exercise(0, [{'coalition_id': 100},
                                     {'coalition_id': 200, 'active': 2}])
        self.assertIn('jobs', report)
        self.assertEqual(report['jobs'][0]['active'], 2)
        self.assertFalse(report['api_and_job_isolation_passed'])


class ReadinessSafety(unittest.TestCase):
    snapshot = {'nonce': 'expected', 'coalition_id': 200,
                'started': 3, 'exited': 2, 'active': 1}

    def exercise(self, raw, held=True, controller=False):
        flock = Mock(side_effect=BlockingIOError() if held else None)
        fake_fcntl = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=flock)
        with TEMP_FACTORY(dir=ROOT / '.artifacts') as temp, \
                patch.dict('sys.modules', {'fcntl': fake_fcntl}):
            directory = Path(temp)
            (directory / 'ready.json').write_text(raw, encoding='utf-8')
            (directory / 'alive.lock').touch()
            if controller:
                output = directory / 'report.json'
                with patch.object(probe.sys, 'argv', ['probe', '--output', str(output)]), \
                        patch.object(probe, 'probe', side_effect=lambda report, domain: probe.ready(directory, 'expected')), \
                        redirect_stdout(io.StringIO()):
                    code = probe.main()
                return code, json.loads(output.read_text()), flock
            return probe.ready(directory, 'expected'), flock

    def test_malformed_records_fail_with_bounded_fixture_reason(self):
        invalid = ['{private-diagnostic', '[]', 'null',
                   json.dumps({'nonce': 'expected'}),
                   json.dumps({**self.snapshot, 'coalition_id': True}),
                   json.dumps({**self.snapshot, 'coalition_id': -4}),
                   json.dumps({**self.snapshot, 'started': 1 << 64}),
                   json.dumps({**self.snapshot, 'exited': -1}),
                   json.dumps({**self.snapshot, 'active': 2})]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaisesRegex(RuntimeError, 'guardian readiness invalid'):
                self.exercise(raw)

    def test_mismatched_nonce_cannot_use_a_held_lease(self):
        with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
            self.exercise(json.dumps({**self.snapshot, 'nonce': 'another-launch'}))

    def test_api_denial_is_unavailable_and_does_not_echo_payload(self):
        with self.assertRaises(probe.Unsupported) as caught:
            self.exercise(json.dumps({'nonce': 'expected', 'unavailable': '/private/diagnostic'}))
        self.assertEqual(str(caught.exception), 'guardian API unavailable')

    def test_unheld_alive_lease_rejects_stale_valid_snapshot(self):
        with self.assertRaisesRegex(RuntimeError, 'without held alive lease'):
            self.exercise(json.dumps(self.snapshot), held=False)

    def test_held_alive_lease_accepts_valid_snapshot(self):
        result, flock = self.exercise(json.dumps(self.snapshot))
        self.assertEqual(result, self.snapshot)
        flock.assert_called_once()

    def test_malformed_ready_still_writes_failed_controller_report(self):
        code, report, flock = self.exercise('{private-diagnostic', controller=True)
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['api_and_job_isolation_passed'])
        self.assertFalse(report['family_recovery_acceptance'])
        self.assertEqual(report['reason'], 'guardian readiness invalid')
        self.assertNotIn('private-diagnostic', json.dumps(report))
        flock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
