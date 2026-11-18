"""
Unit tests for the propose-only scan setting.

These tests avoid touching Postgres: `is_propose_only_scan` is a pure helper,
and the admin settings dictionaries (`DEFAULT_SETTINGS` / `FIELD_MAPPINGS`)
are plain module-level dicts. Where a GlobalSettings-like object is needed,
a lightweight stand-in is used instead of a real ORM-backed instance.
"""

from types import SimpleNamespace

from oneirodex.utils.game_core import is_propose_only_scan
from oneirodex.utils.match_proposal import build_match_proposal
from oneirodex.utils.server_settings import FIELD_MAPPINGS, SERVER_DEFAULTS as DEFAULT_SETTINGS
import pytest

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- propose-only library scan pass.


class TestIsProposeOnlyScan:
    """Test the settings-parsing helper used by retrieve_and_save_game."""

    def test_none_settings_is_false(self):
        assert is_propose_only_scan(None) is False

    def test_empty_dict_is_false(self):
        assert is_propose_only_scan({}) is False

    def test_dict_with_flag_true(self):
        assert is_propose_only_scan({'propose_only_scan': True}) is True

    def test_dict_with_flag_false(self):
        assert is_propose_only_scan({'propose_only_scan': False}) is False

    def test_dict_missing_flag_defaults_false(self):
        assert is_propose_only_scan({'use_local_metadata': True}) is False

    def test_object_with_flag_true(self):
        settings_obj = SimpleNamespace(propose_only_scan=True)
        assert is_propose_only_scan(settings_obj) is True

    def test_object_with_flag_false(self):
        settings_obj = SimpleNamespace(propose_only_scan=False)
        assert is_propose_only_scan(settings_obj) is False

    def test_object_missing_attribute_defaults_false(self):
        settings_obj = SimpleNamespace(use_local_metadata=True)
        assert is_propose_only_scan(settings_obj) is False


class TestProposeOnlyProposalPayload:
    """Verify the high-confidence proposal payload written when propose-only is enabled."""

    def test_high_confidence_proposal_marks_confidence_high(self):
        candidates = [{'id': 42, 'name': 'Definitely The Game'}]
        payload = build_match_proposal('Definitely The Game', candidates, confidence='high')
        proposal = payload['proposal']
        assert proposal['confidence'] == 'high'
        assert proposal['candidates'][0]['igdb_id'] == 42


class TestAdminSettingsMapping:
    """Verify propose_only_scan is wired into the admin settings dictionaries."""

    def test_default_settings_includes_propose_only_scan(self):
        assert 'proposeOnlyScan' in DEFAULT_SETTINGS
        assert DEFAULT_SETTINGS['proposeOnlyScan'] is False

    def test_field_mappings_includes_propose_only_scan(self):
        assert FIELD_MAPPINGS.get('proposeOnlyScan') == 'propose_only_scan'
