"""Tests for match proposal payload builder (no DB)."""

import json
import os
import tempfile

from oneirodex.utils.match_proposal import build_match_proposal, write_match_proposal


def test_build_match_proposal_from_scene_repack_label():
    candidates = [
        {'id': 10, 'name': "Assassin's Creed Shadows"},
        {'id': 11, 'name': "Assassin's Creed Odyssey"},
    ]
    # A1 peels generic "[… Repack]" bracket tags (prefix + Repack).
    payload = build_match_proposal("Assassin's Creed Shadows [Scene Repack]", candidates)
    prop = payload['proposal']
    assert prop['cleaned_name'] == "Assassin's Creed Shadows"
    assert prop['confidence'] == 'low'
    assert prop['candidates'][0]['igdb_id'] == 10
    assert prop['candidates'][0]['score'] >= prop['candidates'][1]['score']
    assert isinstance(prop.get('transforms'), list)
    assert any(t.get('stage') == 'A1' for t in prop['transforms'])


def test_build_includes_steam_app_id():
    payload = build_match_proposal('barony (Steam 335240)', [{'id': 1, 'name': 'Barony'}])
    assert payload['proposal']['steam_app_id'] == 335240


def test_bare_catalogue_number_is_not_a_steam_app_id():
    payload = build_match_proposal('barony (89881)', [{'id': 1, 'name': 'Barony'}])
    assert payload['proposal']['steam_app_id'] is None


def test_write_match_proposal_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        payload = build_match_proposal('Test Game', [{'id': 5, 'name': 'Test Game'}])
        assert write_match_proposal(tmp, payload) is True
        path = os.path.join(tmp, 'oneirodex.proposal.json')
        with open(path, encoding='utf-8') as handle:
            loaded = json.load(handle)
        assert loaded['proposal']['cleaned_name'] == 'Test Game'


def test_build_match_proposal_default_confidence_is_low():
    payload = build_match_proposal('Test Game', [{'id': 5, 'name': 'Test Game'}])
    assert payload['proposal']['confidence'] == 'low'


def test_build_match_proposal_accepts_high_confidence_override():
    """propose-only scan mode writes a proposal for a high-confidence match instead of importing."""
    payload = build_match_proposal(
        'Test Game',
        [{'id': 5, 'name': 'Test Game'}],
        confidence='high',
    )
    assert payload['proposal']['confidence'] == 'high'
    assert payload['proposal']['candidates'][0]['igdb_id'] == 5
