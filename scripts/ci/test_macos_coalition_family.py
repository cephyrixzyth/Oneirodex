"""Protocol and failure controls; native family acceptance is a separate run."""
import importlib.util
from contextlib import contextmanager
import ctypes
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    'family_probe', Path(__file__).with_name('probe-macos-coalition-family.py'))
family = importlib.util.module_from_spec(spec)
spec.loader.exec_module(family)
ROOT = Path(__file__).resolve().parents[2]
NONCE = 'a' * 32
CASE = 'b' * 32


class FamilyControls(unittest.TestCase):
    def test_only_bound_predefined_requests_are_accepted(self):
        for mode in ('normal', 'detached'):
            request = {'nonce': NONCE, 'case': CASE, 'mode': mode}
            self.assertEqual(family.validate_request(request, NONCE), request)
        bad = [None, [], {}, {'nonce': NONCE, 'case': CASE, 'mode': 'shell'},
               {'nonce': NONCE, 'case': '../escape', 'mode': 'normal'},
               {'nonce': 'c' * 32, 'case': CASE, 'mode': 'normal'},
               {'nonce': NONCE, 'case': CASE, 'mode': 'normal', 'command': 'anything'}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                family.validate_request(value, NONCE)

    def with_record(self, value, callback):
        with tempfile.TemporaryDirectory(dir=ROOT / '.artifacts') as temp:
            path = Path(temp) / 'state.json'
            path.write_text(json.dumps(value), encoding='utf-8')
            return callback(path)

    def snapshot(self, **changes):
        return {'nonce': NONCE, 'case': CASE, 'coalition_id': 200,
                'started': 4, 'exited': 2, 'active': 2,
                'heartbeat': 1, 'pid': 123, 'pgid': 123, 'sid': 123, **changes}

    def test_snapshot_identity_and_counter_validation(self):
        value = self.snapshot()
        self.assertEqual(self.with_record(value, lambda p: family.read_snapshot(p, NONCE, CASE)), value)
        for changes in ({'nonce': 'c'*32}, {'case': 'c'*32}, {'coalition_id': True},
                        {'exited': -1}, {'active': 9}, {'heartbeat': False}, {'pid': 0}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.with_record(self.snapshot(**changes), lambda p: family.read_snapshot(p, NONCE, CASE))

    def test_unknown_api_snapshot_is_unavailable_without_payload_echo(self):
        with self.assertRaises(family.base.Unsupported) as error:
            self.with_record({'nonce': NONCE, 'unavailable': '/private/diagnostic'},
                             lambda p: family.read_snapshot(p, NONCE))
        self.assertEqual(str(error.exception), 'family inspection unavailable')

    def test_nonobject_snapshot_is_invalid_rather_than_missing(self):
        for value in (None, [], False):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.with_record(value, lambda p: family.read_snapshot(p, NONCE))

    def test_dead_keeper_cannot_make_stale_snapshot_an_end_result(self):
        with patch.object(family, 'held', return_value=False):
            with self.assertRaises(family.base.Unsupported):
                family.keeper_snapshot(Path('unused'), NONCE)

    def test_keeper_loss_during_inspection_is_unavailable(self):
        with patch.object(family, 'held', side_effect=[True, False]), \
                patch.object(family, 'read_snapshot', return_value=self.snapshot()):
            with self.assertRaises(family.base.Unsupported):
                family.keeper_snapshot(Path('unused'), NONCE)

    def test_exit_request_requires_a_previously_live_leaf(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.artifacts') as temp, \
                patch.object(family, 'held', return_value=False), \
                patch.object(family, 'count_is', return_value=True):
            directory = Path(temp)
            with self.assertRaisesRegex(RuntimeError, 'not alive before requested exit'):
                family.end_case({}, CASE, directory)
            self.assertFalse((directory / 'stop').exists())

    def test_injected_failure_recovery_waits_for_a_fresh_available_snapshot(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.artifacts') as temp, \
                patch.object(family, 'held', return_value=True), \
                patch.object(family, 'keeper_snapshot', side_effect=[self.snapshot(),
                    family.base.Unsupported('family inspection unavailable'),
                    family.base.Unsupported('family inspection unavailable'), self.snapshot()]) as inspect:
            directory = Path(temp)
            (directory / 'cases').mkdir()
            (directory / 'request-result.json').write_text(json.dumps({'nonce': NONCE, 'status': 'rejected'}))
            job = {'directory': directory, 'nonce': NONCE, 'initial': {'coalition_id': 200}}
            family.negative_controls(job, 2)
            self.assertEqual(inspect.call_count, 4)

    def test_injected_failure_recovery_cannot_hide_a_dead_keeper(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.artifacts') as temp, \
                patch.object(family, 'held', return_value=False), \
                patch.object(family, 'keeper_snapshot', side_effect=[self.snapshot(),
                    family.base.Unsupported('family inspection unavailable'),
                    family.base.Unsupported('family inspection unavailable')]) as inspect:
            directory = Path(temp)
            (directory / 'cases').mkdir()
            (directory / 'request-result.json').write_text(json.dumps({'nonce': NONCE, 'status': 'rejected'}))
            job = {'directory': directory, 'nonce': NONCE, 'initial': {'coalition_id': 200}}
            with self.assertRaises(family.base.Unsupported):
                family.negative_controls(job, 2)
            self.assertEqual(inspect.call_count, 3)

    def test_survival_requires_later_same_launch_heartbeat_and_held_leaf(self):
        before = self.snapshot()
        after = self.snapshot(heartbeat=2)
        family.verify_survival(before, after, keeper_held=False, leaf_held=True)
        for changes, keeper, leaf in [({}, True, True), ({}, False, False),
                                     ({'heartbeat': 1}, False, True),
                                     ({'case': 'c'*32}, False, True),
                                     ({'coalition_id': 201}, False, True),
                                     ({'pid': 999}, False, True)]:
            with self.subTest(changes=changes, keeper=keeper, leaf=leaf), self.assertRaises(RuntimeError):
                family.verify_survival(before, {**after, **changes}, keeper, leaf)

    def test_root_and_nonmac_refuse_before_native_queries(self):
        for platform, uid in [('win32', 501), ('darwin', 0)]:
            with self.subTest(platform=platform, uid=uid), \
                    patch.object(family.sys, 'platform', platform), \
                    patch.object(family.os, 'geteuid', return_value=uid, create=True), \
                    patch.object(family.base, 'CoalitionAPI') as api:
                with self.assertRaises(family.base.Unsupported):
                    family.probe({})
                api.assert_not_called()

    def test_cleanup_unloads_only_registered_exact_labels_after_partial_admission(self):
        calls = []
        def command(*args):
            calls.append(args)
            return types.SimpleNamespace(returncode=113, stderr='Could not find service fixture')
        with tempfile.TemporaryDirectory(dir=ROOT / '.artifacts') as temp, \
                patch.object(family.base, 'launchctl', side_effect=command), \
                patch.object(family, 'held', return_value=False):
            job = {'target': 'gui/501/com.oneirodex.fixture.' + NONCE,
                   'directory': Path(temp), 'nonce': NONCE}
            errors = []
            family.cleanup_jobs([job], errors)
            self.assertEqual(errors, [])
            self.assertEqual(calls, [('bootout', job['target']), ('print', job['target'])])

    def test_still_loaded_job_makes_cleanup_fail(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.artifacts') as temp, \
                patch.object(family.base, 'launchctl', return_value=types.SimpleNamespace(returncode=0)), \
                patch.object(family, 'held', return_value=False):
            errors = []
            family.cleanup_jobs([{'target': 'owned-exact-label', 'directory': Path(temp), 'nonce': NONCE}], errors)
            self.assertTrue(errors)

    @contextmanager
    def observer_files(self, coalition=None, leaf=None):
        with tempfile.TemporaryDirectory(dir=ROOT / '.artifacts') as temp:
            directory = Path(temp)
            (directory / 'job.json').write_text(json.dumps({'nonce': NONCE}))
            (directory / 'coalition.json').write_text(json.dumps(coalition or self.snapshot()))
            case = directory / 'cases' / CASE
            case.mkdir(parents=True)
            (case / 'leaf.json').write_text(json.dumps(leaf or self.snapshot()))
            (case / 'leaf.lock').touch()
            yield directory

    def observer_api(self, counts=(7, 5), result=0, caller=99, error=None):
        def query(cid, buffer, size):
            if error:
                raise error
            if counts is not None:
                target = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint64 * 2)).contents
                target[0], target[1] = counts
            return result
        return types.SimpleNamespace(own_snapshot=lambda: {'coalition_id': caller}, usage=Mock(side_effect=query))

    def test_outside_observer_queries_only_registered_owned_coalition(self):
        api = self.observer_api()
        with self.observer_files() as directory, patch.object(family, 'held', return_value=True), \
                patch.object(family.base, 'CoalitionAPI', return_value=api):
            data = family.observe_owned(directory, NONCE, CASE)
        self.assertEqual((data['coalition_id'], data['active'], data['observer_coalition_id']), (200, 2, 99))
        self.assertEqual(api.usage.call_args.args[0], 200)
        self.assertEqual(api.usage.call_args.args[2], 16)

    def test_retired_group_keeps_valid_zero_and_one_counts_distinct_from_unknown(self):
        for active in (0, 1):
            with self.subTest(active=active), self.observer_files() as directory, \
                    patch.object(family, 'held', return_value=False), \
                    patch.object(family.base, 'CoalitionAPI', return_value=self.observer_api(counts=(7, 7-active))):
                data = family.observe_owned(directory, NONCE, CASE, expect_live=False)
                self.assertEqual(data['active'], active)

    def test_retired_expectation_rejects_held_or_missing_leaf_lease(self):
        for present, locked in [(True, True), (False, False)]:
            with self.subTest(present=present), self.observer_files() as directory, \
                    patch.object(family, 'held', return_value=locked), \
                    patch.object(family.base, 'CoalitionAPI') as api:
                if not present:
                    (directory / 'cases' / CASE / 'leaf.lock').unlink()
                with self.assertRaises(family.base.Unsupported):
                    family.observe_owned(directory, NONCE, CASE, expect_live=False)
                api.assert_not_called()

    def test_observer_rejects_unbound_metadata_before_any_query(self):
        for coalition, leaf, case in [(self.snapshot(nonce='c'*32), self.snapshot(), CASE),
                                     (self.snapshot(), self.snapshot(coalition_id=201), CASE),
                                     (self.snapshot(), self.snapshot(), '../outside')]:
            with self.subTest(case=case, coalition=coalition), \
                    self.observer_files(coalition, leaf) as directory, \
                    patch.object(family, 'held', return_value=True), \
                    patch.object(family.base, 'CoalitionAPI') as api:
                with self.assertRaises(RuntimeError):
                    family.observe_owned(directory, NONCE, case)
                api.assert_not_called()

    def test_foreign_query_errors_and_incomplete_counters_remain_unavailable(self):
        variants = [self.observer_api(counts=None), self.observer_api(result=1),
                    self.observer_api(counts=(3, 4)), self.observer_api(error=OSError('/private/diagnostic'))]
        for api in variants:
            with self.subTest(api=api), self.observer_files() as directory, \
                    patch.object(family, 'held', return_value=True), \
                    patch.object(family.base, 'CoalitionAPI', return_value=api):
                with self.assertRaises(family.base.Unsupported) as error:
                    family.observe_owned(directory, NONCE, CASE)
                self.assertNotIn('/private', str(error.exception))

    def test_observer_cannot_adopt_joined_coalition_or_a_lost_leaf(self):
        for caller, leases in [(200, [True]), (99, [True, False])]:
            with self.subTest(caller=caller), self.observer_files() as directory, \
                    patch.object(family, 'held', side_effect=leases), \
                    patch.object(family.base, 'CoalitionAPI', return_value=self.observer_api(caller=caller)):
                with self.assertRaises((RuntimeError, family.base.Unsupported)):
                    family.observe_owned(directory, NONCE, CASE)

    def test_fresh_observer_result_must_match_current_request_and_live_count(self):
        observation = 'd'*32
        value = {**self.snapshot(), 'observer_coalition_id': 99, 'observation': observation}
        family.verify_observation(value, NONCE, CASE, 200, 2, observation)
        for changes in ({'nonce': 'c'*32}, {'case': 'c'*32}, {'coalition_id': 201},
                        {'observer_coalition_id': 200}, {'observer_coalition_id': True},
                        {'observation': 'c'*32}, {'active': 1}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                family.verify_observation({**value, **changes}, NONCE, CASE, 200, 2, observation)


if __name__ == '__main__':
    unittest.main()
