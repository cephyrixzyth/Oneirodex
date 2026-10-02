"""Unit tests for artwork provider framework and SteamGridDB provider."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import select

from oneirodex.models import GlobalSettings, User
from oneirodex.utils.providers import (
    ProviderDisabledError,
    SteamGridDBProvider,
    get_provider,
    get_steamgriddb_api_key,
    list_providers,
    mask_api_key,
    reset_provider_cache,
)

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- SteamGridDB provider adapter.


@pytest.fixture(autouse=True)
def _reset_provider_state(monkeypatch):
    monkeypatch.delenv('STEAMGRIDDB_API_KEY', raising=False)
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', '')
    reset_provider_cache()
    yield
    reset_provider_cache()


def _ensure_global_settings(db_session, **kwargs):
    settings = db_session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    if not settings:
        settings = GlobalSettings()
        db_session.add(settings)
    for key, value in kwargs.items():
        setattr(settings, key, value)
    db_session.commit()
    return settings


def test_mask_api_key_short_and_long():
    assert mask_api_key(None) is None
    assert mask_api_key('') is None
    assert mask_api_key('abcd') == '****'
    assert mask_api_key('abcdefghijklmnop') == 'abcd...mnop'


def test_steamgriddb_api_key_from_env(monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', 'env-test-key')
    assert get_steamgriddb_api_key() == 'env-test-key'


def test_steamgriddb_api_key_from_database(app, db_session, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', '')
    settings = _ensure_global_settings(db_session, steamgriddb_api_key='db-test-key')
    db_session.expire_all()
    reloaded = db_session.get(GlobalSettings, settings.id)
    assert reloaded is not None
    assert reloaded.steamgriddb_api_key == 'db-test-key'
    with app.app_context():
        assert get_steamgriddb_api_key() == 'db-test-key'


def test_provider_disabled_without_key(db_session, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', '')
    _ensure_global_settings(db_session, steamgriddb_api_key=None)
    provider = SteamGridDBProvider()
    assert provider.is_enabled() is False
    with pytest.raises(ProviderDisabledError):
        provider.search_covers('Celeste')


@patch('oneirodex.utils.providers.steamgriddb.requests.get')
def test_search_covers_mocked(mock_get, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', 'test-key')
    provider = SteamGridDBProvider()

    def fake_get(url, *args, **kwargs):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                if '/search/autocomplete/' in url:
                    return {
                        'success': True,
                        'data': [{'id': 7993, 'name': 'Celeste'}],
                    }
                if '/grids/game/7993' in url:
                    return {
                        'success': True,
                        'data': [{
                            'id': 12345,
                            'url': 'https://cdn.example/grid.png',
                            'thumb': 'https://cdn.example/grid_thumb.png',
                            'width': 600,
                            'height': 900,
                            'score': 0,
                            'style': 'alternate',
                            'mime': 'image/png',
                            'nsfw': False,
                        }],
                    }
                raise AssertionError(f'Unexpected URL: {url}')

        return FakeResponse()

    mock_get.side_effect = fake_get
    results = provider.search_covers('Celeste', limit=5)
    assert len(results) == 1
    assert results[0].url == 'https://cdn.example/grid.png'
    assert results[0].game_name == 'Celeste'
    assert results[0].game_id == 7993
    assert mock_get.call_count == 2


def test_fetch_image_mocked(monkeypatch):
    """fetch_image goes through the SSRF-guarded safe_get (providers/base.py);
    this test used to patch requests.get, which that path never calls, so it
    reached the network. Mock the guarded fetch and resolve the reserved
    `cdn.example` name instead of depending on the machine's resolver."""
    import ipaddress

    from oneirodex.utils import security
    from oneirodex.utils.providers import base

    monkeypatch.setattr(security, '_resolve_host', lambda host: [ipaddress.ip_address('93.184.216.34')])
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', 'test-key')
    provider = SteamGridDBProvider()

    class FakeResponse:
        status_code = 200
        content = b'PNGDATA'
        headers = {'Content-Type': 'image/png'}

    fetched = []

    def fake_safe_get(url, **kwargs):
        fetched.append((url, kwargs.get('validator')))
        return FakeResponse()

    monkeypatch.setattr(base, 'safe_get', fake_safe_get)
    data, content_type = provider.fetch_image('https://cdn.example/grid.png')
    assert data == b'PNGDATA'
    assert content_type == 'image/png'
    assert fetched and fetched[0][1] is not None, 'the redirect validator still applies'


def test_registry_lists_steamgriddb(app, db_session, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', '')
    _ensure_global_settings(db_session, steamgriddb_api_key=None)
    with app.app_context():
        providers = list_providers()
        assert get_provider('steamgriddb').id == 'steamgriddb'

    ids = {p['id'] for p in providers}
    assert 'steamgriddb' in ids
    assert 'igdb' in ids
    sgdb = next(p for p in providers if p['id'] == 'steamgriddb')
    assert sgdb['enabled'] is False


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    row = User(
        name=f'admin_{uid[:8]}',
        email=f'admin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login_admin(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def test_providers_api_disabled(client, app, db_session, admin_user, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', '')
    _ensure_global_settings(db_session, steamgriddb_api_key=None)
    _login_admin(client, app, admin_user)

    resp = client.get('/api/providers')
    assert resp.status_code == 200
    payload = resp.get_json()
    by_id = {p['id']: p for p in payload['providers']}
    assert 'steamgriddb' in by_id
    assert by_id['steamgriddb']['enabled'] is False

    search_resp = client.get('/api/providers/steamgriddb/search?q=Celeste')
    assert search_resp.status_code == 503
    assert 'STEAMGRIDDB_API_KEY' in search_resp.get_json()['error']


@patch('oneirodex.utils.providers.steamgriddb.requests.get')
def test_providers_api_search_enabled(mock_get, client, app, db_session, admin_user, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', 'test-key')
    _login_admin(client, app, admin_user)

    def fake_get(url, *args, **kwargs):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                if '/search/autocomplete/' in url:
                    return {'success': True, 'data': []}
                return {'success': True, 'data': []}

        return FakeResponse()

    mock_get.side_effect = fake_get
    resp = client.get('/api/providers/steamgriddb/search?q=UnknownGame')
    assert resp.status_code == 200
    assert resp.get_json()['results'] == []


def test_apply_artwork_missing_game_returns_404(client, app, db_session, admin_user, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', 'test-key')
    _login_admin(client, app, admin_user)
    game_uuid = str(uuid4())
    resp = client.post(
        f'/api/games/{game_uuid}/artwork/steamgriddb',
        json={'url': 'https://cdn.example/grid.png'},
    )
    assert resp.status_code == 404
    assert 'not found' in resp.get_json()['error'].lower()


@patch('oneirodex.utils.providers.steamgriddb.requests.get')
def test_search_logos_mocked(mock_get, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', 'test-key')
    provider = SteamGridDBProvider()

    def fake_get(url, *args, **kwargs):
        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                if '/search/autocomplete/' in url:
                    return {
                        'success': True,
                        'data': [{'id': 7993, 'name': 'Celeste'}],
                    }
                if '/logos/game/7993' in url:
                    return {
                        'success': True,
                        'data': [{
                            'id': 55,
                            'url': 'https://cdn.example/logo.png',
                            'thumb': 'https://cdn.example/logo_thumb.png',
                            'width': 800,
                            'height': 200,
                            'score': 1,
                            'style': 'white',
                            'mime': 'image/png',
                            'nsfw': False,
                        }],
                    }
                raise AssertionError(f'Unexpected URL: {url}')

        return FakeResponse()

    mock_get.side_effect = fake_get
    results = provider.search_artwork('Celeste', limit=5, art_kind='logo')
    assert len(results) == 1
    assert results[0].url == 'https://cdn.example/logo.png'
    assert results[0].image_type == 'logo'


def test_apply_rejects_invalid_image_type(client, app, db_session, admin_user, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', 'test-key')
    _login_admin(client, app, admin_user)
    # Game does not need to exist for validation of image_type when game missing
    # returns 404 first — create a minimal game so we hit image_type check after lookup.
    from oneirodex.models import Game, Library
    from oneirodex.platform import LibraryPlatform

    lib = Library(name=f'artlib_{uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=f'ArtGame_{uuid4().hex[:8]}',
        full_disk_path=f'/tmp/{uuid4().hex}',
        library_uuid=lib.uuid,
    )
    db_session.add(game)
    db_session.commit()

    resp = client.post(
        f'/api/games/{game.uuid}/artwork/steamgriddb',
        json={'url': 'https://cdn.example/x.png', 'image_type': 'banner'},
    )
    assert resp.status_code == 400
    assert 'image_type' in resp.get_json()['error']


def test_search_api_rejects_bad_image_type(client, app, db_session, admin_user, monkeypatch):
    monkeypatch.setenv('STEAMGRIDDB_API_KEY', 'test-key')
    _login_admin(client, app, admin_user)
    resp = client.get('/api/providers/steamgriddb/search?q=Celeste&image_type=banner')
    assert resp.status_code == 400
