"""Unit tests for Steam/RAWG secondary enrichment and VR detection (no DB)."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from oneirodex.utils.secondary_scrapers import (
    VR_PERSPECTIVE_NAME,
    apply_steam_enrichment_to_game,
    categories_indicate_vr,
    game_indicates_vr,
    normalize_perspective_name,
    perspectives_indicate_vr,
    steam_perspective_names,
)


def test_categories_indicate_vr_vr_only():
    assert categories_indicate_vr(['Single-player', 'VR Only', 'Family Sharing']) is True


def test_categories_indicate_vr_tracked_controller_alone_not_enough():
    assert categories_indicate_vr(['Single-player', 'Tracked Controller Support']) is False


def test_categories_indicate_vr_virtual_reality_phrase():
    assert categories_indicate_vr(['Virtual Reality Support']) is True


def test_categories_indicate_vr_empty():
    assert categories_indicate_vr([]) is False
    assert categories_indicate_vr(None) is False


def test_normalize_perspective_maps_steam_vr_label():
    assert normalize_perspective_name('VR / Virtual Reality') == VR_PERSPECTIVE_NAME
    assert normalize_perspective_name('Virtual Reality') == VR_PERSPECTIVE_NAME
    assert normalize_perspective_name('First person') == 'First person'


def test_steam_perspective_names_includes_vr():
    names = steam_perspective_names(['VR Only', 'Single-player'])
    assert VR_PERSPECTIVE_NAME in names


def test_perspectives_indicate_vr():
    assert perspectives_indicate_vr([VR_PERSPECTIVE_NAME, 'First person']) is True
    assert perspectives_indicate_vr(['First person']) is False
    assert perspectives_indicate_vr([]) is False


def test_game_indicates_vr():
    game = SimpleNamespace(
        player_perspectives=[
            SimpleNamespace(name='First person'),
            SimpleNamespace(name=VR_PERSPECTIVE_NAME),
        ]
    )
    assert game_indicates_vr(game) is True
    assert game_indicates_vr(SimpleNamespace(player_perspectives=[])) is False


def test_game_card_flags_include_is_vr():
    from oneirodex.utils.secondary_scrapers import game_card_flags

    vr_game = SimpleNamespace(
        player_perspectives=[SimpleNamespace(name=VR_PERSPECTIVE_NAME)]
    )
    plain = SimpleNamespace(player_perspectives=[SimpleNamespace(name='Bird view')])
    vr_flags = game_card_flags(vr_game)
    plain_flags = game_card_flags(plain)
    assert vr_flags['is_vr'] is True
    assert plain_flags['is_vr'] is False
    for flags in (vr_flags, plain_flags):
        assert 'item_kind' in flags
        assert 'content_kind' in flags
        assert 'path_missing' in flags
        assert 'path_status' in flags


def test_apply_steam_enrichment_adds_vr_perspective():
    existing = SimpleNamespace(name='First person')
    game = SimpleNamespace(
        name='Archery Kings VR',
        summary='Already has summary',
        player_perspectives=[existing],
        developer=None,
        publisher=None,
    )
    created = []

    def fake_get_or_create(name):
        entity = SimpleNamespace(name=name)
        created.append(entity)
        return entity

    steam_payload = {
        'summary': 'Steam summary ignored when present',
        'player_perspectives': ['VR / Virtual Reality'],
        'is_vr': True,
        'developer': 'Some Dev',
        'publisher': 'Some Pub',
    }

    with patch(
        'oneirodex.utils.secondary_scrapers.fetch_steam_data',
        return_value=steam_payload,
    ):
        result = apply_steam_enrichment_to_game(
            game,
            game.name,
            get_or_create_entity=fake_get_or_create,
        )

    assert result['applied'] is True
    assert result['is_vr'] is True
    assert any(p.name == VR_PERSPECTIVE_NAME for p in game.player_perspectives)
    assert any(p.name == VR_PERSPECTIVE_NAME for p in created)


def test_apply_steam_enrichment_no_steam_data():
    game = SimpleNamespace(name='Unknown', player_perspectives=[], summary=None)

    def unused_factory(*args, **kwargs):
        raise AssertionError('should not create entities without steam data')

    with patch(
        'oneirodex.utils.secondary_scrapers.fetch_steam_data',
        return_value=None,
    ):
        result = apply_steam_enrichment_to_game(
            game,
            game.name,
            get_or_create_entity=unused_factory,
        )
    assert result['applied'] is False
    assert result['is_vr'] is False


@patch('oneirodex.utils.services.game_enrich.apply_enriched_metadata')
@patch('oneirodex.utils.services.game_enrich.fetch_steam_data')
def test_enrich_game_with_steam_delegates(mock_fetch, mock_apply):
    from oneirodex.utils.game_core import enrich_game_with_steam

    game = SimpleNamespace(name='Archery Kings VR', player_perspectives=[], genres=[], game_modes=[])
    mock_fetch.return_value = {
        'summary': 'Bow time',
        'player_perspectives': ['Virtual Reality'],
        'genres': ['Sports', 'Action'],
        'game_modes': ['Single player'],
        'is_vr': True,
        'steam_app_id': 802340,
    }
    mock_apply.return_value = True

    result = enrich_game_with_steam(game)

    assert result['is_vr'] is True
    assert result['applied'] is True
    assert result['genres_added'] == ['Sports', 'Action']
    assert result['game_modes_added'] == ['Single player']
    mock_fetch.assert_called_once_with('Archery Kings VR')
    mock_apply.assert_called_once()
    assert mock_apply.call_args.args[0] is game
    assert mock_apply.call_args.args[1]['player_perspectives'] == ['Virtual Reality']
    assert mock_apply.call_args.args[1]['genres'] == ['Sports', 'Action']
    assert mock_apply.call_args.args[1]['game_modes'] == ['Single player']
    assert callable(mock_apply.call_args.kwargs['perspective_factory'])
    assert callable(mock_apply.call_args.kwargs['genre_factory'])
    assert callable(mock_apply.call_args.kwargs['game_mode_factory'])


@patch('oneirodex.utils.services.game_enrich.apply_enriched_metadata')
@patch('oneirodex.utils.services.game_enrich.fetch_steam_data')
def test_enrich_game_with_steam_applies_genres(mock_fetch, mock_apply):
    """W20-3: Steam enrich must pass genres (and mapped modes) into apply_enriched_metadata."""
    from oneirodex.utils.game_core import enrich_game_with_steam

    game = SimpleNamespace(name='Half-Life', player_perspectives=[], genres=[], game_modes=[])
    mock_fetch.return_value = {
        'summary': 'Gordon',
        'player_perspectives': [],
        'genres': ['Action'],
        'game_modes': ['Single player', 'Multiplayer'],
        'is_vr': False,
        'steam_app_id': 70,
    }
    mock_apply.return_value = True

    result = enrich_game_with_steam(game)

    assert result['applied'] is True
    assert result['genres_added'] == ['Action']
    assert result['game_modes_added'] == ['Single player', 'Multiplayer']
    enriched = mock_apply.call_args.args[1]
    assert enriched['genres'] == ['Action']
    assert enriched['game_modes'] == ['Single player', 'Multiplayer']
    assert enriched['summary'] == 'Gordon'


@patch('oneirodex.utils.services.game_enrich.apply_enriched_metadata')
@patch('oneirodex.utils.services.game_enrich.fetch_steam_data')
def test_enrich_game_with_steam_logs_vr_yes(mock_fetch, mock_apply, caplog):
    caplog.set_level(logging.INFO, logger='oneirodex.utils.services.game_enrich')
    from oneirodex.utils.game_core import enrich_game_with_steam

    game = SimpleNamespace(name='Archery Kings VR', player_perspectives=[])
    mock_fetch.return_value = {
        'summary': 'Bow time',
        'player_perspectives': ['Virtual Reality'],
        'is_vr': True,
        'steam_app_id': 802340,
    }
    mock_apply.return_value = True

    enrich_game_with_steam(game)
    out = caplog.text
    assert "Steam VR: yes" in out
    assert "Archery Kings VR" in out


@patch('oneirodex.utils.services.game_enrich.apply_enriched_metadata')
@patch('oneirodex.utils.services.game_enrich.fetch_steam_data')
def test_enrich_game_with_steam_logs_vr_no_when_skipped(mock_fetch, mock_apply, caplog):
    caplog.set_level(logging.INFO, logger='oneirodex.utils.services.game_enrich')
    from oneirodex.utils.game_core import enrich_game_with_steam

    game = SimpleNamespace(name='Plain Game', player_perspectives=[])
    mock_fetch.return_value = None

    enrich_game_with_steam(game)
    out = caplog.text
    assert "Steam VR: no" in out
    assert "no_steam_data" in out
    mock_apply.assert_not_called()


@patch('oneirodex.utils.services.game_enrich.apply_enriched_metadata')
@patch('oneirodex.utils.services.game_enrich.fetch_steam_data')
def test_enrich_game_with_steam_still_enriches_an_already_vr_game(
    mock_fetch, mock_apply, caplog,
):
    """Being flagged VR must not skip the rest of the enrichment pass.

    This used to short-circuit on `already_vr` and return without fetching,
    which also skipped the summary / genre / game-mode backfill — VR detection
    is only one part of what this pass does. The flag stays true either way.
    """
    caplog.set_level(logging.INFO, logger='oneirodex.utils.services.game_enrich')
    from oneirodex.utils.game_core import enrich_game_with_steam

    mock_fetch.return_value = {
        'is_vr': True,
        'summary': 'Draw the bow.',
        'genres': ['Sports'],
        'player_perspectives': [],
        'game_modes': [],
        'developer': 'Studio',
        'publisher': 'Studio',
        'release_date': '1 Jan, 2020',
        'cover_url': None,
        'steam_app_id': 12345,
    }

    game = SimpleNamespace(
        name='Archery Kings VR',
        player_perspectives=[SimpleNamespace(name=VR_PERSPECTIVE_NAME)],
        genres=[],
    )
    result = enrich_game_with_steam(game)

    assert result['is_vr'] is True
    mock_fetch.assert_called_once()
    assert 'Steam VR: yes' in caplog.text


@patch('oneirodex.utils.services.game_enrich.apply_enriched_metadata')
@patch('oneirodex.utils.services.game_enrich.fetch_steam_data')
def test_enrich_game_with_steam_reports_rollback(mock_fetch, mock_apply, caplog):
    """When the savepoint rolls back, the caller must see applied=False and no perspectives."""
    caplog.set_level(logging.INFO, logger='oneirodex.utils.services.game_enrich')
    from oneirodex.utils.game_core import enrich_game_with_steam

    game = SimpleNamespace(name='Archery Kings VR', player_perspectives=[])
    mock_fetch.return_value = {
        'summary': 'Bow time',
        'player_perspectives': ['Virtual Reality'],
        'is_vr': True,
        'steam_app_id': 802340,
    }
    mock_apply.return_value = False

    result = enrich_game_with_steam(game)

    assert result['applied'] is False
    assert result['perspectives_added'] == []
    assert result['reason'] == 'enrichment_savepoint_rollback'
    out = caplog.text
    assert "enrichment_savepoint_rollback" in out


def test_fetch_steam_data_prefers_exact_name_match():
    search = MagicMock(status_code=200)
    search.json.return_value = {
        'items': [
            {'id': 1, 'name': 'Archery Kings'},
            {'id': 802340, 'name': 'Archery Kings VR'},
        ]
    }
    details = MagicMock(status_code=200)
    details.json.return_value = {
        '802340': {
            'data': {
                'name': 'Archery Kings VR',
                'short_description': 'Bow time',
                'categories': [{'description': 'VR Only'}],
                'genres': [],
                'developers': [],
                'publishers': [],
                'release_date': {'date': '2018'},
                'header_image': 'http://example/cover.jpg',
            }
        }
    }

    with patch(
        'oneirodex.utils.secondary_scrapers.request_with_backoff',
        side_effect=[search, details],
    ) as mock_request:
        from oneirodex.utils.secondary_scrapers import fetch_steam_data

        data = fetch_steam_data('Archery Kings VR')

    assert data['steam_app_id'] == 802340
    assert data['is_vr'] is True
    details_url = mock_request.call_args_list[1][0][0]
    assert '802340' in details_url
    assert mock_request.call_args_list[0][1]['host_key'] == 'steam'
    assert mock_request.call_args_list[1][1]['host_key'] == 'steam'


def test_fetch_steam_data_sets_is_vr_for_archery_kings_style_payload():
    search = MagicMock(status_code=200)
    search.json.return_value = {'items': [{'id': 802340, 'name': 'Archery Kings VR'}]}
    details = MagicMock(status_code=200)
    details.json.return_value = {
        '802340': {
            'data': {
                'name': 'Archery Kings VR',
                'short_description': 'Bow time',
                'categories': [
                    {'description': 'Single-player'},
                    {'description': 'VR Only'},
                ],
                'genres': [{'description': 'Sports'}],
                'developers': ['Dev'],
                'publishers': ['Pub'],
                'release_date': {'date': '2018'},
                'header_image': 'http://example/cover.jpg',
            }
        }
    }

    with patch(
        'oneirodex.utils.secondary_scrapers.request_with_backoff',
        side_effect=[search, details],
    ):
        from oneirodex.utils.secondary_scrapers import fetch_steam_data

        data = fetch_steam_data('Archery Kings VR')

    assert data is not None
    assert data['is_vr'] is True
    assert data['genres'] == ['Sports']
    assert 'Single player' in data['game_modes']
    assert VR_PERSPECTIVE_NAME in [
        normalize_perspective_name(n) for n in data['player_perspectives']
    ]


@patch('oneirodex.utils.secondary_scrapers.request_with_backoff')
def test_fetch_steam_data_returns_none_on_http_failure(mock_req):
    mock_req.return_value = None
    from oneirodex.utils.secondary_scrapers import fetch_steam_data

    assert fetch_steam_data('Some Game') is None


@patch('oneirodex.utils.secondary_scrapers.request_with_backoff')
def test_fetch_rawg_data_returns_none_on_http_failure(mock_req):
    mock_req.return_value = None
    from oneirodex.utils.secondary_scrapers import fetch_rawg_data

    assert fetch_rawg_data('Some Game') is None


def test_fetch_rawg_data_uses_backoff_with_rawg_host_key():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        'results': [{'description_raw': 'Desc', 'rating': 4.2, 'genres': [], 'released': '2019', 'background_image': None}]
    }

    with patch(
        'oneirodex.utils.secondary_scrapers.request_with_backoff',
        return_value=resp,
    ) as mock_request:
        from oneirodex.utils.secondary_scrapers import fetch_rawg_data

        data = fetch_rawg_data('Some Game')

    assert data['summary'] == 'Desc'
    assert mock_request.call_args[1]['host_key'] == 'rawg'
