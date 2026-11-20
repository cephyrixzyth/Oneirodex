"""W20-5a Stage D — IGDB miss → Steam/GOG exact|App-ID custom Game (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from oneirodex.models import Game, GameURL, Library
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.software_identify import (
    CUSTOM_IGDB_BASE,
    exact_title_hits,
    igdb_retry_title_from_store,
    resolve_stage_d_store_candidate,
    scrub_stage_d_payload,
    try_stage_d_store_identify,
    upsert_stage_d_custom_game,
)

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- store cascade invoked during scan.


@pytest.fixture
def sample_library(db_session):
    lib = Library(
        name=f'StageD_Lib_{uuid4().hex[:8]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(lib)
    db_session.flush()
    return lib


def test_exact_title_hits_casefold_only():
    hits = [
        {'name': 'Hades', 'steam_app_id': 1},
        {'name': 'Hades II', 'steam_app_id': 2},
        {'name': 'hades', 'steam_app_id': 3},
    ]
    exact = exact_title_hits('HADES', hits)
    assert {h['steam_app_id'] for h in exact} == {1, 3}


def test_scrub_drops_install_download_fields():
    cleaned = scrub_stage_d_payload({
        'name': 'Title',
        'url': 'https://store.steampowered.com/app/1/',
        'download_url': 'https://evil.example/dl',
        'install_url': 'steam://install/1',
        'magnet': 'magnet:?xt=urn:btih:abc',
    })
    assert 'download_url' not in cleaned
    assert 'install_url' not in cleaned
    assert 'magnet' not in cleaned
    assert cleaned['url'].startswith('https://store.steampowered.com/')


def test_app_id_path_resolves_custom_candidate():
    details = {
        'steam_app_id': 81735,
        'name': 'Abandon Ship',
        'steam_type': 'game',
        'header_image': 'https://cdn.example/cover.jpg',
        'short_description': 'A naval adventure.',
    }
    with patch(
        'oneirodex.utils.steam_lookup.fetch_steam_app_details',
        return_value=details,
    ):
        hit = resolve_stage_d_store_candidate(
            cleaned_name='Abandon Ship',
            steam_app_id=81735,
        )
    assert hit is not None
    assert hit['match_mode'] == 'app_id'
    assert hit['steam_app_id'] == 81735
    assert hit['name'] == 'Abandon Ship'
    assert hit['summary'] == 'A naval adventure.'
    assert 'download_url' not in hit


def test_app_id_details_miss_falls_through_to_exact_steam():
    """Wrong-namespace paren digits must not stamp a bogus steam_app_id."""
    steam_hits = [{
        'source': 'steam',
        'id': 1675830,
        'name': '1000xRESIST',
        'steam_app_id': 1675830,
        'steam_type': 'game',
        'item_kind': 'game',
    }]
    with patch(
        'oneirodex.utils.steam_lookup.fetch_steam_app_details',
        return_value=None,
    ), patch(
        'oneirodex.utils.software_identify.search_steam_games',
        return_value=steam_hits,
    ) as mock_steam, patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[],
    ):
        # Exact title still casefold-strict — use store-exact cleaned name.
        hit = resolve_stage_d_store_candidate(
            cleaned_name='1000xRESIST',
            steam_app_id=77125,
        )
        assert mock_steam.called
    assert hit is not None
    assert hit['match_mode'] == 'exact_title'
    assert hit['steam_app_id'] == 1675830


def test_app_id_details_miss_no_exact_returns_none():
    with patch(
        'oneirodex.utils.steam_lookup.fetch_steam_app_details',
        return_value=None,
    ), patch(
        'oneirodex.utils.software_identify.search_steam_games',
        return_value=[{'name': 'Other', 'steam_app_id': 1}],
    ), patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[],
    ), patch(
        'oneirodex.utils.software_identify.search_epic_games',
        return_value=[],
    ):
        hit = resolve_stage_d_store_candidate(
            cleaned_name='1000x Resist',
            steam_app_id=77125,
        )
    assert hit is None


def test_app_id_title_mismatch_falls_through():
    details = {
        'steam_app_id': 77125,
        'name': 'Unrelated Steam Title',
        'steam_type': 'game',
        'header_image': None,
        'short_description': None,
    }
    with patch(
        'oneirodex.utils.steam_lookup.fetch_steam_app_details',
        return_value=details,
    ), patch(
        'oneirodex.utils.software_identify.search_steam_games',
        return_value=[],
    ), patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[{
            'source': 'gog',
            'id': 99,
            'name': 'Broken Sword 2',
            'url': 'https://www.gog.com/game/broken_sword_2',
            'gog_id': 99,
        }],
    ), patch(
        'oneirodex.utils.software_identify.search_epic_games',
        return_value=[],
    ):
        hit = resolve_stage_d_store_candidate(
            cleaned_name='Broken Sword 2',
            steam_app_id=77125,
        )
    assert hit is not None
    assert hit['source'] == 'gog'
    assert hit['gog_id'] == 99


def test_app_id_remaster_subtitle_corroborates():
    details = {
        'steam_app_id': 33600,
        'name': 'Broken Sword 2 - the Smoking Mirror: Remastered',
        'steam_type': 'game',
        'header_image': None,
        'short_description': 'Adventure',
    }
    with patch(
        'oneirodex.utils.steam_lookup.fetch_steam_app_details',
        return_value=details,
    ), patch(
        'oneirodex.utils.software_identify.search_steam_games',
    ) as mock_steam:
        hit = resolve_stage_d_store_candidate(
            cleaned_name='Broken Sword 2',
            steam_app_id=33600,
        )
        mock_steam.assert_not_called()
    assert hit is not None
    assert hit['match_mode'] == 'app_id'
    assert hit['steam_app_id'] == 33600
    assert 'Smoking Mirror' in hit['name']


def test_igdb_miss_steam_exact_title(monkeypatch):
    steam_hits = [
        {
            'source': 'steam',
            'id': 570,
            'name': 'Dota 2',
            'url': 'https://store.steampowered.com/app/570/',
            'cover_url': None,
            'summary': None,
            'steam_app_id': 570,
            'steam_type': 'game',
            'item_kind': 'game',
            'is_software': False,
        },
        {
            'source': 'steam',
            'id': 999,
            'name': 'Dota 2 Demo',
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
        return_value=steam_hits,
    ) as mock_steam, patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[],
    ) as mock_gog:
        hit = resolve_stage_d_store_candidate(cleaned_name='Dota 2')
        assert mock_steam.called
        mock_gog.assert_not_called()
    assert hit is not None
    assert hit['match_mode'] == 'exact_title'
    assert hit['steam_app_id'] == 570


def test_ambiguous_steam_exact_no_auto():
    steam_hits = [
        {'name': 'Keeper', 'steam_app_id': 1, 'steam_type': 'game', 'item_kind': 'game'},
        {'name': 'keeper', 'steam_app_id': 2, 'steam_type': 'game', 'item_kind': 'game'},
    ]
    with patch(
        'oneirodex.utils.software_identify.search_steam_games',
        return_value=steam_hits,
    ), patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[{'name': 'Keeper', 'gog_id': 9}],
    ):
        hit = resolve_stage_d_store_candidate(cleaned_name='Keeper')
    assert hit is None


def test_gog_exact_when_steam_misses():
    with patch(
        'oneirodex.utils.software_identify.search_steam_games',
        return_value=[{'name': 'Other Title', 'steam_app_id': 1}],
    ), patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[{
            'source': 'gog',
            'id': 1207658691,
            'name': 'The Witcher 3',
            'url': 'https://www.gog.com/game/the_witcher_3',
            'cover_url': 'https://cdn.example/gog.jpg',
            'summary': None,
            'gog_id': 1207658691,
            'slug': 'the_witcher_3',
            'download_url': 'https://should.not/persist',
        }],
    ), patch(
        'oneirodex.utils.software_identify.search_epic_games',
    ) as mock_epic:
        hit = resolve_stage_d_store_candidate(cleaned_name='The Witcher 3')
        mock_epic.assert_not_called()
    assert hit is not None
    assert hit['source'] == 'gog'
    assert hit['gog_id'] == 1207658691
    assert 'download_url' not in hit


def test_epic_exact_when_steam_and_gog_miss():
    with patch(
        'oneirodex.utils.software_identify.search_steam_games',
        return_value=[],
    ), patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[],
    ), patch(
        'oneirodex.utils.software_identify.search_epic_games',
        return_value=[{
            'source': 'epic',
            'id': 'fortnite',
            'name': 'Fortnite',
            'url': 'https://store.epicgames.com/en-US/p/fortnite',
            'slug': 'fortnite',
            'download_url': 'https://should.not/persist',
        }],
    ):
        hit = resolve_stage_d_store_candidate(cleaned_name='Fortnite')
    assert hit is not None
    assert hit['source'] == 'epic'
    assert hit['name'] == 'Fortnite'
    assert 'download_url' not in hit
    assert hit['url'].startswith('https://store.epicgames.com/')


def test_sources_toggle_skips_steam():
    with patch(
        'oneirodex.utils.software_identify.search_steam_games',
    ) as mock_steam, patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[{
            'source': 'gog',
            'id': 1,
            'name': 'Celeste',
            'url': 'https://www.gog.com/game/celeste',
            'gog_id': 1,
        }],
    ), patch(
        'oneirodex.utils.software_identify.search_epic_games',
        return_value=[],
    ):
        hit = resolve_stage_d_store_candidate(
            cleaned_name='Celeste',
            sources=('gog', 'epic'),
        )
        mock_steam.assert_not_called()
    assert hit is not None
    assert hit['source'] == 'gog'


def test_igdb_retry_title_from_store_skips_already_tried():
    assert igdb_retry_title_from_store({'name': 'Hades'}, ['hades', 'HADES']) is None
    assert igdb_retry_title_from_store({'name': 'Hades II'}, ['Hades']) == 'Hades II'
    assert igdb_retry_title_from_store(None, ['x']) is None


def test_commit_epic_exact_registers_store_url(app, db_session, sample_library):
    path = f'/test/stage-d/Epic-{uuid4().hex[:6]}'
    candidate = {
        'source': 'epic',
        'name': 'Fortnite',
        'url': 'https://store.epicgames.com/en-US/p/fortnite',
        'item_kind': 'game',
        'match_mode': 'exact_title',
        'install_url': 'https://nope.example/install',
    }
    game = upsert_stage_d_custom_game(
        candidate=candidate,
        full_disk_path=path,
        library_uuid=sample_library.uuid,
    )
    db_session.flush()
    urls = db_session.query(GameURL).filter_by(game_uuid=game.uuid).all()
    assert len(urls) == 1
    assert urls[0].url_type == 'epic'
    assert 'install' not in urls[0].url


def test_software_item_kind_from_steam_type():
    details = {
        'steam_app_id': 1044340,
        'name': '3DSen VR',
        'steam_type': 'software',
        'header_image': None,
        'short_description': 'NES emulator in VR',
    }
    with patch(
        'oneirodex.utils.steam_lookup.fetch_steam_app_details',
        return_value=details,
    ):
        hit = resolve_stage_d_store_candidate(
            cleaned_name='3DSen',
            steam_app_id=1044340,
        )
    assert hit['item_kind'] == 'emulator'
    assert hit['steam_type'] == 'software'


def test_commit_app_id_creates_custom_game(app, db_session, sample_library):
    path = f'/test/stage-d/Abandon Ship ({uuid4().hex[:6]})'
    candidate = {
        'source': 'steam',
        'name': 'Abandon Ship',
        'summary': 'Naval',
        'cover_url': 'https://cdn.example/c.jpg',
        'steam_app_id': 81735,
        'item_kind': 'game',
        'identify_path': 'stage_d',
        'match_mode': 'app_id',
        'download_url': 'https://nope.example/dl',
    }
    game = upsert_stage_d_custom_game(
        candidate=candidate,
        full_disk_path=path,
        library_uuid=sample_library.uuid,
    )
    db_session.flush()

    assert game.igdb_id >= CUSTOM_IGDB_BASE
    assert game.steam_app_id == 81735
    assert game.name == 'Abandon Ship'
    assert game.summary == 'Naval'
    assert game.steam_url == 'https://store.steampowered.com/app/81735/'
    assert game.item_kind == 'game'
    # Must not persist install/download queue fields on the model.
    assert not hasattr(game, 'download_url') or getattr(game, 'download_url', None) is None


def test_commit_gog_exact_registers_store_url_only(app, db_session, sample_library):
    path = f'/test/stage-d/Witcher3-{uuid4().hex[:6]}'
    candidate = {
        'source': 'gog',
        'name': 'The Witcher 3',
        'gog_id': 1207658691,
        'url': 'https://www.gog.com/game/the_witcher_3',
        'cover_url': None,
        'item_kind': 'game',
        'match_mode': 'exact_title',
        'install_url': 'https://nope.example/install',
    }
    game = upsert_stage_d_custom_game(
        candidate=candidate,
        full_disk_path=path,
        library_uuid=sample_library.uuid,
    )
    db_session.flush()

    assert game.igdb_id >= CUSTOM_IGDB_BASE
    assert game.steam_app_id is None
    urls = db_session.query(GameURL).filter_by(game_uuid=game.uuid).all()
    assert len(urls) == 1
    assert urls[0].url_type == 'gog'
    assert urls[0].url == 'https://www.gog.com/game/the_witcher_3'
    assert 'install' not in urls[0].url


def test_try_stage_d_end_to_end_mocked(app, db_session, sample_library):
    path = f'/test/stage-d/Barony-{uuid4().hex[:6]}'
    details = {
        'steam_app_id': 89881,
        'name': 'Barony',
        'steam_type': 'game',
        'header_image': None,
        'short_description': 'Roguelike',
    }
    with patch(
        'oneirodex.utils.steam_lookup.fetch_steam_app_details',
        return_value=details,
    ), patch(
        'oneirodex.utils.software_identify.search_steam_games',
    ) as mock_steam, patch(
        'oneirodex.utils.software_identify.search_gog_games',
    ) as mock_gog:
        game = try_stage_d_store_identify(
            raw_label='barony (89881)',
            cleaned_name='Barony',
            full_disk_path=path,
            library_uuid=sample_library.uuid,
            steam_app_id=89881,
        )
        mock_steam.assert_not_called()
        mock_gog.assert_not_called()

    assert game is not None
    assert game.igdb_id >= CUSTOM_IGDB_BASE
    assert game.steam_app_id == 89881
    assert game.name == 'Barony'


def test_retrieve_and_save_game_stage_d_on_igdb_miss(
    app, db_session, sample_library,
):
    """IGDB empty → Stage D App-ID custom Game; Unmatched not required."""
    from oneirodex.utils.game_core import retrieve_and_save_game

    # A5 reads a Steam App ID only when the label names it; a bare (81735) is a
    # catalogue number.
    path = f'/tmp/oneirodex-stage-d-test/Abandon Ship (Steam 81735)'
    details = {
        'steam_app_id': 81735,
        'name': 'Abandon Ship',
        'steam_type': 'game',
        'header_image': 'https://cdn.example/a.jpg',
        'short_description': 'Ship',
    }

    with patch(
        'oneirodex.utils.services.scan_identify.search_igdb_for_game',
        return_value=[],
    ), patch(
        'oneirodex.utils.services.scan_identify.fetch_steam_title_by_app_id',
        return_value='Abandon Ship',
    ), patch(
        'oneirodex.utils.steam_lookup.fetch_steam_app_details',
        return_value=details,
    ), patch(
        'oneirodex.utils.services.scan_identify.notify_admins_new_game',
    ), patch(
        'oneirodex.utils.software_identify.search_steam_games',
        return_value=[],
    ), patch(
        'oneirodex.utils.software_identify.search_gog_games',
        return_value=[],
    ), patch(
        'oneirodex.utils.software_identify.search_epic_games',
        return_value=[],
    ), patch(
        'oneirodex.utils.services.scan_identify.get_folder_size_in_bytes_updates',
        return_value=0,
    ):
        result = retrieve_and_save_game(
            'Abandon Ship',
            path,
            library_uuid=sample_library.uuid,
            settings={
                'use_local_metadata': False,
                'write_local_metadata': False,
                'use_local_images': False,
                'local_metadata_filename': 'oneirodex.json',
                'propose_only_scan': False,
            },
        )

    assert result is not None
    assert result.igdb_id >= CUSTOM_IGDB_BASE
    assert result.steam_app_id == 81735
    assert result.name == 'Abandon Ship'


def test_retrieve_skips_stage_d_when_propose_only(
    app, db_session, sample_library,
):
    from oneirodex.utils.game_core import retrieve_and_save_game

    path = f'/test/stage-d/ProposeOnly-{uuid4().hex[:4]}'

    with patch(
        'oneirodex.utils.services.scan_identify.search_igdb_for_game',
        return_value=[],
    ), patch(
        'oneirodex.utils.software_identify.try_stage_d_store_identify',
    ) as mock_stage_d, patch(
        'oneirodex.utils.software_identify.enrich_proposal_with_software',
        side_effect=lambda p, *_a, **_k: p,
    ), patch(
        'oneirodex.utils.services.scan_identify.write_match_proposal',
        return_value=True,
    ):
        result = retrieve_and_save_game(
            'Some Title',
            path,
            library_uuid=sample_library.uuid,
            settings={
                'use_local_metadata': False,
                'write_local_metadata': False,
                'use_local_images': False,
                'local_metadata_filename': 'oneirodex.json',
                'propose_only_scan': True,
            },
        )
    assert result is None
    mock_stage_d.assert_not_called()
