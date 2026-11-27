"""Scan matching recovery: retried misses, sequel-safe truncation, IGDB outages.

Regressions from the 2026-11-19 review of a live library where every game had
been created from a store exact title (IGDB refused at the address pin), sequels
collapsed onto base titles through name truncation, and old misses were never
retried.
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from oneirodex.models import Library, ScanJob, UnmatchedFolder
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.scanning import (
    clear_retried_unmatched,
    log_unmatched_folder,
    note_scan_job_problem,
    settled_unmatched_paths,
    truncated_search_names,
)


@pytest.mark.parametrize('name, expected', [
    ('Myst 3 Exile', ['Myst 3']),
    ('I Expect You To Die 2 VR', ['I Expect You To Die 2']),
    ('Quake III Gold Edition', ['Quake III Gold', 'Quake III']),
    ('Shenmue I And II', []),
    ('Battletoads', []),
    ('Some Long Game Name Here Deluxe',
     ['Some Long Game Name Here', 'Some Long Game Name', 'Some Long Game']),
])
def test_truncation_never_drops_a_sequel_number(name, expected):
    assert truncated_search_names(name) == expected


def test_igdb_error_is_reported_as_unavailable_not_as_no_results():
    from oneirodex.utils.clients import igdb

    config = {'IGDB_API_ENDPOINT': 'https://api.igdb.com/v4/games'}
    with patch.object(igdb, 'get_runtime_config', return_value=config), patch.object(igdb, 'make_igdb_api_request', return_value={'error': 'Failed to retrieve access token'}):
        assert igdb.search_igdb_for_game('Choplifter HD', None) is None
        with pytest.raises(igdb.IgdbUnavailable, match='access token'):
            igdb.search_igdb_for_game('Choplifter HD', None, raise_on_error=True)
    with patch.object(igdb, 'get_runtime_config', return_value=config),             patch.object(igdb, 'make_igdb_api_request', return_value=[]):
        assert igdb.search_igdb_for_game('No Such Game', None, raise_on_error=True) is None


@pytest.fixture
def scan_library(db_session):
    lib = Library(name=f'ScanLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.commit()
    return lib


def _row(db_session, lib, **values):
    row = UnmatchedFolder(
        library_uuid=lib.uuid,
        folder_path=f'/storage/_pc/{uuid4().hex[:8]}',
        status=values.pop('status', 'Unmatched'),
        **values,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_plain_misses_are_retried_but_handled_rows_are_not(db_session, scan_library):
    plain = _row(db_session, scan_library)
    ignored = _row(db_session, scan_library, status='Ignore')
    reviewed = _row(db_session, scan_library, review_decision={'revision': 1})
    flagged = _row(db_session, scan_library, bad_match_reason='wrong_game')

    settled = settled_unmatched_paths(scan_library.uuid)
    assert plain.folder_path not in settled
    assert {ignored.folder_path, reviewed.folder_path, flagged.folder_path} <= settled


def test_a_retried_folder_that_matches_drops_its_unmatched_row(db_session, scan_library):
    plain = _row(db_session, scan_library)
    reviewed = _row(db_session, scan_library, review_decision={'revision': 1})

    clear_retried_unmatched(plain.folder_path, scan_library.uuid)
    clear_retried_unmatched(reviewed.folder_path, scan_library.uuid)

    db_session.expire_all()
    assert db_session.get(UnmatchedFolder, plain.id) is None
    assert db_session.get(UnmatchedFolder, reviewed.id) is not None


def _job(db_session, lib):
    job = ScanJob(id=str(uuid4()), library_uuid=lib.uuid, status='Running')
    db_session.add(job)
    db_session.commit()
    return job


def test_a_retried_miss_records_the_new_scan_and_keeps_its_same_run_reason(db_session, scan_library):
    old_job, new_job = _job(db_session, scan_library), _job(db_session, scan_library)
    row = _row(db_session, scan_library, scan_job_id=old_job.id, match_reason='igdb_unavailable')

    # This run reaches IGDB and still misses: the stale outage reason goes.
    log_unmatched_folder(new_job.id, row.folder_path, 'Unmatched', scan_library.uuid)
    db_session.expire_all()
    row = db_session.get(UnmatchedFolder, row.id)
    assert row.scan_job_id == new_job.id
    assert row.match_reason is None

    # Within one run, the fallback's reason-less log keeps the reason just recorded.
    log_unmatched_folder(new_job.id, row.folder_path, 'Unmatched', scan_library.uuid,
                         match_reason='igdb_unavailable')
    log_unmatched_folder(new_job.id, row.folder_path, 'Unmatched', scan_library.uuid)
    db_session.expire_all()
    assert db_session.get(UnmatchedFolder, row.id).match_reason == 'igdb_unavailable'


def test_scan_job_problem_is_recorded_once(db_session, scan_library):
    job = _job(db_session, scan_library)
    note_scan_job_problem(job.id, 'IGDB unavailable: Failed to retrieve access token')
    note_scan_job_problem(job.id, 'IGDB unavailable: Failed to retrieve access token')
    db_session.expire_all()
    assert db_session.get(ScanJob, job.id).error_message == 'IGDB unavailable: Failed to retrieve access token'


def test_scan_job_finish_time_follows_its_status(db_session, scan_library):
    job = _job(db_session, scan_library)
    assert job.finished_at is None
    job.status = 'Completed'
    db_session.commit()
    finished = job.finished_at
    assert finished is not None
    job.status = 'Completed'  # re-saving a final status keeps the original time
    db_session.commit()
    assert job.finished_at == finished
    job.status = 'Running'
    db_session.commit()
    assert job.finished_at is None


def test_scan_history_lists_unmatched_reasons_per_job(db_session, scan_library):
    from oneirodex.runtime_native.scan_job_reads import ScanJobReadData

    job = _job(db_session, scan_library)
    for reason in (None, None, 'update_package_folder', 'igdb_unavailable'):
        _row(db_session, scan_library, scan_job_id=job.id, match_reason=reason)
    reasons = ScanJobReadData().failure_reasons([job.id])[job.id]
    assert reasons[0] == {'reason': 'no_confident_match', 'label': 'No confident match', 'count': 2}
    labels = {item['label'] for item in reasons}
    assert {'Update package, not a game', 'IGDB unavailable (retried next scan)'} <= labels


def test_timing_reports_the_finish_time_for_final_runs():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from oneirodex.utils.scan_job_timing import compute_scan_job_timing

    start = datetime(2026, 11, 19, 20, 11, tzinfo=timezone.utc)
    end = datetime(2026, 11, 20, 2, 38, tzinfo=timezone.utc)
    done = SimpleNamespace(status='Completed', last_run=start, last_progress_update=end,
                           finished_at=end, total_folders=10, folders_success=8, folders_failed=2)
    timing = compute_scan_job_timing(done)
    assert timing['finished_at'] == end.isoformat()
    assert timing['elapsed_label'] == '6h 27m 0s'
    running = SimpleNamespace(**{**vars(done), 'status': 'Running', 'finished_at': None})
    assert compute_scan_job_timing(running)['finished_at'] is None


def test_steam_cover_refresh_targets_only_small_capsules():
    from scripts.refresh_steam_covers import needs_refresh

    assert needs_refresh('https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1/capsule_231x87.jpg?t=1')
    assert needs_refresh(None)
    assert not needs_refresh('https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/1/library_600x900.jpg')
    assert not needs_refresh('https://images.igdb.com/igdb/image/upload/t_cover_big/co1.jpg')


def test_steam_cover_lookup_never_reaches_steam_in_tests():
    from oneirodex.utils.steam_lookup import steam_cover_for_app

    assert steam_cover_for_app(220, 'tiny.jpg') == 'tiny.jpg'
    assert steam_cover_for_app(220).endswith('/220/header.jpg')
    assert steam_cover_for_app('not-an-id', 'tiny.jpg') == 'tiny.jpg'


@pytest.mark.parametrize('folder, candidates, expected', [
    ('Jagged Alliance 2',
     ['Jagged Alliance 2', 'Jagged Alliance 2: Wildfire', 'Jagged Alliance 2: Gold Pack'],
     'Jagged Alliance 2'),
    ('Heads Will Roll Reforged',
     ['Heads Will Roll: Reforged', 'Heads Will Roll: Reforged - Not a Hero'],
     'Heads Will Roll: Reforged'),
])
def test_an_exact_title_beats_its_own_subtitled_variants(folder, candidates, expected):
    from oneirodex.utils.match_scoring import select_best_match

    best, confidence = select_best_match(folder, [{'name': name} for name in candidates])
    assert confidence == 'high'
    assert best['name'] == expected


def test_a_lone_subtitled_remaster_still_matches_and_two_exacts_stay_ambiguous():
    from oneirodex.utils.match_scoring import select_best_match

    best, confidence = select_best_match(
        'Broken Sword 2', [{'name': 'Broken Sword 2 - the Smoking Mirror: Remastered'}],
    )
    assert confidence == 'high' and best['name'].startswith('Broken Sword 2')
    # No exact title among several boosted variants: still a person's call.
    _, confidence = select_best_match(
        'Jagged Alliance 2', [{'name': 'Jagged Alliance 2: Wildfire'}, {'name': 'Jagged Alliance 2: Gold Pack'}],
    )
    assert confidence == 'low'


def test_igdb_request_retries_a_timeout_then_succeeds():
    import requests
    from types import SimpleNamespace

    from oneirodex.utils import igdb_api

    calls = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ReadTimeout('slow')
        return SimpleNamespace(status_code=200)

    with patch.object(igdb_api, 'safe_request_limited', side_effect=fake):
        response = igdb_api._post_igdb_with_retry('https://api.igdb.com/v4/games', {}, 'q', sleep=lambda _s: None)
    assert response.status_code == 200 and len(calls) == 2


def test_igdb_request_gives_up_after_its_attempts():
    import requests

    from oneirodex.utils import igdb_api

    with patch.object(igdb_api, 'safe_request_limited', side_effect=requests.ReadTimeout('slow')) as fake:
        with pytest.raises(requests.ReadTimeout):
            igdb_api._post_igdb_with_retry('https://api.igdb.com/v4/games', {}, 'q', sleep=lambda _s: None)
    assert fake.call_count == igdb_api.IGDB_REQUEST_ATTEMPTS


@pytest.mark.parametrize('platforms, expected', [
    (['PC (Microsoft Windows)'], True),
    (['DOS'], True),
    (['Meta Quest 2'], True),
    (['SteamVR'], True),
    (['Oculus Rift'], True),
    (['Linux', 'Xbox One'], True),
    (['PlayStation 4', 'Nintendo Switch'], False),
    (['Dreamcast'], False),
    ([], False),
])
def test_pc_family_second_pass_keeps_only_pc_family_candidates(platforms, expected):
    from oneirodex.utils.helpers.platforms import candidate_on_pc_family

    assert candidate_on_pc_family({'platforms': [{'name': name} for name in platforms]}) is expected


def test_only_pc_libraries_get_the_second_pass():
    from oneirodex.platform import LibraryPlatform
    from oneirodex.utils.helpers.platforms import is_pc_family_library

    assert is_pc_family_library(LibraryPlatform.PCWIN)
    assert is_pc_family_library(LibraryPlatform.PCDOS)
    assert not is_pc_family_library(LibraryPlatform.PS2)


@pytest.mark.parametrize('folder, candidate', [
    ('Stargaze', 'Stargazer'),
    ('Masterpiece', 'Masterpieced'),
    ('Slime Lab', 'Slime Labs'),
])
def test_a_title_that_only_adds_a_letter_or_two_is_not_a_confident_match(folder, candidate):
    from oneirodex.utils.match_scoring import select_best_match

    _, confidence = select_best_match(folder, [{'name': candidate}])
    assert confidence == 'low'


@pytest.mark.parametrize('folder, candidate', [
    ('Ghostbusters 2016', 'Ghostbusters'),
    ('Alone in the Dark 2008', 'Alone in the Dark'),
])
def test_a_year_in_the_folder_name_is_not_dropped_for_a_confident_match(folder, candidate):
    from oneirodex.utils.match_scoring import select_best_match

    _, confidence = select_best_match(folder, [{'name': candidate}])
    assert confidence == 'low'


@pytest.mark.parametrize('folder, candidate', [
    ('Police Quest 3 The Kindred', 'Police Quest III: The Kindred'),
    ('Gothic 2 Gold Edition', 'Gothic II: Gold Edition'),
])
def test_roman_and_arabic_sequel_numbers_score_alike(folder, candidate):
    from oneirodex.utils.match_scoring import select_best_match

    best, confidence = select_best_match(folder, [{'name': candidate}])
    assert confidence == 'high' and best['name'] == candidate


def test_single_letter_numerals_are_left_alone():
    from oneirodex.utils.match_scoring import normalize_for_score

    assert normalize_for_score('Mega Man X') == 'megamanx'
    assert normalize_for_score('Star Wars X-Wing') == 'starwarsxwing'
    assert normalize_for_score('Final Fantasy VII') == 'finalfantasy7'


@pytest.mark.parametrize('folder, store_title', [
    ('8bit Adventures 2', '8-Bit Adventures 2'),
    ('ForgottenSeas', 'Forgotten Seas'),
    ('Nearmage', 'Near-Mage'),
    ('Roguefp', 'ROGUE-FP'),
    ('Lost Diskettes vol1', 'Lost Diskettes Vol.1'),
    ('ClueCluedo', 'Clue/Cluedo'),
    ('Gothic 2 Gold Edition', 'Gothic II: Gold Edition'),
    ('Final Fantasy X-X2 HD Remaster', 'FINAL FANTASY X/X-2 HD Remaster'),
    ('Rick And Morty Virtual Rickality', 'Rick and Morty: Virtual Rick-ality'),
    ('Kooring Wonderland VR Mecadinos Attack', "Kooring VR Wonderland:Mecadino's Attack"),
])
def test_fuzzy_store_title_matches_spelling_variants(folder, store_title):
    from oneirodex.utils.software_identify import fuzzy_store_title_hit

    hit = fuzzy_store_title_hit(folder, [{'name': store_title, 'steam_type': 'game'}, {'name': 'Something Else Entirely'}])
    assert hit is not None and hit['name'] == store_title


@pytest.mark.parametrize('folder, hits', [
    # a subtitle the folder does not have is a different product
    ("Baldur's Gate 2", [{'name': "Baldur's Gate II: Reflections Of Myth & Valor"}]),
    ('Broken Sword 2', [{'name': 'Broken Sword 2: Original Version'}]),
    # DLC, soundtracks and demos are never the game
    ('Forgotten Seas', [{'name': 'Forgotten Seas Soundtrack'}]),
    ('Forgotten Seas', [{'name': 'Forgotten Seas', 'steam_type': 'dlc'}]),
    ('Forgotten Seas', [{'name': 'Forgotten Seas Demo'}]),
    # two equally close titles: a person decides
    ('Forgotten Sea', [{'name': 'Forgotten Seas'}, {'name': 'Forgotten Seat'}]),
])
def test_fuzzy_store_title_refuses_unsafe_hits(folder, hits):
    from oneirodex.utils.software_identify import fuzzy_store_title_hit

    assert fuzzy_store_title_hit(folder, hits) is None


def test_store_fallback_takes_a_clear_spelling_variant_when_no_title_is_exact():
    from oneirodex.utils import software_identify as si

    steam_hits = [
        {'name': '8-Bit Adventures 2', 'steam_app_id': 1234, 'steam_type': 'game'},
        {'name': '8-Bit Adventures 2 Soundtrack', 'steam_app_id': 1235, 'steam_type': 'music'},
    ]
    with patch.object(si, 'search_steam_games', return_value=steam_hits), \
            patch.object(si, 'search_gog_games', return_value=[]), \
            patch.object(si, 'search_epic_games', return_value=[]):
        candidate = si.resolve_stage_d_store_candidate(
            cleaned_name='8bit Adventures 2', sources=('steam', 'gog', 'epic'),
        )
    assert candidate['name'] == '8-Bit Adventures 2'
    assert candidate['steam_app_id'] == 1234
    assert candidate['match_mode'] == 'fuzzy_title'


def test_store_fallback_still_prefers_an_exact_title_and_refuses_a_subtitled_product():
    from oneirodex.utils import software_identify as si

    with patch.object(si, 'search_steam_games', return_value=[{'name': 'Broken Sword 2: Original Version', 'steam_app_id': 9}]), \
            patch.object(si, 'search_gog_games', return_value=[]), \
            patch.object(si, 'search_epic_games', return_value=[]):
        assert si.resolve_stage_d_store_candidate(cleaned_name='Broken Sword 2', sources=('steam', 'gog', 'epic')) is None


def test_a_demo_with_the_same_name_does_not_make_an_exact_title_ambiguous():
    from oneirodex.utils import software_identify as si

    hits = [
        {'name': 'VoidBound', 'steam_app_id': 1, 'steam_type': 'game'},
        {'name': 'VoidBound', 'steam_app_id': 2, 'steam_type': 'demo'},
    ]
    with patch.object(si, 'search_steam_games', return_value=hits), \
            patch.object(si, 'search_gog_games', return_value=[]), \
            patch.object(si, 'search_epic_games', return_value=[]):
        candidate = si.resolve_stage_d_store_candidate(cleaned_name='Voidbound', sources=('steam', 'gog', 'epic'))
    assert candidate['steam_app_id'] == 1


def test_scan_options_default_to_old_behaviour_and_follow_the_job_row():
    from types import SimpleNamespace

    from oneirodex.utils.services.scan_orchestration import scan_job_match_options

    assert scan_job_match_options(None) == (True, True, False)
    assert scan_job_match_options(SimpleNamespace(
        setting_recheck_matches=None, setting_retry_unmatched=None, setting_propose_only=None,
    )) == (True, True, False)
    assert scan_job_match_options(SimpleNamespace(
        setting_recheck_matches=False, setting_retry_unmatched=False, setting_propose_only=True,
    )) == (False, False, True)


def test_new_folders_only_skips_plain_misses_too(db_session, scan_library):
    from oneirodex.utils.services.scan_orchestration import unmatched_paths_to_skip

    plain = _row(db_session, scan_library)
    ignored = _row(db_session, scan_library, status='Ignore')

    assert unmatched_paths_to_skip(scan_library.uuid) == {ignored.folder_path}
    assert unmatched_paths_to_skip(scan_library.uuid, retry_unmatched=False) == {
        plain.folder_path, ignored.folder_path,
    }


def test_scan_job_rows_store_the_matching_options(db_session, scan_library):
    from oneirodex.utils.scan_queue import create_scan_job_row, find_queued_for_library

    job = create_scan_job_row(
        folder_path='/storage/_pc', library_uuid=scan_library.uuid,
        recheck_matches=False, retry_unmatched=False, propose_only=True,
    )
    db_session.expire_all()
    stored = db_session.get(ScanJob, job.id)
    assert (stored.setting_recheck_matches, stored.setting_retry_unmatched,
            stored.setting_propose_only) == (False, False, True)
    # A queued scan only absorbs a request with the same options.
    assert find_queued_for_library(scan_library.uuid, '/storage/_pc') is None
    assert find_queued_for_library(
        scan_library.uuid, '/storage/_pc',
        recheck_matches=False, retry_unmatched=False, propose_only=True,
    ).id == job.id
