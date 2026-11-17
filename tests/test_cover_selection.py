"""Tests for cover selection policy and download error recording."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from oneirodex.models import Game, Image, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.cover_selection import (
    POLICY_ALIASES,
    apply_policy_to_game,
    image_save_path_status,
    resolve_policy,
    search_cover_candidates,
)
from oneirodex.utils.providers import ImageSearchResult, reset_provider_cache


@pytest.fixture(autouse=True)
def _reset_providers():
    reset_provider_cache()
    yield
    reset_provider_cache()


def test_resolve_policy_aliases():
    assert resolve_policy('sgdb_then_igdb_then_generate') == POLICY_ALIASES['sgdb_then_igdb_then_generate']
    assert resolve_policy('best_available') == POLICY_ALIASES['best_available']
    assert 'generate' in resolve_policy('best_available')
    assert resolve_policy('provider:igdb') == ('igdb',)
    assert resolve_policy('steamgriddb,generate') == ('steamgriddb', 'generate')


def test_image_save_path_status(app, tmp_path):
    writable = tmp_path / 'images'
    writable.mkdir()
    app.config['IMAGE_SAVE_PATH'] = str(writable)
    with app.app_context():
        status = image_save_path_status()
    assert status['exists'] is True
    assert status['writable'] is True
    assert status['error'] is None


@patch('oneirodex.utils.cover_selection.get_provider')
def test_search_cover_candidates_records_provider_errors(mock_get):
    disabled = MagicMock()
    disabled.is_enabled.return_value = False
    disabled.config_hint.return_value = 'Set STEAMGRIDDB_API_KEY'

    enabled = MagicMock()
    enabled.is_enabled.return_value = True
    enabled.search_covers.return_value = [
        ImageSearchResult(id='1', url='https://cdn.example/a.jpg', game_name='Demo')
    ]

    def _get(pid):
        if pid == 'steamgriddb':
            return disabled
        if pid == 'igdb':
            return enabled
        raise KeyError(pid)

    mock_get.side_effect = _get
    result = search_cover_candidates('Demo', providers=['steamgriddb', 'igdb'])
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['provider'] == 'igdb'
    assert any(e['provider'] == 'steamgriddb' for e in result['errors'])


@patch('oneirodex.utils.cover_selection.apply_cover_from_url')
@patch('oneirodex.utils.cover_selection.search_cover_candidates')
@patch('oneirodex.utils.cover_selection.image_save_path_status')
def test_apply_policy_prefers_first_provider(mock_path, mock_search, mock_apply, db_session):
    mock_path.return_value = {'path': '/tmp', 'exists': True, 'writable': True, 'error': None}
    mock_search.return_value = {
        'candidates': [{'provider': 'igdb', 'url': 'https://cdn.example/c.jpg'}],
        'errors': [],
    }
    mock_apply.return_value = {'game_uuid': 'g1', 'provider': 'igdb'}

    library = Library(name=f'CovLib_{uuid4().hex[:6]}', platform=LibraryPlatform.NES)
    db_session.add(library)
    db_session.flush()
    game = Game(uuid=str(uuid4()), name='Policy Game', library_uuid=library.uuid)
    db_session.add(game)
    db_session.commit()

    result = apply_policy_to_game(game, policy='provider:igdb')
    assert result['status'] == 'applied'
    assert result['provider'] == 'igdb'
    mock_apply.assert_called_once()


@patch('oneirodex.utils.cover_selection.image_save_path_status')
def test_apply_policy_fails_when_path_not_writable(mock_path, db_session):
    mock_path.return_value = {
        'path': '/ro',
        'exists': True,
        'writable': False,
        'error': 'not writable',
    }
    library = Library(name=f'CovLib_{uuid4().hex[:6]}', platform=LibraryPlatform.SNES)
    db_session.add(library)
    db_session.flush()
    game = Game(uuid=str(uuid4()), name='No Write', library_uuid=library.uuid)
    db_session.add(game)
    db_session.commit()

    result = apply_policy_to_game(game, policy='generate_only')
    assert result['status'] == 'failed'
    assert 'writable' in (result.get('error') or '').lower() or 'not writable' in (result.get('error') or '')


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        user_id=uid,
        name=f'CoverAdmin_{uid[:8]}',
        email=f'coveradmin_{uid[:8]}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def test_image_queue_includes_failure_reason_and_path(client, db_session, admin_user, app, tmp_path):
    img_root = tmp_path / 'images'
    img_root.mkdir()
    app.config['IMAGE_SAVE_PATH'] = str(img_root)

    library = Library(name=f'QLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.flush()
    game = Game(uuid=str(uuid4()), name='Queued', library_uuid=library.uuid)
    db_session.add(game)
    db_session.flush()
    image = Image(
        game_uuid=game.uuid,
        image_type='cover',
        url='missing.jpg',
        download_url='https://cdn.example/missing.jpg',
        is_downloaded=False,
        last_error='HTTP 404 downloading image.',
    )
    db_session.add(image)
    db_session.commit()

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    resp = client.get('/admin/api/image_queue_list?status=failed')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'image_save_path' in data
    assert data['image_save_path']['writable'] is True
    assert data['images']
    assert data['images'][0]['failure_reason'] == 'HTTP 404 downloading image.'
    assert data['images'][0]['status'] == 'failed'
