"""W21-BE-3 — IGDB easy-title miss recovery (mocked candidates, no live IGDB)."""

from oneirodex.utils.gamenames import generate_goty_variants
from oneirodex.utils.game_name_parse import parse_game_label
from oneirodex.utils.match_scoring import (
    DEFAULT_HIGH_THRESHOLD,
    score_candidate,
    select_best_match,
)
import pytest

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- IGDB title-match pipeline.


def _assert_threshold_untouched():
    assert DEFAULT_HIGH_THRESHOLD >= 0.92


def test_threshold_default_not_lowered():
    _assert_threshold_untouched()


def test_1000x_resist_compact_variant_and_exact_select():
    """Spaced folder label must search compact IGDB form and select exact hit."""
    cleaned = parse_game_label('1000x Resist')['cleaned_name']
    assert cleaned == '1000x Resist'
    variants = generate_goty_variants(cleaned)
    assert '1000x Resist' in variants
    assert any(v.replace(' ', '').casefold() == '1000xresist' for v in variants)

    # Before-style: spaced + glued spelling variants must not fake ambiguity.
    candidates = [
        {'id': 1, 'name': '1000xRESIST'},
        {'id': 2, 'name': '1000x Resist'},
        {'id': 3, 'name': '1000xRESIST Demo'},
    ]
    best, confidence = select_best_match(cleaned, candidates)
    assert confidence == 'high'
    assert best['name'] in ('1000xRESIST', '1000x Resist')
    assert score_candidate(cleaned, '1000xRESIST') >= 0.99


def test_broken_sword_2_remaster_primary_head():
    """Remaster subtitle packaging must score as exact when primary head matches."""
    cleaned = 'Broken Sword 2'
    remaster = 'Broken Sword 2 - the Smoking Mirror: Remastered'
    # Pre-fix SequenceMatcher-only shape sat ~0.48 — must now clear 0.92.
    assert score_candidate(cleaned, remaster) >= 0.99

    candidates = [
        {'id': 10, 'name': remaster},
        {'id': 11, 'name': 'Broken Sword'},  # BS1 — sequel asymmetry must demote
        {'id': 12, 'name': 'Broken Sword II: The Smoking Mirror'},
    ]
    best, confidence = select_best_match(cleaned, candidates)
    assert confidence == 'high'
    # Roman numerals now score like digits (1.3.2), so the original ties the
    # remaster; a folder that does not say "Remastered" means the original.
    assert best['name'] == 'Broken Sword II: The Smoking Mirror'
    # Without the original among the candidates, the remaster still matches.
    best, confidence = select_best_match(cleaned, candidates[:2])
    assert confidence == 'high'
    assert best['name'] == remaster
    # A folder that names the remaster gets the remaster.
    best, confidence = select_best_match('Broken Sword 2 Remastered', candidates)
    assert best is None or best['name'] == remaster
    assert score_candidate(cleaned, 'Broken Sword') <= 0.85


def test_broken_sword_2_roman_variant_colon_subtitle():
    """Roman sequel search variant + colon subtitle still high-confidence."""
    variants = generate_goty_variants('Broken Sword 2')
    assert 'Broken Sword II' in variants
    best, confidence = select_best_match(
        'Broken Sword II',
        [
            {'id': 1, 'name': 'Broken Sword II: The Smoking Mirror'},
            {'id': 2, 'name': 'Broken Sword'},
        ],
    )
    assert confidence == 'high'
    assert best['id'] == 1


def test_resident_evil_exact_beats_sequel_siblings():
    """Franchise first entry must not stay ambiguous against RE2/3/4 (~0.96)."""
    cleaned = parse_game_label('resident evil')['cleaned_name']
    assert cleaned == 'Resident Evil'
    candidates = [
        {'id': 1, 'name': 'Resident Evil'},
        {'id': 2, 'name': 'Resident Evil 2'},
        {'id': 3, 'name': 'Resident Evil 3'},
        {'id': 4, 'name': 'Resident Evil 4'},
        {'id': 5, 'name': 'Resident Evil Remake'},
    ]
    # Before: RE2 scored ~0.96 → gap 0.04 < 0.08 → low.
    assert score_candidate(cleaned, 'Resident Evil 2') <= 0.85
    best, confidence = select_best_match(cleaned, candidates)
    assert confidence == 'high'
    assert best['name'] == 'Resident Evil'


def test_chasm_exact_over_colon_subtitle_game():
    """Single-token exact title stays high; `Chasm: The Rift` must not get remaster boost."""
    cleaned = parse_game_label('chasm')['cleaned_name']
    assert cleaned == 'Chasm'
    assert score_candidate(cleaned, 'Chasm: The Rift') < 0.92
    best, confidence = select_best_match(
        cleaned,
        [
            {'id': 1, 'name': 'Chasm'},
            {'id': 2, 'name': 'Chasm: The Rift'},
            {'id': 3, 'name': 'Chasm VR'},
        ],
    )
    assert confidence == 'high'
    assert best['name'] == 'Chasm'


def test_alan_wake_remastered_folder_still_prefers_remaster_sku():
    """Folder that includes Remastered must still pick the remaster SKU, not base."""
    best, confidence = select_best_match(
        'Alan Wake Remastered',
        [
            {'id': 1, 'name': 'Alan Wake Remastered'},
            {'id': 2, 'name': 'Alan Wake'},
            {'id': 3, 'name': 'Alan Wake II'},
        ],
    )
    assert confidence == 'high'
    assert best['name'] == 'Alan Wake Remastered'


def test_does_not_auto_pick_when_only_unrelated_remaster_prefix_missing():
    """No high-confidence invent when folder has no real IGDB peer above threshold."""
    best, confidence = select_best_match(
        'Totally Unknown Game XYZ',
        [
            {'id': 1, 'name': 'Cyberpunk 2077'},
            {'id': 2, 'name': 'Hades'},
        ],
    )
    assert confidence == 'low'
    assert best is None
