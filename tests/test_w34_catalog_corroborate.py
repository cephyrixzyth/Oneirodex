"""W34-MATCH — four-source identify on IGDB hits (mocked HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from oneirodex.models import Library, UnmatchedFolder
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.match_proposal import (
    MATCH_REASON_CATALOG_DISAGREEMENT,
    format_why_unmatched,
)
from oneirodex.utils.software_identify import (
    apply_catalog_identity_to_game,
    corroborate_igdb_with_catalogs,
    titles_identify_agree,
    _identity_key,
)


@pytest.fixture
def sample_library(db_session):
    lib = Library(
        name=f'W34_Lib_{uuid4().hex[:8]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(lib)
    db_session.flush()
    return lib


def test_identity_key_punctuation_tolerant():
    assert _identity_key("Half-Life 2") == _identity_key("Half Life 2")
    assert titles_identify_agree("DOOM", "Doom")
    assert not titles_identify_agree("Doom", "Doom Eternal")
    assert not titles_identify_agree("Doom", "Doom 3")


def test_format_why_unmatched_catalog_disagreement():
    text = format_why_unmatched(match_reason=MATCH_REASON_CATALOG_DISAGREEMENT)
    assert 'Steam' in text
    assert 'MobyGames' in text


@patch('oneirodex.utils.software_identify.gather_catalog_identify_signals')
def test_corroborate_disagree_when_folder_exact_is_other_product(mock_gather):
    mock_gather.return_value = {
        'rows': [{
            'source': 'mobygames',
            'name': 'Doom',
            'match_mode': 'moby_exact',
            'url': 'https://www.mobygames.com/game/15/doom/',
        }],
        'skipped': [],
        'stage_e': {},
    }
    result = corroborate_igdb_with_catalogs(
        igdb_name='Doom 3',
        cleaned_name='Doom',
        library_platform='PCWIN',
    )
    assert result['verdict'] == 'disagree'
    assert result['disagreed'][0]['name'] == 'Doom'


@patch('oneirodex.utils.software_identify.gather_catalog_identify_signals')
def test_corroborate_agree_when_titles_match(mock_gather):
    mock_gather.return_value = {
        'rows': [{
            'source': 'steam',
            'name': 'Celeste',
            'match_mode': 'exact_title',
            'steam_app_id': 504230,
            'url': 'https://store.steampowered.com/app/504230/',
        }],
        'skipped': [],
        'stage_e': {},
    }
    result = corroborate_igdb_with_catalogs(
        igdb_name='Celeste',
        cleaned_name='Celeste',
        library_platform='PCWIN',
    )
    assert result['verdict'] == 'agree'
    assert result['agreed'][0]['steam_app_id'] == 504230


@patch('oneirodex.utils.software_identify.gather_catalog_identify_signals')
def test_corroborate_remaster_subtitle_is_noise_not_veto(mock_gather):
    mock_gather.return_value = {
        'rows': [{
            'source': 'steam',
            'name': 'Broken Sword 2 - the Smoking Mirror: Remastered',
            'match_mode': 'app_id',
            'steam_app_id': 33600,
        }],
        'skipped': [],
        'stage_e': {},
    }
    result = corroborate_igdb_with_catalogs(
        igdb_name='Broken Sword 2: The Smoking Mirror',
        cleaned_name='Broken Sword 2',
        library_platform='PCWIN',
    )
    assert result['verdict'] == 'no_signal'
    assert result['disagreed'] == []


def test_apply_catalog_identity_stamps_steam_and_moby(monkeypatch):
    from types import SimpleNamespace
    mock_session = MagicMock()
    monkeypatch.setattr(
        'oneirodex.utils.software_identify.db',
        SimpleNamespace(session=mock_session),
    )
    game = MagicMock()
    game.uuid = 'game-uuid'
    game.steam_app_id = None
    game.steam_url = None
    game.urls = []
    apply_catalog_identity_to_game(game, [
        {
            'source': 'steam',
            'name': 'Celeste',
            'steam_app_id': 504230,
        },
        {
            'source': 'mobygames',
            'name': 'Celeste',
            'url': 'https://www.mobygames.com/game/celeste/',
        },
    ])
    assert game.steam_app_id == 504230
    assert '504230' in game.steam_url
    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.url_type == 'mobygames'


@patch('oneirodex.utils.services.scan_identify.select_best_match')
@patch(
    'oneirodex.utils.services.scan_identify.corroborate_igdb_with_catalogs',
)
@patch('oneirodex.utils.services.scan_identify.notify_admins_new_game')
@patch('oneirodex.utils.services.scan_identify.smart_process_images_for_game')
@patch('oneirodex.utils.services.scan_identify.get_folder_size_in_bytes_updates', return_value=0)
@patch('oneirodex.utils.services.scan_identify.read_first_nfo_content', return_value=None)
@patch('oneirodex.utils.clients.igdb.make_igdb_api_request')
@patch('oneirodex.utils.services.scan_identify.create_game_instance')
def test_retrieve_catalog_disagreement_goes_to_review(
    mock_create,
    mock_api,
    mock_nfo,
    mock_size,
    mock_images,
    mock_notify,
    mock_corroborate,
    mock_best,
    app,
    db_session,
    sample_library,
    tmp_path,
):
    from oneirodex.utils.game_core import retrieve_and_save_game

    folder = tmp_path / 'Test Game'
    folder.mkdir()
    selected = {'id': 4242, 'name': 'Test Game'}
    mock_api.return_value = [selected]
    mock_best.return_value = (selected, 'high')
    mock_corroborate.return_value = {
        'verdict': 'disagree',
        'agreed': [],
        'disagreed': [{
            'source': 'mobygames',
            'name': 'Test Game: Director\'s Cut',
            'match_mode': 'moby_exact',
            'url': 'https://www.mobygames.com/game/1/test/',
        }],
        'skipped': [],
    }

    db_session.commit()
    with app.app_context():
        result = retrieve_and_save_game(
            'Test Game',
            str(folder),
            library_uuid=sample_library.uuid,
            settings={
                'use_local_metadata': False,
                'write_local_metadata': False,
                'use_local_images': False,
                'local_metadata_filename': 'oneirodex.json',
                'propose_only_scan': False,
            },
        )

    assert result is None
    mock_create.assert_not_called()
    row = db_session.query(UnmatchedFolder).filter_by(
        folder_path=str(folder),
    ).one_or_none()
    assert row is not None
    assert row.match_reason == MATCH_REASON_CATALOG_DISAGREEMENT
    sidecar = folder / 'oneirodex.proposal.json'
    assert sidecar.is_file()
    body = sidecar.read_text(encoding='utf-8')
    assert 'catalog_disagreement' in body
    assert 'review' in body
