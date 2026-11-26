"""Tests for item_kind taxonomy and software identify search path."""

from unittest.mock import patch

from oneirodex.utils.item_kind import (
    infer_item_kind_from_steam_type,
    is_denied_auto_game_match,
    normalize_item_kind,
    steam_type_is_software,
    suggest_item_kind,
)
from oneirodex.utils.game_name_parse import parse_game_label, strip_vr_noise_tail
from oneirodex.utils.match_proposal import build_match_proposal
from oneirodex.utils.software_identify import (
    build_software_search_queries,
    collect_software_identify_candidates,
    enrich_proposal_with_software,
)


def test_normalize_item_kind_aliases():
    assert normalize_item_kind('Emulator') == 'emulator'
    assert normalize_item_kind('utility') == 'tool'
    assert normalize_item_kind('software') == 'tool'
    assert normalize_item_kind('soft title') == 'experience'
    assert normalize_item_kind(None) == 'game'
    assert normalize_item_kind('nope') == 'game'


def test_item_kind_plain_language_labels():
    from oneirodex.utils.item_kind import ITEM_KIND_LABELS
    from oneirodex.utils.match_proposal import SUGGESTED_KIND_LABELS

    assert ITEM_KIND_LABELS['experience'] == 'Soft title'
    assert ITEM_KIND_LABELS['tool'] == 'Utility'
    assert SUGGESTED_KIND_LABELS['experience'] == 'Soft title'
    assert SUGGESTED_KIND_LABELS['tool'] == 'Utility'
    # API tokens unchanged
    assert normalize_item_kind('experience') == 'experience'
    assert normalize_item_kind('tool') == 'tool'


def test_steam_type_software_maps_to_tool_or_emulator():
    assert steam_type_is_software('software')
    assert steam_type_is_software('application')
    assert not steam_type_is_software('game')
    assert infer_item_kind_from_steam_type('software', name='OpenVR Metrics') == 'tool'
    assert infer_item_kind_from_steam_type('software', name='3DSen VR') == 'emulator'
    assert infer_item_kind_from_steam_type('game', name='Hades') == 'game'


def test_deny_auto_game_for_converter_metrics():
    assert is_denied_auto_game_match('OpenVR Metrics')
    assert is_denied_auto_game_match('Foo Converter')
    assert not is_denied_auto_game_match('3DSen VR')
    assert suggest_item_kind('Save Editor Pro') == 'tool'


def test_glued_vr_peel_3dsenvr():
    """3DSenVR-class labels must yield a searchable clean name (not permanent peel miss)."""
    assert strip_vr_noise_tail('3DSenVR') == '3DSen'
    parsed = parse_game_label('3DSenVR')
    assert parsed['cleaned_name'] == '3DSen'
    assert parsed['had_vr_suffix'] is True
    # Spaced form still peels
    assert parse_game_label('3DSen VR')['cleaned_name'] == '3DSen'
    # Mid-token VR must not peel (7VR Wonders)
    assert parse_game_label('7VR Wonders')['cleaned_name'] == '7VR Wonders'
    assert parse_game_label('7VR Wonders')['had_vr_suffix'] is False


def test_software_search_queries_include_vr_reattach():
    # 3DSenVR is the VR edition of 3DSen: the VR forms are the queries, the
    # flat title is not (2026-11-26 scan review).
    queries = build_software_search_queries('3DSenVR')
    assert queries[0] == '3DSenVR'
    assert '3DSen VR' in queries
    assert '3DSen' not in queries


def test_collect_software_candidates_synthetic_non_game(monkeypatch):
    """Synthetic Steam software fixture — no network."""
    synthetic = [
        {
            'source': 'steam',
            'id': 1044340,
            'name': '3DSen VR',
            'url': 'https://store.steampowered.com/app/1044340/',
            'cover_url': None,
            'summary': None,
            'steam_app_id': 1044340,
            'steam_type': 'software',
            'item_kind': 'emulator',
            'is_software': True,
        },
        {
            'source': 'steam',
            'id': 999,
            'name': 'Unrelated Game',
            'url': None,
            'cover_url': None,
            'summary': None,
            'steam_app_id': 999,
            'steam_type': 'game',
            'item_kind': 'game',
            'is_software': False,
        },
    ]

    with patch(
        'oneirodex.utils.software_identify.search_steam_games',
        return_value=synthetic,
    ) as mock_search:
        hits = collect_software_identify_candidates('3DSenVR', limit=10)
        assert mock_search.called
        assert hits
        top = hits[0]
        assert top['name'] == '3DSen VR'
        assert top['is_software'] is True
        assert top['item_kind'] == 'emulator'
        assert top['match_score'] >= 0.7


def test_enrich_proposal_adds_software_path():
    with patch(
        'oneirodex.utils.software_identify.collect_software_identify_candidates',
        return_value=[{
            'source': 'steam',
            'steam_app_id': 1,
            'name': '3DSen VR',
            'steam_type': 'software',
            'item_kind': 'emulator',
            'match_score': 0.95,
            'url': None,
            'cover_url': None,
            'is_software': True,
            'deny_auto_game': False,
        }],
    ):
        proposal = build_match_proposal('3DSenVR', [])
        enriched = enrich_proposal_with_software(proposal, '3DSenVR')
        body = enriched['proposal']
        assert body['suggested_kind'] == 'emulator'
        assert body['identify_path'] == 'software'
        assert body['software_candidates'][0]['name'] == '3DSen VR'
        assert body.get('had_vr_suffix') is True


def test_search_steam_games_tags_software_type():
    from oneirodex.utils.secondary_scrapers import search_steam_games

    class _Resp:
        def json(self):
            return {
                'items': [
                    {
                        'id': 42,
                        'name': 'Demo Tool',
                        'type': 'software',
                        'tiny_image': None,
                    }
                ]
            }

    with patch(
        'oneirodex.utils.secondary_scrapers.request_with_backoff',
        return_value=_Resp(),
    ):
        results = search_steam_games('Demo Tool', limit=5, include_software=True)
        assert len(results) == 1
        assert results[0]['steam_type'] == 'software'
        assert results[0]['is_software'] is True
        assert results[0]['item_kind'] in ('tool', 'emulator', 'experience')

        filtered = search_steam_games('Demo Tool', limit=5, include_software=False)
        assert filtered == []
