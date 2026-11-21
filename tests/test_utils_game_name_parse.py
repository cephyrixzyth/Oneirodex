"""Unit tests for folder label parsing (Stage A0–A8). No DB required.

Fixtures follow docs/strategy/name-resolution.md acceptance table.
Path fixtures use Y: / UNC / %TEMP% shapes — never Z: (NAS).
"""

import os

import pytest

from oneirodex.utils.game_name_parse import (
    inject_franchise_apostrophes,
    is_bare_franchise,
    parse_game_label,
    strip_addon_junk_tails,
    strip_date_stamp_tails,
    strip_incl_update_tails,
    strip_repack_tags,
    strip_unbracketed_scene_suffix,
    strip_update_build_prose_tails,
    strip_version_access_tails,
    strip_version_brackets,
    strip_build_tail,
    strip_vr_noise_tail,
)


def test_fitgirl_repack_stripped():
    r = parse_game_label("Assassin's Creed Shadows [FitGirl Repack]")
    assert r['cleaned_name'] == "Assassin's Creed Shadows"
    assert r['steam_app_id'] is None


def test_fitgirl_hv_repack_stripped():
    r = parse_game_label("Borderlands 4 [FitGirl HV Repack]")
    assert "FitGirl" not in r['cleaned_name']
    assert "Repack" not in r['cleaned_name']
    assert "Borderlands 4" in r['cleaned_name']


def test_fitgirl_lowercase_tag():
    r = parse_game_label("Alan Wake 2 [Fitgirl Repack]")
    assert r['cleaned_name'] == "Alan Wake 2"
    assert r['steam_app_id'] is None


def test_generic_repack_and_hv_repack_brackets():
    """A1 — bare [Repack] / [HV Repack] and unknown-prefix tags."""
    assert parse_game_label("Abyssus [Repack]")['cleaned_name'] == "Abyssus"
    assert parse_game_label("Title [HV Repack]")['cleaned_name'] == "Title"
    assert parse_game_label("Some Unknown [Whatever Repack]")['cleaned_name'] == "Some Unknown"
    assert parse_game_label("Game [Random HV Repack]")['cleaned_name'] == "Game"


def test_steam_app_id_extracted_and_stripped():
    r = parse_game_label("barony (89881)")
    assert r['catalog_number'] == 89881
    assert r['cleaned_name'].lower() == "barony"


def test_steam_app_id_with_fitgirl_not_typical_but_id_trailing():
    r = parse_game_label("Abandon Ship (81735)")
    assert r['catalog_number'] == 81735
    assert "Abandon Ship" in r['cleaned_name']


def test_remastered_kept_for_disambiguation():
    r = parse_game_label("Alan Wake - Remastered [FitGirl Repack]")
    assert "Alan Wake" in r['cleaned_name']
    assert "Remastered" in r['cleaned_name'] or "Remaster" in r['cleaned_name']


def test_version_bracket_junk_stripped():
    r = parse_game_label("Some Game [1 0 4 1]")
    assert r['cleaned_name'] == "Some Game"
    assert "[1" not in r['cleaned_name']
    assert strip_version_brackets("Game [1.0.4.1]") == "Game"


def test_strip_repack_tags_alone():
    assert "[FitGirl" not in strip_repack_tags("Game [FitGirl HV Repack]")
    assert "[Repack]" not in strip_repack_tags("Game [Repack]")
    assert strip_repack_tags("Plain Game") == "Plain Game"


def test_raw_preserved():
    raw = "ctrl alt ego (89861)"
    r = parse_game_label(raw)
    assert r['raw'] == raw
    assert r['catalog_number'] == 89861


def test_a0_basename_only_y_drive_and_unc():
    """A0 — path segments dropped; prefer Y:/UNC (never remap Z:)."""
    r = parse_game_label(r"Y:\_pc\_a\Abyssus [Repack]")
    assert r['cleaned_name'] == "Abyssus"
    unc = r"\\192.168.50.116\isos\library\_pc\_a\Abandon Ship (81735)"
    r2 = parse_game_label(unc)
    assert r2['cleaned_name'] == "Abandon Ship"
    assert r2['catalog_number'] == 81735
    temp_shaped = os.path.join(os.environ.get('TEMP', '/tmp'), 'Abiotic Factor [Repack]')
    assert parse_game_label(temp_shaped)['cleaned_name'] == "Abiotic Factor"


# --- GM acceptance fixtures (Stage A cleaned_name + steam_app_id) ---

def test_gm_01_abyssus_repack():
    r = parse_game_label("Abyssus [Repack]")
    assert r['cleaned_name'] == "Abyssus"
    assert r['steam_app_id'] is None


def test_gm_02_assassins_creed_odyssey_hv_repack():
    r = parse_game_label("Assassin's Creed Odyssey [HV Repack]")
    assert r['cleaned_name'] == "Assassin's Creed Odyssey"
    assert r['steam_app_id'] is None


def test_gm_03_assassins_creed_rogue_apostrophe_inject():
    r = parse_game_label("Assassins Creed Rogue")
    assert r['cleaned_name'] == "Assassin's Creed Rogue"
    assert r['steam_app_id'] is None


def test_gm_04_abandon_ship_steam_id():
    r = parse_game_label("Abandon Ship (81735)")
    assert r['cleaned_name'] == "Abandon Ship"
    assert r['catalog_number'] == 81735


def test_gm_05_angeline_era_steam_id():
    r = parse_game_label("angeline era (88323)")
    assert r['cleaned_name'] == "Angeline Era"
    assert r['catalog_number'] == 88323


def test_gm_06_fishermans_tale_vr():
    r = parse_game_label("A Fishermans Tale VR")
    assert r['cleaned_name'] == "A Fisherman's Tale"
    assert "VR" not in r['cleaned_name']


def test_gm_07_alien_isolation_vr_mod():
    r = parse_game_label("Alien Isolation VR MOD - MotherVR 0 8 1")
    assert r['cleaned_name'] == "Alien Isolation"
    assert "VR" not in r['cleaned_name']
    assert "MotherVR" not in r['cleaned_name']


def test_gm_08_spaced_version_v0_4():
    r = parse_game_label("Some Game v0 4")
    assert r['cleaned_name'] == "Some Game"


def test_gm_09_spaced_version_v1_188():
    r = parse_game_label("Some Game v1 188")
    assert r['cleaned_name'] == "Some Game"


def test_gm_10_adr1ft_build_spaced():
    r = parse_game_label("ADR1FT (build 18 05 2023)")
    assert r['cleaned_name'] == "Adrift"
    assert r['steam_app_id'] is None


def test_gm_11_early_access_stripped():
    r = parse_game_label("Title Early Access")
    assert r['cleaned_name'] == "Title"


def test_gm_12_alone_in_the_dark_2024():
    r = parse_game_label("Alone in the Dark 2024")
    assert r['cleaned_name'] == "Alone In The Dark 2024"
    assert r['steam_app_id'] is None


def test_gm_13_alone_in_the_dark_2008():
    r = parse_game_label("Alone in the Dark 2008")
    assert r['cleaned_name'] == "Alone In The Dark 2008"


def test_gm_14_alan_wake_complete_collection_kept():
    r = parse_game_label("Alan Wake Complete Collection")
    assert r['cleaned_name'] == "Alan Wake Complete Collection"


def test_gm_15_baldurs_gate_dark_alliance_1():
    r = parse_game_label("Baldur's Gate Dark Alliance 1")
    assert r['cleaned_name'] == "Baldur's Gate Dark Alliance 1"


def test_gm_16_agatha_christie_steam_id():
    r = parse_game_label("agatha christie death on the nile (85933)")
    assert r['catalog_number'] == 85933
    assert r['cleaned_name'] == "Agatha Christie Death On The Nile"


def test_gm_17_barony_steam_id():
    r = parse_game_label("barony (89881)")
    assert r['cleaned_name'] == "Barony"
    assert r['catalog_number'] == 89881


def test_abiotic_factor_fitgirl_repack():
    r = parse_game_label("Abiotic Factor [FitGirl Repack]")
    assert r['cleaned_name'] == "Abiotic Factor"


def test_alien_vs_predator_dodi_repack():
    r = parse_game_label("Alien vs. Predator - [DODI Repack]")
    assert r['cleaned_name'] == "Alien Vs. Predator"
    assert "DODI" not in r['cleaned_name']
    assert "Repack" not in r['cleaned_name']


def test_avowed_mid_title_v_not_stripped():
    """A6 must not strip mid-title 'v' letters (Avowed)."""
    r = parse_game_label("Avowed")
    assert r['cleaned_name'] == "Avowed"


def test_strip_version_access_tails_alone():
    assert strip_version_access_tails("Some Game v0 4") == "Some Game"
    assert strip_version_access_tails("Some Game v1 188") == "Some Game"
    assert strip_version_access_tails("Title Early Access") == "Title"
    assert strip_version_access_tails("Title EA") == "Title"
    assert strip_version_access_tails("Avowed") == "Avowed"


def test_inject_franchise_apostrophes_alone():
    assert inject_franchise_apostrophes("Assassins Creed Rogue") == "Assassin's Creed Rogue"
    assert inject_franchise_apostrophes("Assassin's Creed Rogue") == "Assassin's Creed Rogue"
    assert inject_franchise_apostrophes("A Fishermans Tale") == "A Fisherman's Tale"
    assert inject_franchise_apostrophes("Baldurs Gate Dark Alliance") == "Baldur's Gate Dark Alliance"


def test_strip_build_tail_alone():
    assert strip_build_tail("ADR1FT (Build 14.09.2017)") == "ADR1FT"
    assert strip_build_tail("ADR1FT (build 18 05 2023)") == "ADR1FT"
    assert strip_build_tail("Plain Game") == "Plain Game"


def test_strip_vr_noise_tail_alone():
    assert strip_vr_noise_tail("A Fishermans Tale VR") == "A Fishermans Tale"
    assert strip_vr_noise_tail("Alien Isolation VR MOD - MotherVR 0 8 1") == "Alien Isolation"
    assert strip_vr_noise_tail("3DSenVR") == "3DSen"
    assert strip_vr_noise_tail("Plain Game") == "Plain Game"


def test_parse_3dsenvr_had_vr_suffix():
    r = parse_game_label("3DSenVR")
    assert r["cleaned_name"] == "3DSen"
    assert r["had_vr_suffix"] is True



# --- A9–A14 fixtures (docs/strategy/name-resolution.md) ---

def test_a9_incl_update_parenthetical():
    r = parse_game_label("Pathologic 2 (Incl Update 7)")
    assert r['cleaned_name'] == "Pathologic 2"
    assert r['steam_app_id'] is None


def test_a9_incl_update_no_number():
    r = parse_game_label("Dragon's Dogma Dark Arisen (Incl Update)")
    assert r['cleaned_name'] == "Dragon's Dogma Dark Arisen"


def test_a9_oculus_paren_stripped():
    r = parse_game_label("Dead and buried ii [2 0 7534] (oculus)")
    assert r['cleaned_name'] == "Dead And Buried Ii"
    assert "(oculus)" not in r['cleaned_name'].casefold()


def test_a10_unbracketed_scene_hyphen():
    r = parse_game_label("Some Game - GROUP")
    assert r['cleaned_name'] == "Some Game"


def test_a10_unbracketed_scenegrp_hyphen_attached():
    r = parse_game_label("Title Game-SCENEGRP")
    assert r['cleaned_name'] == "Title Game"
    assert "SCENEGRP" not in r['cleaned_name']


def test_a10_trailing_scene_token():
    r = parse_game_label("Blades of Fire Update v2 0 0 5 SCENE")
    assert r['cleaned_name'] == "Blades Of Fire"


def test_a10_single_token_hyphen_scene_stripped():
    """Hyphen-glued scene suffixes allow a single head token (BeachHead-ALIAS)."""
    assert strip_unbracketed_scene_suffix("GROUP") == "GROUP"
    assert strip_unbracketed_scene_suffix("Alone-SCENEGRP") == "Alone"
    assert parse_game_label("BeachHead-SKIDROW")['cleaned_name'] == "BeachHead"
    assert parse_game_label("Some Game-CODEX")['cleaned_name'] == "Some Game"
    assert parse_game_label("Game Title - SKIDROW")['cleaned_name'] == "Game Title"


def test_a11_alfred_hitchcock_date_stamp():
    r = parse_game_label("Alfred Hitchcock Vertigo 2022093001")
    assert r['cleaned_name'] == "Alfred Hitchcock Vertigo"
    assert r['steam_app_id'] is None


def test_steam_id_63_days():
    r = parse_game_label("63 days (88642)")
    assert r['catalog_number'] == 88642
    assert r['cleaned_name'] == "63 Days"


def test_ff_vii_bracket_repack():
    r = parse_game_label("Final Fantasy VII [FitGirl Repack]")
    assert r['cleaned_name'] == "Final Fantasy VII"
    assert "Repack" not in r['cleaned_name']


def test_dragons_dogma_incl_update_7():
    r = parse_game_label("Dragon's Dogma Dark Arisen (Incl Update 7)")
    assert r['cleaned_name'] == "Dragon's Dogma Dark Arisen"
    assert r['steam_app_id'] is None


def test_baldurs_gate_2_kept():
    r = parse_game_label("Baldur's Gate 2")
    assert r['cleaned_name'] == "Baldur's Gate 2"
    assert r['steam_app_id'] is None


def test_year_kept_alone_in_the_dark_2008():
    r = parse_game_label("Alone in the Dark 2008")
    assert r['cleaned_name'] == "Alone In The Dark 2008"


def test_a11_date_stamp_tail():
    r = parse_game_label("Some Game 2022093001")
    assert r['cleaned_name'] == "Some Game"


def test_a11_compact_v_block():
    r = parse_game_label("Some Game V16092671")
    assert r['cleaned_name'] == "Some Game"


def test_a12_update_version_tail():
    r = parse_game_label("Some Game Update v1.2")
    assert r['cleaned_name'] == "Some Game"


def test_a12_update_version_range():
    r = parse_game_label("Some Game update 1.24.01 - 1.25.01")
    assert r['cleaned_name'] == "Some Game"


def test_a12_bare_build_n():
    r = parse_game_label("Some Game Build 18")
    assert r['cleaned_name'] == "Some Game"


def test_a14_vr_repass_after_version():
    r = parse_game_label("Some Game VR v0 8 1")
    assert r['cleaned_name'] == "Some Game"
    assert "VR" not in r['cleaned_name']


def test_a14_summer_sports_vr_version():
    r = parse_game_label("All In One Summer Sports VR v0 4")
    assert r['cleaned_name'] == "All In One Summer Sports"
    assert "VR" not in r['cleaned_name']


def test_a13_4k_addon_junk_stripped():
    r = parse_game_label("Some Game 4K Videos Add-on")
    assert r['cleaned_name'] == "Some Game"


def test_a13_bracketed_4k_addon_repack():
    r = parse_game_label("Mortal Kombat 1 [4K Videos Add-on Repack]")
    assert r['cleaned_name'] == "Mortal Kombat 1"


def test_a13_collectors_edition_kept_for_c10():
    r = parse_game_label("Some Game Collector's Edition")
    assert r['cleaned_name'] == "Some Game Collector's Edition"
    assert r['bare_franchise'] is False


def test_c11_bare_franchise_flag():
    r = parse_game_label("Final Fantasy")
    assert r['cleaned_name'] == "Final Fantasy"
    assert r['bare_franchise'] is True
    assert is_bare_franchise("Final Fantasy") is True
    assert is_bare_franchise("Final Fantasy IV") is False


def test_lettered_version_v1_1_0a():
    r = parse_game_label("3 Minutes to Midnight v1.1.0a")
    assert r['cleaned_name'] == "3 Minutes To Midnight"


def test_atom_rpg_spaced_version():
    r = parse_game_label("ATOM RPG v1 188")
    assert r['cleaned_name'] == "ATOM RPG"


def test_ancient_dungeon_version_then_vr():
    r = parse_game_label("Ancient Dungeon v0 1 6 6 VR")
    assert r['cleaned_name'] == "Ancient Dungeon"


def test_adr1ft_build_dotted_date():
    r = parse_game_label("ADR1FT (Build 14.09.2017)")
    assert r['cleaned_name'] == "Adrift"


def test_beyond_good_and_evil_hv_repack():
    r = parse_game_label("Beyond Good and Evil - 20th AE [HV Repack]")
    assert r['cleaned_name'] == "Beyond Good And Evil - 20th AE"
    assert "Repack" not in r['cleaned_name']


def test_lowercase_steam_id_49_keys():
    r = parse_game_label("49 keys (87117)")
    assert r['catalog_number'] == 87117
    assert r['cleaned_name'] == "49 Keys"


def test_steam_id_1000x_resist():
    r = parse_game_label("1000x Resist (77125)")
    assert r['catalog_number'] == 77125
    assert "1000x" in r['cleaned_name']
    assert "Resist" in r['cleaned_name']


def test_baldurs_gate_ee_steam_id():
    r = parse_game_label("Baldur's Gate 1 Enhanced Edition (68994)")
    assert r['catalog_number'] == 68994
    assert "Baldur's Gate 1 Enhanced Edition" == r['cleaned_name']


def test_ff_iv_complete_collection_build():
    r = parse_game_label("Final Fantasy IV Complete Collection (build 05.11.2020)")
    assert r['cleaned_name'] == "Final Fantasy IV Complete Collection"
    assert r['bare_franchise'] is False


def test_strip_helpers_a9_a13_alone():
    assert strip_incl_update_tails("Pathologic 2 (Incl Update 3)") == "Pathologic 2"
    assert strip_date_stamp_tails("Some Game 2022093001") == "Some Game"
    assert strip_update_build_prose_tails("Some Game Update v1.2") == "Some Game"
    assert strip_update_build_prose_tails("Some Game Build 18") == "Some Game"
    assert strip_addon_junk_tails("Some Game 4K Videos Add-on") == "Some Game"
    assert strip_addon_junk_tails("Some Game HV") == "Some Game"


# --- W22-M5 UPDATE packaging hints ---

def test_bare_update_package_folder_detected():
    from oneirodex.utils.game_name_parse import (
        detect_update_packaging,
        is_bare_update_package,
    )

    assert is_bare_update_package('UPDATE')
    assert is_bare_update_package('Updates')
    assert is_bare_update_package('updates')
    assert is_bare_update_package('UPDATES')
    assert not is_bare_update_package('Pathologic 2 (Incl Update 3)')

    for name in ('UPDATE', 'Updates', 'updates', 'UPDATES'):
        meta = detect_update_packaging(name)
        assert meta['is_bare_update_package'] is True
        assert meta['update_folder_hint'] is True
        assert meta['match_reason'] == 'update_package_folder'


def test_incl_update_sets_packaging_hint_not_bare():
    r = parse_game_label('Pathologic 2 (Incl Update 3)')
    assert r['cleaned_name'] == 'Pathologic 2'
    assert r['update_folder_hint'] is True
    assert r['is_bare_update_package'] is False
    assert r['update_match_reason'] == 'update_packaging_hint'


def test_update_prose_tail_sets_packaging_hint():
    r = parse_game_label('Some Game Update v1.2')
    assert r['cleaned_name'] == 'Some Game'
    assert r['update_folder_hint'] is True
    assert r['is_bare_update_package'] is False


def test_trailing_update_sep_hint():
    r = parse_game_label('Cool Title - UPDATE')
    assert r['cleaned_name'] == 'Cool Title'
    assert r['update_folder_hint'] is True
    assert r['is_bare_update_package'] is False


def test_format_why_unmatched_update_package():
    from oneirodex.utils.match_proposal import format_why_unmatched

    text = format_why_unmatched(
        status='Unmatched',
        match_reason='update_package_folder',
        folder_name='Updates',
        suggested_kind=None,
    )
    assert 'update or patch package' in text
    assert 'Soft title' not in text
    assert 'Experience' not in text


# --- household packaging noise (2026-11-19 unmatched review) -----------------


@pytest.mark.parametrize('raw, cleaned', [
    ('3 Minutes to Midnight v1.1.0a', '3 Minutes To Midnight'),
    ('8bit Adventures 2 (79354)', '8bit Adventures 2'),
    ('The necromancers tale 1 235 (64bit) (91571) win gog', 'The Necromancers Tale'),
    ('Superhot Mind Control Delete [GOG]', 'Superhot Mind Control Delete'),
    ('Call Of Cthulhu Prisoner Of Ice GOG', 'Call Of Cthulhu Prisoner Of Ice'),
    ('ALIEN ABDUCTION EXPERIENCE TiNYiSO', 'ALIEN ABDUCTION EXPERIENCE'),
    ('DERELIKT-P2P', 'DERELIKT'),
    ('Chuchel Cherry Edition V 2 0 0', 'Chuchel Cherry Edition'),
    ('Cultures 1+2 (July25, 2001)', 'Cultures 1+2'),
    ('Wonder Boy The Dragons Trap 1.03g', 'Wonder Boy The Dragons Trap'),
    ('Myst 3 Exile (83079)', 'Myst 3 Exile'),
    ('1979 Revolution (2016)', '1979 Revolution'),
    # Titles that only look like noise stay intact.
    ('Win That War', 'Win That War'),
    ('Kingdom Hearts 2.5', 'Kingdom Hearts 2.5'),
    ('Quake 2', 'Quake 2'),
])
def test_household_packaging_noise_is_peeled(raw, cleaned):
    assert parse_game_label(raw)['cleaned_name'] == cleaned


def test_bare_paren_number_is_never_a_steam_app_id():
    r = parse_game_label('8bit Adventures 2 (79354)')
    assert r['steam_app_id'] is None
    assert r['catalog_number'] == 79354


def test_paren_year_is_not_a_catalog_number():
    r = parse_game_label('1979 Revolution (2016)')
    assert r['catalog_number'] is None


@pytest.mark.parametrize('raw, cleaned', [
    # dates: dd mm yyyy, dd mm.yyyy, (v dd mm yyyy), Vmm mm.yyyy
    ('Metro Awakening VR 12 12 2024', 'Metro Awakening'),
    ('Resident Evil Village 10 04.2023', 'Resident Evil Village'),
    ('Snufkin MoMoomin valley 18 12.2024', 'Snufkin MoMoomin Valley'),
    ('Swordsman VR (v11 06 2022)', 'Swordsman'),
    ('Tracks Train Game 30 11.2021', 'Tracks Train Game'),
    ('Vertigo 1 Remastered V04 04.2023', 'Vertigo 1 Remastered'),
    # bare version tails
    ('Dragon Age II 1.04', 'Dragon Age II'),
    ('Gothic 2 Gold Edition 2.60', 'Gothic 2 Gold Edition'),
    ('CrossCode 1.4.2-3', 'CrossCode'),
    ('Book Of Demons 1 04 22689', 'Book Of Demons 1'),
    ('Beyond Blue 1 4 16124', 'Beyond Blue 1'),
    ('Larva Mortus 1 0.2 (55857)', 'Larva Mortus'),
    ('Sifu 1 28.6.720', 'Sifu'),
    ('Gone Rogue 1 14', 'Gone Rogue'),
    ('One Punch Man A Hero Nobody Knows 1 300', 'One Punch Man A Hero Nobody Knows'),
    ('The Legend of Khiimori v0 8 4 Early Acces', 'The Legend Of Khiimori'),
    ('Dagon by H P. Lovecraft All DLC', 'Dagon By H P. Lovecraft'),
    # real titles with numbers stay
    ('Fritz Chess 20', 'Fritz Chess 20'),
    ('Pixel Ripped 1978', 'Pixel Ripped 1978'),
    ('Serpent In The Staglands 19', 'Serpent In The Staglands 19'),
    ('Kingdom Hearts 2.5', 'Kingdom Hearts 2.5'),
    ('Tony Hawks Pro Skater 3 Plus 4', 'Tony Hawks Pro Skater 3 Plus 4'),
    ('Worms 2', 'Worms 2'),
])
def test_version_and_date_tails_are_peeled(raw, cleaned):
    assert parse_game_label(raw)['cleaned_name'] == cleaned
