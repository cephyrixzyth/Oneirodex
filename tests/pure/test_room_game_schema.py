"""Pure validation checks: runnable with unittest without a server or database."""
import copy
import json
from pathlib import Path
import unittest

from pydantic import ValidationError
from oneirodex.schemas.room_games import MoonfallSave, RoomGameSaveBody, RoomGameDeleteBody, MISSION_LENGTHS


def fixture():
    return json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'moonfall-save-v1.json').read_text())


class MoonfallSchemaTests(unittest.TestCase):
    def test_feature_counters_and_side_have_strict_bounds(self):
        for key, bad in [('rampSide', True), ('rampSide', 0), ('rampTicks', 181),
                         ('skillTicks', 361), ('launchAim', float('nan')), ('launchAim', -4),
                         ('ramps', 1_000_001), ('unexpected', 0)]:
            with self.subTest(key=key):
                value = fixture()
                value['features'][key] = bad
                with self.assertRaises(ValidationError):
                    MoonfallSave.model_validate(value)

    def test_shared_active_run_round_trip(self):
        value = fixture()
        self.assertEqual(MoonfallSave.model_validate(value).model_dump(), value)
        self.assertEqual(RoomGameSaveBody.model_validate({'revision': 0, 'state': value}).revision, 0)

    def test_completed_and_exhausted_run(self):
        value = fixture()
        value.update(phase='complete', missionHits=list(MISSION_LENGTHS))
        value['features'].update(ramps=6, returns=8, skillShots=2)
        self.assertEqual(MoonfallSave.model_validate(value).phase, 'complete')
        value.update(phase='game-over', ballsRemaining=0, balls=[])
        self.assertEqual(MoonfallSave.model_validate(value).ballsRemaining, 0)

    def test_invalid_versions_types_bounds_and_unknown_fields(self):
        for key, bad in [('version', 2), ('version', True), ('score', float('nan')),
                         ('score', float('inf')), ('score', True), ('tick', -1),
                         ('seed', 2**32), ('ballsRemaining', -1), ('recoveries', 3),
                         ('missionHits', [0, 0, 99]), ('missionHits', [0, 1, 0]),
                         ('unexpected', 'secret-like-invalid-input')]:
            with self.subTest(key=key, value_type=type(bad).__name__):
                value = fixture()
                value[key] = bad
                with self.assertRaises(ValidationError):
                    MoonfallSave.model_validate(value)

    def test_invalid_ball_shape_and_non_finite_motion(self):
        for key, bad in [('x', float('nan')), ('vy', float('inf')), ('vx', 51),
                         ('id', 0), ('id', 2), ('cooldown', 601), ('captureTicks', 121),
                         ('x', True), ('unexpected', 'value')]:
            with self.subTest(key=key):
                value = fixture()
                value['balls'][0][key] = bad
                with self.assertRaises(ValidationError):
                    MoonfallSave.model_validate(value)

    def test_duplicate_too_many_and_semantically_inconsistent_balls(self):
        for changes in ({'balls': []}, {'balls': [fixture()['balls'][0]] * 2},
                        {'balls': [fixture()['balls'][0]] * 4}, {'phase': 'ready'},
                        {'phase': 'complete'}, {'best': 0}, {'ballsRemaining': 0}):
            value = fixture()
            value.update(copy.deepcopy(changes))
            with self.subTest(fields=tuple(changes)):
                with self.assertRaises(ValidationError):
                    MoonfallSave.model_validate(value)

    def test_revision_envelope_is_strict_and_has_no_client_owner(self):
        for changes in ({'revision': -1}, {'revision': True}, {'user_id': 7},
                        {'game_id': 'other-game'}, {'revision': '1'}):
            value = {'revision': 0, 'state': fixture(), **changes}
            with self.subTest(fields=tuple(changes)):
                with self.assertRaises(ValidationError):
                    RoomGameSaveBody.model_validate(value)
        self.assertEqual(RoomGameDeleteBody.model_validate({'revision': 4}).revision, 4)
        with self.assertRaises(ValidationError):
            RoomGameDeleteBody.model_validate({'revision': True})

    def test_game_settings_are_bounded_and_strict(self):
        for key, value in [('volume', float('nan')), ('volume', 1.1), ('volume', True),
                           ('quality', 'ultra'), ('muted', 'yes'), ('unexpected', 'value')]:
            state = fixture()
            state['settings'][key] = value
            with self.subTest(key=key):
                with self.assertRaises(ValidationError):
                    MoonfallSave.model_validate(state)


if __name__ == '__main__':
    unittest.main()


class RoomGameRevisionBoundTests(unittest.TestCase):
    def test_revision_at_the_ceiling_is_invalid_not_a_conflict(self):
        # The store writes revision + 1 and caps at 2,000,000,000, so the body
        # rejects the ceiling itself (422) instead of the store answering 409.
        self.assertEqual(RoomGameDeleteBody.model_validate({'revision': 1_999_999_999}).revision, 1_999_999_999)
        for body in (RoomGameDeleteBody, RoomGameSaveBody):
            with self.subTest(body=body.__name__):
                with self.assertRaises(ValidationError):
                    body.model_validate({'revision': 2_000_000_000, 'state': fixture()})
