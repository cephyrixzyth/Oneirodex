"""W20-2: ordered Stage A0–A14 name-transform trail on parse / proposal / dupe explain."""

from oneirodex.utils.duplicate_check import explain_duplicate_match
from oneirodex.utils.game_name_parse import parse_game_label
from oneirodex.utils.match_proposal import build_match_proposal


def _stages(transforms):
    return [t['stage'] for t in transforms]


def _assert_step(step, *, stage, before_contains=None, after_lacks=None):
    assert step['stage'] == stage
    assert 'before' in step and 'after' in step
    assert step['before'] != step['after']
    if before_contains:
        assert before_contains in step['before']
    if after_lacks:
        assert after_lacks not in step['after']


def test_parse_empty_has_empty_transforms():
    r = parse_game_label('')
    assert r['transforms'] == []
    assert r['cleaned_name'] == ''


def test_plain_title_may_only_title_case():
    r = parse_game_label('plain game')
    assert r['cleaned_name'] == 'Plain Game'
    assert _stages(r['transforms']) == ['A7']
    assert r['transforms'][0]['reason'] == 'title_case'


def test_a0_basename_transform_on_y_path():
    r = parse_game_label(r'Y:\_pc\_a\Abyssus [Repack]')
    assert r['cleaned_name'] == 'Abyssus'
    assert 'A0' in _stages(r['transforms'])
    assert 'A1' in _stages(r['transforms'])
    a0 = next(t for t in r['transforms'] if t['stage'] == 'A0')
    assert a0['after'] == 'Abyssus [Repack]'
    assert a0['reason'] == 'basename_trim'


def test_a1_repack_bracket_peel_step():
    r = parse_game_label("Assassin's Creed Shadows [Repack]")
    assert r['cleaned_name'] == "Assassin's Creed Shadows"
    a1 = next(t for t in r['transforms'] if t['stage'] == 'A1')
    _assert_step(a1, stage='A1', before_contains='[Repack]', after_lacks='Repack')


def test_a2_version_bracket_peel_step():
    r = parse_game_label('Some Game [1 0 4 1]')
    a2 = next(t for t in r['transforms'] if t['stage'] == 'A2')
    _assert_step(a2, stage='A2', before_contains='[1 0 4 1]', after_lacks='[1')


def test_a3_build_paren_peel_step():
    r = parse_game_label('ADR1FT (build 18 05 2023)')
    assert 'A3' in _stages(r['transforms'])
    a3 = next(t for t in r['transforms'] if t['stage'] == 'A3')
    _assert_step(a3, stage='A3', before_contains='build', after_lacks='build')


def test_a4_vr_tail_peel_step():
    r = parse_game_label('A Fishermans Tale VR')
    a4 = next(t for t in r['transforms'] if t['stage'] == 'A4')
    _assert_step(a4, stage='A4', before_contains='VR', after_lacks='VR')
    assert r['had_vr_suffix'] is True


def test_a5_catalog_number_peel_step():
    """A bare trailing (digits) is a catalogue number, never a Steam App ID."""
    r = parse_game_label('Abandon Ship (81735)')
    assert r['catalog_number'] == 81735
    assert r['steam_app_id'] is None
    a5 = next(t for t in r['transforms'] if t['stage'] == 'A5')
    _assert_step(a5, stage='A5', before_contains='81735', after_lacks='81735')
    assert a5['reason'] == 'catalog_number'


def test_a5_labelled_steam_app_id_peel_step():
    r = parse_game_label('Abandon Ship (Steam 1245620)')
    assert r['steam_app_id'] == 1245620
    assert r['catalog_number'] is None
    a5 = next(t for t in r['transforms'] if t['stage'] == 'A5')
    assert a5['reason'] == 'steam_app_id'


def test_a6_version_and_early_access_peel_steps():
    r = parse_game_label('Some Game v0 4 Early Access')
    assert r['cleaned_name'] == 'Some Game'
    assert 'A6' in _stages(r['transforms'])
    a6 = next(t for t in r['transforms'] if t['stage'] == 'A6')
    assert 'v0' in a6['before'].casefold() or 'Early' in a6['before']


def test_a14_vr_repass_after_version():
    """Title VR v… → A6 leaves Title VR → A14 peels VR."""
    r = parse_game_label('Some Game VR v0 8 1')
    assert r['cleaned_name'] == 'Some Game'
    stages = _stages(r['transforms'])
    assert 'A6' in stages
    assert 'A14' in stages
    # A4 should not fire first when VR is followed by version (no trailing bare VR yet).
    a14 = next(t for t in r['transforms'] if t['stage'] == 'A14')
    _assert_step(a14, stage='A14', before_contains='VR', after_lacks='VR')
    assert a14['reason'] == 'vr_repass'


def test_a9_incl_update_peel_step():
    r = parse_game_label('Pathologic 2 (Incl Update 7)')
    a9 = next(t for t in r['transforms'] if t['stage'] == 'A9')
    _assert_step(a9, stage='A9', before_contains='Incl', after_lacks='Incl')


def test_a10_unbracketed_scene_peel_step():
    r = parse_game_label('Some Game - SCENEGRP')
    a10 = next(t for t in r['transforms'] if t['stage'] == 'A10')
    _assert_step(a10, stage='A10', before_contains='SCENEGRP', after_lacks='SCENEGRP')


def test_a11_date_stamp_peel_step():
    r = parse_game_label('Alfred Hitchcock Vertigo 2022093001')
    a11 = next(t for t in r['transforms'] if t['stage'] == 'A11')
    _assert_step(a11, stage='A11', before_contains='2022093001', after_lacks='2022093001')


def test_a12_update_build_prose_peel_step():
    r = parse_game_label('Blades of Fire Update v2 0 0 5')
    assert 'A12' in _stages(r['transforms']) or 'A6' in _stages(r['transforms'])
    # After peels, title core remains.
    assert 'Blades' in r['cleaned_name']
    assert 'Update' not in r['cleaned_name']


def test_a13_addon_hv_junk_peel_step():
    r = parse_game_label('Some Game 4K Videos Add-ons')
    a13 = next(t for t in r['transforms'] if t['stage'] == 'A13')
    _assert_step(a13, stage='A13', before_contains='4K', after_lacks='4K')


def test_a8_franchise_apostrophe_inject_step():
    r = parse_game_label('Assassins Creed Rogue')
    assert r['cleaned_name'] == "Assassin's Creed Rogue"
    a8 = next(t for t in r['transforms'] if t['stage'] == 'A8')
    assert a8['reason'] == 'franchise_apostrophe_inject'
    assert "Assassin's" in a8['after']


def test_transforms_ordered_and_chained():
    """Multi-stage label: each after feeds the next before."""
    r = parse_game_label(r'Y:\_pc\Some Game VR v0 4 [Repack]')
    transforms = r['transforms']
    assert transforms, 'expected peel steps'
    for i in range(1, len(transforms)):
        # Later stages operate on the previous after (may skip unchanged stages).
        assert transforms[i]['before'] == transforms[i - 1]['after']
    assert r['cleaned_name'] == 'Some Game'
    stages = _stages(transforms)
    assert stages[0] == 'A0'
    assert 'A1' in stages
    assert 'A6' in stages
    assert 'A14' in stages


def test_build_match_proposal_includes_transforms():
    payload = build_match_proposal(
        "Assassin's Creed Shadows [Repack]",
        [{'id': 10, 'name': "Assassin's Creed Shadows"}],
    )
    prop = payload['proposal']
    assert prop['cleaned_name'] == "Assassin's Creed Shadows"
    assert isinstance(prop['transforms'], list)
    assert any(t['stage'] == 'A1' for t in prop['transforms'])


def test_explain_duplicate_keeps_short_reason_and_attaches_transforms():
    existing = type('G', (), {
        'uuid': 'u-1',
        'full_disk_path': r'Y:\_pc\Library Game',
        'name': 'Library Game',
    })()
    expl = explain_duplicate_match(
        existing,
        r'Y:\_pc\Other\Library Game [Repack]',
        'Library Game [Repack]',
    )
    assert expl['match_reason'] in {
        'same_path',
        'title_vs_folder',
        'title_vs_library_name',
        'title_below_threshold',
    }
    assert len(expl['match_reason']) <= 64
    assert isinstance(expl['transforms'], list)
    assert any(t['stage'] == 'A1' for t in expl['transforms'])
