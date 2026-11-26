"""VR editions stay separate from flat games; Meta Quest store pages as a source.

From the 2026-11-26 scan review: "Green Hell VR" was filed as a Duplicate of
"Green Hell", VR titles landed in catalog_disagreement because Steam's flat title
vetoed IGDB's VR one, "Leisure Suit Larry 9 Box Office Bust" never found
"Leisure Suit Larry: Box Office Bust", and Quest-only games ("Golden Gloves")
had no source at all.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from oneirodex.utils.duplicate_check import edition_conflict, explain_duplicate_match
from oneirodex.utils.game_name_parse import parse_game_label
from oneirodex.utils.gamenames import generate_goty_variants
from oneirodex.utils.match_scoring import select_best_match
from oneirodex.utils.meta_store import (
    meta_app_id_from_folder,
    meta_app_id_from_label,
    parse_meta_app_id,
    parse_meta_store_page,
)
from oneirodex.utils.software_identify_store import candidate_from_meta_store
from oneirodex.utils.vr_catalog import candidate_is_vr, has_vr_token

FIXTURE = Path(__file__).parent / 'fixtures' / 'meta_store_golden_gloves.html'
GOLDEN_GLOVES_ID = '5682829115084320'


# --- VR edition parsing -----------------------------------------------------

@pytest.mark.parametrize('label, cleaned, vr_form', [
    ('Green Hell VR', 'Green Hell', 'Green Hell VR'),
    ('Golden Gloves Boxing VR', 'Golden Gloves Boxing', 'Golden Gloves Boxing VR'),
    ('Eleven Table Tennis VR v354.4', 'Eleven Table Tennis', 'Eleven Table Tennis VR'),
    ('Metro Awakening VR 12 12 2024', 'Metro Awakening', 'Metro Awakening VR'),
    ('cyubeVR', 'Cyube', 'CyubeVR'),
    ('Medium VR (Oculus)', 'Medium', 'Medium VR'),
    ('Dead and buried ii [2 0 7534] (oculus)', 'Dead And Buried Ii', None),
    ('Green Hell', 'Green Hell', None),
    # A VR mod is a mod for the flat game, not a VR edition.
    ('Alien Isolation VR MOD - MotherVR 0 8 1', 'Alien Isolation', None),
])
def test_vr_edition_is_recorded_separately_from_the_cleaned_name(label, cleaned, vr_form):
    parsed = parse_game_label(label)
    assert parsed['cleaned_name'] == cleaned
    assert parsed['vr_title_form'] == vr_form
    assert parsed['vr_title'] is bool(vr_form)


def test_vr_token_and_vr_candidates():
    assert has_vr_token('Green Hell VR')
    assert has_vr_token('cyubeVR')
    assert not has_vr_token('Crisis VRigade')
    assert not has_vr_token('Green Hell')
    flat = {'name': 'Green Hell', 'platforms': [{'name': 'PC (Microsoft Windows)'}, {'name': 'PlayStation 4'}]}
    quest = {'name': "A Fisherman's Tale", 'platforms': [{'name': 'Meta Quest 2'}]}
    perspective = {'name': 'Some Game', 'player_perspectives': [{'name': 'Virtual Reality'}]}
    assert not candidate_is_vr(flat)
    assert candidate_is_vr(quest)
    assert candidate_is_vr(perspective)
    assert candidate_is_vr({'name': 'Green Hell VR'})


def test_vr_and_flat_titles_never_score_as_one_game():
    best, confidence = select_best_match('Green Hell VR', [{'name': 'Green Hell'}])
    assert best is None and confidence == 'low'


# --- duplicates ---------------------------------------------------------------

def _existing(path, name):
    return SimpleNamespace(uuid='existing', full_disk_path=path, name=name, library=None,
                           library_uuid='lib', rom_region=None)


def test_vr_edition_is_not_a_duplicate_of_the_flat_game():
    assert edition_conflict('Green Hell VR', 'Green Hell') == 'vr'
    assert edition_conflict('Green Hell', 'Green Hell (build 1)') is None
    result = explain_duplicate_match(
        _existing('/storage/_pc/_g/Green Hell', 'Green Hell'),
        '/storage/_pc/_g/Green Hell VR', 'Green Hell', new_library_uuid='lib',
    )
    assert result['is_duplicate'] is False
    assert result['match_reason'] == 'different_vr'


def test_duplicate_check_reads_the_folder_not_the_scan_cleaned_name():
    """A release-group filter cut "Remastered" from the cleaned name."""
    result = explain_duplicate_match(
        _existing("/storage/_pc/_m/Monkey Island 2 Lechuck's Revenge", "Monkey Island 2: LeChuck's Revenge"),
        '/storage/_pc/_m/Monkey Island 2 Lechucks Revenge Remastered',
        'Monkey Island 2 Lechucks Revenge', new_library_uuid='lib',
    )
    assert result['is_duplicate'] is False


def test_wrongly_matched_library_name_does_not_make_duplicates():
    """"Star Trek Deep Space Nine" filed as "Star Trek - Armada" swallowed every Star Trek folder."""
    existing = _existing('/storage/_pc/_s/Star Trek Deep Space Nine', 'Star Trek - Armada')
    for folder in ('Star Trek Enterprise', 'Star Trek The Next Generation'):
        result = explain_duplicate_match(
            existing, f'/storage/_pc/_s/{folder}', 'Star Trek', new_library_uuid='lib',
        )
        assert result['is_duplicate'] is False, folder


def test_true_duplicates_still_are():
    result = explain_duplicate_match(
        _existing('/storage/_pc/_c/Chrono Trigger (build 29.08.2023)', 'Chrono Trigger'),
        '/storage/_pc/_c/CHRONO TRIGGER v2025 10 17', 'Chrono Trigger', new_library_uuid='lib',
    )
    assert result['is_duplicate'] is True


# --- series number + subtitle -----------------------------------------------

def test_series_number_subtitle_variants():
    variants = generate_goty_variants('Leisure Suit Larry 9 Box Office Bust')
    assert 'Leisure Suit Larry 9: Box Office Bust' in variants
    assert variants[-1] == 'Leisure Suit Larry: Box Office Bust'
    best, confidence = select_best_match(
        'Leisure Suit Larry: Box Office Bust',
        [{'name': 'Leisure Suit Larry: Box Office Bust'}, {'name': 'Leisure Suit Larry: Magna Cum Laude'}],
    )
    assert confidence == 'high' and best['name'] == 'Leisure Suit Larry: Box Office Bust'
    # Edition packaging is not a subtitle.
    assert generate_goty_variants('Gothic 2 Gold Edition') == ['Gothic 2 Gold Edition']


# --- Meta Quest store ---------------------------------------------------------

@pytest.mark.parametrize('text, expected', [
    ('https://www.meta.com/experiences/golden-gloves/5682829115084320/', GOLDEN_GLOVES_ID),
    ('meta.com/experiences/5682829115084320', GOLDEN_GLOVES_ID),
    ('https://www.oculus.com/experiences/quest/5682829115084320/', GOLDEN_GLOVES_ID),
    ('https://www.meta.com/en-gb/experiences/golden-gloves/5682829115084320/', GOLDEN_GLOVES_ID),
    ('5682829115084320', GOLDEN_GLOVES_ID),
    ('Golden Gloves', None),
    ('https://store.steampowered.com/app/5682829115084320/', None),
])
def test_parse_meta_app_id(text, expected):
    assert parse_meta_app_id(text) == expected


def test_meta_tag_in_folder_name():
    label = f'Golden Gloves Boxing VR [meta {GOLDEN_GLOVES_ID}]'
    assert meta_app_id_from_label(label) == GOLDEN_GLOVES_ID
    parsed = parse_game_label(label)
    assert parsed['meta_app_id'] == GOLDEN_GLOVES_ID
    assert parsed['cleaned_name'] == 'Golden Gloves Boxing'
    assert parsed['vr_title_form'] == 'Golden Gloves Boxing VR'


def test_meta_link_file_inside_folder(tmp_path):
    folder = tmp_path / 'Golden Gloves Boxing VR'
    folder.mkdir()
    assert meta_app_id_from_folder(str(folder)) is None
    (folder / 'Meta Store.url').write_text(
        '[InternetShortcut]\nURL=https://www.meta.com/experiences/golden-gloves/5682829115084320/\n'
    )
    assert meta_app_id_from_folder(str(folder)) == GOLDEN_GLOVES_ID


def test_parse_meta_store_page():
    details = parse_meta_store_page(FIXTURE.read_text(), app_id=GOLDEN_GLOVES_ID)
    assert details['name'] == 'Golden Gloves'
    assert details['meta_quest_id'] == GOLDEN_GLOVES_ID
    assert details['url'] == 'https://www.meta.com/experiences/golden-gloves/5682829115084320/'
    assert details['developer'] == 'Engine Room VR LLC'
    assert details['publisher'] == 'Engine Room VR LLC'
    assert details['genres'] == ['Fighting', 'Sports', 'Action', 'Simulation']
    assert details['cover_url'].startswith('https://scontent-dfw6-1.oculuscdn.com/')
    assert details['summary']
    assert parse_meta_store_page('<html></html>') is None
    # A page for a different app id is not this app.
    assert parse_meta_store_page(FIXTURE.read_text(), app_id='1234567890123456') is None


def test_meta_store_candidate_and_search_by_link():
    details = parse_meta_store_page(FIXTURE.read_text(), app_id=GOLDEN_GLOVES_ID)
    candidate = candidate_from_meta_store(details)
    assert candidate['source'] == 'meta_quest'
    assert candidate['name'] == 'Golden Gloves'
    assert candidate['item_kind'] == 'game'
    assert candidate['match_mode'] == 'store_link'

    from oneirodex.utils.providers import meta_quest

    with patch('oneirodex.utils.meta_store.fetch_meta_store_app', return_value=details):
        hits = meta_quest.search_meta_quest_games(
            'https://www.meta.com/experiences/golden-gloves/5682829115084320/'
        )
    assert [hit['name'] for hit in hits] == ['Golden Gloves']
    assert hits[0]['developer'] == 'Engine Room VR LLC'


# --- scan identify (mocked HTTP) -------------------------------------------------

_SETTINGS = {
    'use_local_metadata': False,
    'write_local_metadata': False,
    'use_local_images': False,
    'local_metadata_filename': 'oneirodex.json',
    'propose_only_scan': False,
}


@pytest.fixture
def pc_library(db_session):
    from oneirodex.models import Library
    from oneirodex.platform import LibraryPlatform

    lib = Library(name=f'VR_Lib_{uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    return lib


@pytest.mark.integration
def test_scan_never_files_a_vr_folder_under_the_flat_game(app, db_session, pc_library):
    from oneirodex.utils.game_core import retrieve_and_save_game

    flat = {'id': 101461, 'name': 'Green Hell', 'platforms': [{'name': 'PC (Microsoft Windows)'}]}
    searched = []

    def igdb(name, platform_id, limit=10, **kwargs):
        searched.append(name)
        return [dict(flat)]

    steam_queries = []

    def steam(query, limit=10, include_software=False):
        steam_queries.append(query)
        return [{'name': 'Green Hell', 'steam_app_id': 815370, 'steam_type': 'game'}]

    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game', side_effect=igdb), \
            patch('oneirodex.utils.services.scan_identify.notify_admins_new_game'), \
            patch('oneirodex.utils.software_identify.search_steam_games', side_effect=steam), \
            patch('oneirodex.utils.software_identify.search_gog_games', return_value=[]), \
            patch('oneirodex.utils.software_identify.search_epic_games', return_value=[]), \
            patch('oneirodex.utils.services.scan_identify.get_folder_size_in_bytes_updates', return_value=0):
        result = retrieve_and_save_game(
            'Green Hell', f'/tmp/oneirodex-vr-test-{uuid4().hex[:6]}/Green Hell VR',
            library_uuid=pc_library.uuid, settings=dict(_SETTINGS),
        )

    assert searched[0] == 'Green Hell VR'
    assert 'Green Hell' in searched  # the flat name is still tried, for VR products only
    assert result is None
    assert steam_queries and all('VR' in q for q in steam_queries)


@pytest.mark.integration
def test_scan_reads_a_linked_meta_store_page(app, db_session, pc_library, tmp_path):
    from oneirodex.models import GameURL
    from oneirodex.utils.game_core import retrieve_and_save_game
    from oneirodex.utils.software_identify import CUSTOM_IGDB_BASE

    details = parse_meta_store_page(FIXTURE.read_text(), app_id=GOLDEN_GLOVES_ID)
    path = str(tmp_path / f'Golden Gloves Boxing VR [meta {GOLDEN_GLOVES_ID}]')
    Path(path).mkdir()
    searched = []

    def igdb(name, platform_id, limit=10, **kwargs):
        searched.append(name)
        return []

    with patch('oneirodex.utils.services.scan_identify.search_igdb_for_game', side_effect=igdb), \
            patch('oneirodex.utils.meta_store.fetch_meta_store_app', return_value=details), \
            patch('oneirodex.utils.services.scan_identify.notify_admins_new_game'), \
            patch('oneirodex.utils.software_identify.search_steam_games', return_value=[]) as steam, \
            patch('oneirodex.utils.software_identify.search_gog_games', return_value=[]), \
            patch('oneirodex.utils.software_identify.search_epic_games', return_value=[]), \
            patch('oneirodex.utils.services.scan_identify.get_folder_size_in_bytes_updates', return_value=0):
        result = retrieve_and_save_game(
            'Golden Gloves Boxing', path,
            library_uuid=pc_library.uuid, settings=dict(_SETTINGS),
        )

    assert searched and set(searched) == {'Golden Gloves'}
    steam.assert_not_called()
    assert result is not None
    assert result.igdb_id >= CUSTOM_IGDB_BASE
    assert result.name == 'Golden Gloves'
    db_session.flush()
    urls = db_session.query(GameURL).filter_by(game_uuid=result.uuid, url_type='meta_quest').all()
    assert [u.url for u in urls] == [details['url']]
    assert 'Virtual Reality' in {p.name for p in result.player_perspectives}
    assert result.developer is not None and result.developer.name == 'Engine Room VR LLC'


def test_catalog_identity_tolerates_accents_and_dotted_acronyms():
    from oneirodex.utils.software_identify import titles_identify_agree

    assert titles_identify_agree('Brütal Legend', 'Brutal Legend')
    assert titles_identify_agree('D.E.C.A.Y', 'DECAY')
    assert titles_identify_agree('Half-Life 2', 'Half Life 2')
    assert not titles_identify_agree('Doom', 'Doom 3')
