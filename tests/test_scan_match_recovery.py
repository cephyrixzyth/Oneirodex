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
