"""Tests for Meta/Quest + expanded identify metadata search (mocked HTTP)."""

from __future__ import annotations

import traceback
from unittest.mock import MagicMock, patch

import pytest
import requests

from oneirodex.utils.providers import reset_provider_cache
from oneirodex.utils.providers.giantbomb import GiantBombProvider
from oneirodex.utils.providers.meta_quest import (
    META_QUEST_PLATFORM_IDS,
    MetaQuestProvider,
    get_meta_quest_api_mode,
    search_meta_quest_games,
)
from oneirodex.utils.secondary_scrapers import (
    search_epic_games,
    search_giantbomb_games,
    search_itch_games,
    search_mobygames_games,
    search_thegamesdb_games,
)


@pytest.fixture(autouse=True)
def _reset_providers():
    reset_provider_cache()
    yield
    reset_provider_cache()


@patch('oneirodex.utils.providers.meta_quest.make_igdb_api_request')
@patch('oneirodex.utils.providers.meta_quest.igdb_credentials_configured', return_value=True)
def test_search_meta_quest_games_filters_platforms(mock_creds, mock_igdb):
    mock_igdb.return_value = [
        {
            'id': 99,
            'name': 'Beat Saber',
            'slug': 'beat-saber',
            'summary': 'VR rhythm',
            'cover': {'image_id': 'abc123'},
            'platforms': [{'name': 'Meta Quest 2'}],
            'first_release_date': 1530403200,
        }
    ]
    results = search_meta_quest_games('Beat Saber', limit=5)
    assert len(results) == 1
    assert results[0]['source'] == 'meta_quest'
    assert results[0]['name'] == 'Beat Saber'
    assert results[0]['ownership_only'] is True
    assert results[0]['is_vr'] is True
    assert results[0]['meta_quest_id'] == '99'
    assert 'download' not in (results[0].get('note') or '').lower() or 'never downloads' in results[0]['note'].lower()
    assert 'install' not in results[0]
    query = mock_igdb.call_args[0][1]
    for pid in META_QUEST_PLATFORM_IDS:
        assert str(pid) in query


@patch('oneirodex.utils.providers.meta_quest.igdb_credentials_configured', return_value=False)
def test_search_meta_quest_without_igdb_returns_empty(mock_creds):
    assert search_meta_quest_games('Anything') == []


@patch.dict('os.environ', {'META_QUEST_API_MODE': 'csv_only'}, clear=False)
def test_search_meta_quest_csv_only_returns_empty():
    assert get_meta_quest_api_mode() == 'csv_only'
    assert search_meta_quest_games('Beat Saber') == []


@patch.dict('os.environ', {'META_QUEST_API_MODE': 'unofficial_graphql'}, clear=False)
def test_unofficial_graphql_off_by_default_returns_empty():
    assert get_meta_quest_api_mode() == 'unofficial_graphql'
    assert search_meta_quest_games('Beat Saber') == []


@patch('oneirodex.utils.providers.meta_quest.make_igdb_api_request')
@patch('oneirodex.utils.providers.meta_quest.igdb_credentials_configured', return_value=True)
def test_meta_quest_provider_search_covers(mock_creds, mock_igdb):
    mock_igdb.return_value = [
        {
            'id': 1,
            'name': 'Quest Title',
            'slug': 'quest-title',
            'cover': {'image_id': 'img1'},
            'platforms': [{'name': 'Oculus Quest'}],
        }
    ]
    provider = MetaQuestProvider()
    assert provider.is_enabled() is True
    covers = provider.search_covers('Quest Title', limit=5)
    assert len(covers) == 1
    assert covers[0].url.endswith('img1.jpg')


@patch('oneirodex.utils.secondary_scrapers.request_with_backoff')
def test_search_epic_games_mocked(mock_req):
    resp = MagicMock()
    resp.content = b'{}'
    resp.json.return_value = {
        'elements': [
            {
                'id': 'offer1',
                'title': 'Fortnite',
                'urlSlug': 'fortnite',
                'keyImages': [{'type': 'Thumbnail', 'url': 'https://cdn.example/cover.jpg'}],
            }
        ]
    }
    mock_req.return_value = resp
    results = search_epic_games('Fortnite', limit=5)
    assert len(results) == 1
    assert results[0]['source'] == 'epic'
    assert results[0]['ownership_only'] is True


@patch('oneirodex.utils.secondary_scrapers.request_with_backoff')
def test_search_itch_games_mocked(mock_req):
    resp = MagicMock()
    resp.content = b'{}'
    resp.json.return_value = {
        'games': [
            {
                'id': 42,
                'title': 'Celeste',
                'url': 'https://example.itch.io/celeste',
                'cover': 'https://cdn.example/celeste.png',
            }
        ]
    }
    mock_req.return_value = resp
    results = search_itch_games('Celeste', limit=5)
    assert len(results) == 1
    assert results[0]['source'] == 'itch'
    assert results[0]['id'] == 42


@patch('oneirodex.utils.providers.giantbomb.get_giantbomb_api_key', return_value='gb-key')
@patch('oneirodex.utils.secondary_scrapers.request_with_backoff')
def test_search_giantbomb_games_mocked(mock_req, mock_key):
    resp = MagicMock()
    resp.content = b'{}'
    resp.json.return_value = {
        'results': [
            {
                'id': 7,
                'name': 'Doom',
                'site_detail_url': 'https://www.giantbomb.com/doom/3030-7/',
                'deck': 'Classic shooter',
                'image': {'super_url': 'https://cdn.example/doom.jpg'},
            }
        ]
    }
    mock_req.return_value = resp
    results = search_giantbomb_games('Doom', limit=5)
    assert len(results) == 1
    assert results[0]['source'] == 'giantbomb'


@patch('oneirodex.utils.providers.giantbomb.get_giantbomb_api_key', return_value='gb-secret-key')
@patch('oneirodex.utils.providers.giantbomb.safe_request')
def test_giantbomb_transport_error_does_not_preserve_key_in_exception(mock_request, _mock_key):
    mock_request.side_effect = requests.ConnectionError(
        'connection failed for https://www.giantbomb.com/api/search/?api_key=gb-secret-key'
    )

    with pytest.raises(RuntimeError, match='GiantBomb search request failed') as raised:
        GiantBombProvider().search_covers('Doom')

    assert 'gb-secret-key' not in str(raised.value)
    assert raised.value.__suppress_context__ is True
    assert 'gb-secret-key' not in ''.join(traceback.format_exception(raised.value))


@patch('oneirodex.utils.providers.mobygames.get_mobygames_api_key', return_value=None)
def test_search_mobygames_without_key_returns_empty(mock_key):
    assert search_mobygames_games('Doom') == []
    mock_key.assert_called()


@patch('oneirodex.utils.providers.mobygames.get_mobygames_api_key', return_value='moby-key')
@patch('oneirodex.utils.secondary_scrapers.request_with_backoff')
def test_search_mobygames_games_mocked(mock_req, mock_key):
    resp = MagicMock()
    resp.content = b'{}'
    resp.json.return_value = {
        'games': [
            {
                'game_id': 15,
                'title': 'Doom',
                'moby_url': 'https://www.mobygames.com/game/15/doom/',
                'description': '<p>Classic <b>shooter</b></p>',
                'moby_score': 4.1,
                'sample_cover': {
                    'image': 'https://cdn.example/doom-cover.jpg',
                    'thumbnail_image': 'https://cdn.example/doom-thumb.jpg',
                },
                'platforms': [
                    {'platform_id': 2, 'platform_name': 'DOS'},
                    {'platform_id': 3, 'platform_name': 'Windows'},
                ],
            }
        ]
    }
    mock_req.return_value = resp
    results = search_mobygames_games('Doom', limit=5)
    assert len(results) == 1
    hit = results[0]
    assert hit['source'] == 'mobygames'
    assert hit['id'] == 15
    assert hit['mobygames_id'] == 15
    assert hit['name'] == 'Doom'
    assert hit['cover_url'] == 'https://cdn.example/doom-cover.jpg'
    assert hit['summary'] == 'Classic shooter'
    assert 'install' not in hit
    assert 'download_url' not in hit
    assert mock_req.call_args.kwargs['host_key'] == 'mobygames'
    assert mock_req.call_args.kwargs['params']['title'] == 'Doom'
    assert mock_req.call_args.kwargs['params']['api_key'] == 'moby-key'


@patch('oneirodex.utils.providers.thegamesdb.get_thegamesdb_api_key', return_value=None)
def test_search_thegamesdb_without_key_returns_empty(mock_key):
    assert search_thegamesdb_games('Sonic') == []
    mock_key.assert_called()


@patch('oneirodex.utils.providers.thegamesdb.get_thegamesdb_api_key', return_value='tgdb-key')
@patch('oneirodex.utils.secondary_scrapers.request_with_backoff')
def test_search_thegamesdb_games_mocked(mock_req, mock_key):
    resp = MagicMock()
    resp.content = b'{}'
    resp.json.return_value = {
        'code': 200,
        'status': 'Success',
        'data': {
            'count': 1,
            'games': [
                {
                    'id': 42,
                    'game_title': 'Sonic the Hedgehog',
                    'release_date': '1991-06-23',
                    'platform': 18,
                    'overview': 'Blue blur on Genesis.',
                }
            ],
        },
        'include': {
            'boxart': {
                'base_url': {
                    'large': 'https://cdn.thegamesdb.net/images/large/',
                    'medium': 'https://cdn.thegamesdb.net/images/medium/',
                },
                'data': {
                    '42': [
                        {
                            'id': 1,
                            'type': 'boxart',
                            'side': 'front',
                            'filename': 'boxart/front/42-1.jpg',
                        }
                    ]
                },
            },
            'platform': {
                'data': {
                    '18': {'id': 18, 'name': 'Sega Genesis', 'alias': 'sega-genesis'},
                }
            },
        },
    }
    mock_req.return_value = resp
    results = search_thegamesdb_games('Sonic', limit=5)
    assert len(results) == 1
    hit = results[0]
    assert hit['source'] == 'thegamesdb'
    assert hit['id'] == 42
    assert hit['thegamesdb_id'] == 42
    assert hit['name'] == 'Sonic the Hedgehog'
    assert hit['url'] == 'https://thegamesdb.net/game.php?id=42'
    assert hit['cover_url'] == 'https://cdn.thegamesdb.net/images/large/boxart/front/42-1.jpg'
    assert hit['summary'] == 'Blue blur on Genesis.'
    assert hit['platforms'] == ['Sega Genesis']
    assert 'install' not in hit
    assert 'download_url' not in hit
    assert mock_req.call_args.kwargs['host_key'] == 'thegamesdb'
    assert mock_req.call_args.kwargs['params']['name'] == 'Sonic'
    assert mock_req.call_args.kwargs['params']['apikey'] == 'tgdb-key'
    assert 'boxart' in mock_req.call_args.kwargs['params']['include']


def test_metadata_search_sources_endpoint(client, db_session, admin_user_for_meta):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user_for_meta.id)
        sess['_fresh'] = True
    resp = client.get('/api/search_metadata/sources')
    assert resp.status_code == 200
    ids = {s['id'] for s in resp.get_json()['sources']}
    assert 'meta_quest' in ids
    assert 'epic' in ids
    assert 'itch' in ids
    assert 'giantbomb' in ids
    assert 'mobygames' in ids
    assert 'thegamesdb' in ids
    meta = next(s for s in resp.get_json()['sources'] if s['id'] == 'meta_quest')
    assert meta['ownership_only'] is True
    assert meta['api_mode'] in ('igdb', 'csv_only', 'disabled', 'unofficial_graphql')
    assert meta['unofficial_graphql'] is False
    assert 'meta' in meta.get('aliases', [])
    moby = next(s for s in resp.get_json()['sources'] if s['id'] == 'mobygames')
    assert moby['needs_key'] is True
    assert 'key_configured' in moby
    assert 'moby' in moby.get('aliases', [])
    tgdb = next(s for s in resp.get_json()['sources'] if s['id'] == 'thegamesdb')
    assert tgdb['needs_key'] is True
    assert 'key_configured' in tgdb
    assert 'tgdb' in tgdb.get('aliases', [])


@pytest.fixture
def admin_user_for_meta(db_session):
    from uuid import uuid4

    from oneirodex.models import User

    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'MetaAdmin_{uid[:8]}',
        email=f'metaadmin_{uid[:8]}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@patch('oneirodex.routes_apis.metadata_search.search_meta_quest_games')
def test_search_metadata_meta_alias(mock_search, client, db_session, admin_user_for_meta):
    mock_search.return_value = [
        {'source': 'meta_quest', 'id': 1, 'name': 'Quest Game', 'ownership_only': True, 'is_vr': True}
    ]
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user_for_meta.id)
        sess['_fresh'] = True
    resp = client.get('/api/search_metadata?name=Quest&source=meta')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['source'] == 'meta_quest'
    assert data['ownership_only'] is True
    assert 'api_mode' in data


@patch('oneirodex.routes_apis.metadata_search.search_meta_quest_games')
def test_search_metadata_meta_quest_route(mock_search, client, db_session, admin_user_for_meta):
    mock_search.return_value = [
        {'source': 'meta_quest', 'id': 1, 'name': 'Quest Game', 'ownership_only': True}
    ]
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user_for_meta.id)
        sess['_fresh'] = True
    resp = client.get('/api/search_metadata?name=Quest&source=meta_quest')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['source'] == 'meta_quest'
    assert data['ownership_only'] is True
    assert len(data['results']) == 1


@patch('oneirodex.routes_apis.metadata_search.get_mobygames_api_key', return_value=None)
@patch('oneirodex.routes_apis.metadata_search.search_mobygames_games', return_value=[])
def test_search_metadata_mobygames_honest_without_key(
    mock_search, mock_key, client, db_session, admin_user_for_meta,
):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user_for_meta.id)
        sess['_fresh'] = True
    resp = client.get('/api/search_metadata?name=Doom&source=mobygames')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['source'] == 'mobygames'
    assert data['results'] == []
    assert data['needs_key'] is True
    assert data['key_configured'] is False
    assert 'MOBYGAMES_API_KEY' in data['note']


@patch('oneirodex.routes_apis.metadata_search.get_mobygames_api_key', return_value='moby-key')
@patch('oneirodex.routes_apis.metadata_search.search_mobygames_games')
def test_search_metadata_moby_alias(mock_search, mock_key, client, db_session, admin_user_for_meta):
    mock_search.return_value = [
        {
            'source': 'mobygames',
            'id': 15,
            'name': 'Doom',
            'url': 'https://www.mobygames.com/game/15/doom/',
            'cover_url': 'https://cdn.example/doom.jpg',
            'mobygames_id': 15,
        }
    ]
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user_for_meta.id)
        sess['_fresh'] = True
    resp = client.get('/api/search_metadata?name=Doom&source=moby')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['source'] == 'mobygames'
    assert data['key_configured'] is True
    assert len(data['results']) == 1
    assert data['results'][0]['mobygames_id'] == 15
    mock_search.assert_called_once()


@patch('oneirodex.routes_apis.metadata_search.get_thegamesdb_api_key', return_value=None)
@patch('oneirodex.routes_apis.metadata_search.search_thegamesdb_games', return_value=[])
def test_search_metadata_thegamesdb_honest_without_key(
    mock_search, mock_key, client, db_session, admin_user_for_meta,
):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user_for_meta.id)
        sess['_fresh'] = True
    resp = client.get('/api/search_metadata?name=Sonic&source=thegamesdb')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['source'] == 'thegamesdb'
    assert data['results'] == []
    assert data['needs_key'] is True
    assert data['key_configured'] is False
    assert 'THEGAMESDB_API_KEY' in data['note']


@patch('oneirodex.routes_apis.metadata_search.get_thegamesdb_api_key', return_value='tgdb-key')
@patch('oneirodex.routes_apis.metadata_search.search_thegamesdb_games')
def test_search_metadata_tgdb_alias(mock_search, mock_key, client, db_session, admin_user_for_meta):
    mock_search.return_value = [
        {
            'source': 'thegamesdb',
            'id': 42,
            'name': 'Sonic the Hedgehog',
            'url': 'https://thegamesdb.net/game.php?id=42',
            'cover_url': 'https://cdn.thegamesdb.net/images/large/boxart/front/42-1.jpg',
            'thegamesdb_id': 42,
        }
    ]
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user_for_meta.id)
        sess['_fresh'] = True
    resp = client.get('/api/search_metadata?name=Sonic&source=tgdb')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['source'] == 'thegamesdb'
    assert data['key_configured'] is True
    assert len(data['results']) == 1
    assert data['results'][0]['thegamesdb_id'] == 42
    mock_search.assert_called_once()
