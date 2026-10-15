"""
Unit tests for oneirodex.routes_games_ext.add

Covers the "link existing library game" flow added for Track 4 (Find/Add
MVP), plus the igdb_id prefill enhancement on the Identify GET handler.
The existing IGDB/manual add flow is exercised elsewhere; these tests focus
on the additive behavior only.
"""

import pytest
from uuid import uuid4
from unittest.mock import patch

from sqlalchemy import delete, select

from oneirodex.models import User, Game, Library, LibraryPlatform, UnmatchedFolder


@pytest.fixture
def admin_user(db_session):
    admin_uuid = str(uuid4())
    admin = User(
        name=f'adminuser_{admin_uuid[:8]}',
        email=f'admin_{admin_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=admin_uuid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=5
    )
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    user_uuid = str(uuid4())
    user = User(
        name=f'regularuser_{user_uuid[:8]}',
        email=f'regular_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='user',
        user_id=user_uuid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=5
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_library(db_session):
    library = Library(name='Link Test Library', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def existing_game(db_session, sample_library):
    game = Game(
        name='Existing Game',
        full_disk_path='/allowed/games/existing-game-old-path',
        library_uuid=sample_library.uuid,
        igdb_id=500001
    )
    db_session.add(game)
    db_session.commit()
    yield game
    db_session.execute(delete(Game).filter_by(uuid=game.uuid))
    db_session.commit()


@pytest.fixture
def matching_unmatched_folder(db_session, sample_library):
    folder = UnmatchedFolder(
        library_uuid=sample_library.uuid,
        folder_path='/allowed/games/new-disk-folder',
        content_type='Games',
        status='Pending'
    )
    db_session.add(folder)
    db_session.commit()
    yield folder


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestLinkExistingGame:
    def test_requires_login(self, client):
        response = client.post('/link_existing_game', data={
            'game_uuid': str(uuid4()),
            'full_disk_path': '/allowed/games/new-disk-folder',
        })
        assert response.status_code == 302

    def test_requires_admin(self, client, regular_user):
        _login(client, regular_user)
        response = client.post('/link_existing_game', data={
            'game_uuid': str(uuid4()),
            'full_disk_path': '/allowed/games/new-disk-folder',
        })
        assert response.status_code == 302

    def test_missing_fields_redirects_back(self, client, admin_user):
        _login(client, admin_user)
        response = client.post('/link_existing_game', data={}, follow_redirects=False)
        assert response.status_code == 302
        assert '/add_game_manual' in response.headers['Location']

    def test_unsafe_path_rejected(self, client, admin_user, existing_game):
        _login(client, admin_user)
        with patch('oneirodex.routes_games_ext.add.is_safe_path', return_value=(False, 'Access denied')):
            with patch('oneirodex.routes_games_ext.add.get_allowed_base_directories', return_value=['/allowed']):
                response = client.post('/link_existing_game', data={
                    'game_uuid': existing_game.uuid,
                    'full_disk_path': '/etc/passwd',
                }, follow_redirects=False)

        assert response.status_code == 302
        assert '/add_game_manual' in response.headers['Location']

    def test_no_allowed_bases_configured(self, client, admin_user, existing_game):
        _login(client, admin_user)
        with patch('oneirodex.routes_games_ext.add.get_allowed_base_directories', return_value=[]):
            response = client.post('/link_existing_game', data={
                'game_uuid': existing_game.uuid,
                'full_disk_path': '/allowed/games/new-disk-folder',
            }, follow_redirects=False)

        assert response.status_code == 302
        assert '/add_game_manual' in response.headers['Location']

    def test_nonexistent_game_redirects_back(self, client, admin_user):
        _login(client, admin_user)
        with patch('oneirodex.routes_games_ext.add.is_safe_path', return_value=(True, None)):
            with patch('oneirodex.routes_games_ext.add.get_allowed_base_directories', return_value=['/allowed']):
                response = client.post('/link_existing_game', data={
                    'game_uuid': str(uuid4()),
                    'full_disk_path': '/allowed/games/new-disk-folder',
                }, follow_redirects=False)

        assert response.status_code == 302
        assert '/add_game_manual' in response.headers['Location']

    def test_success_updates_game_path_and_redirects(self, client, admin_user, existing_game, db_session):
        _login(client, admin_user)
        new_path = '/allowed/games/new-disk-folder'

        with patch('oneirodex.routes_games_ext.add.is_safe_path', return_value=(True, None)):
            with patch('oneirodex.routes_games_ext.add.get_allowed_base_directories', return_value=['/allowed']):
                response = client.post('/link_existing_game', data={
                    'game_uuid': existing_game.uuid,
                    'full_disk_path': new_path,
                }, follow_redirects=False)

        assert response.status_code == 302
        assert 'scan_management' in response.headers['Location']
        assert 'active_tab=unmatched' in response.headers['Location']

        db_session.refresh(existing_game)
        assert existing_game.full_disk_path == new_path

    def test_success_clears_matching_unmatched_folder(
        self, client, admin_user, existing_game, matching_unmatched_folder, db_session
    ):
        _login(client, admin_user)
        new_path = matching_unmatched_folder.folder_path

        with patch('oneirodex.routes_games_ext.add.is_safe_path', return_value=(True, None)):
            with patch('oneirodex.routes_games_ext.add.get_allowed_base_directories', return_value=['/allowed']):
                response = client.post('/link_existing_game', data={
                    'game_uuid': existing_game.uuid,
                    'full_disk_path': new_path,
                }, follow_redirects=False)

        assert response.status_code == 302

        remaining = db_session.execute(
            select(UnmatchedFolder).filter_by(folder_path=new_path)
        ).scalars().first()
        assert remaining is None

    def test_success_logs_system_event(self, client, admin_user, existing_game):
        _login(client, admin_user)
        with patch('oneirodex.routes_games_ext.add.is_safe_path', return_value=(True, None)):
            with patch('oneirodex.routes_games_ext.add.get_allowed_base_directories', return_value=['/allowed']):
                with patch('oneirodex.routes_games_ext.add.log_system_event') as mock_log:
                    response = client.post('/link_existing_game', data={
                        'game_uuid': existing_game.uuid,
                        'full_disk_path': '/allowed/games/new-disk-folder',
                    }, follow_redirects=False)

        assert response.status_code == 302
        mock_log.assert_called_once()
        log_call = mock_log.call_args[0][0]
        assert existing_game.name in log_call


class TestAddGameManualIgdbIdPrefill:
    def test_document_title_matches_manual_add_heading(self, client, admin_user, sample_library):
        _login(client, admin_user)
        response = client.get(f'/add_game_manual?library_uuid={sample_library.uuid}')

        assert response.status_code == 200
        assert b'<title>Identify game \xc2\xb7 Oneirodex Admin</title>' in response.data

    def test_document_title_names_unmatched_identify_context(self, client, admin_user, sample_library):
        _login(client, admin_user)
        response = client.get(
            f'/add_game_manual?library_uuid={sample_library.uuid}&from_unmatched=true'
        )

        assert response.status_code == 200
        assert b'<title>Identify unmatched folder \xc2\xb7 Oneirodex Admin</title>' in response.data

    def test_document_title_matches_game_edit_context(self, client, admin_user, existing_game):
        _login(client, admin_user)
        response = client.get(f'/game_edit/{existing_game.uuid}')

        assert response.status_code == 200
        assert b'<title>Edit game entry \xc2\xb7 Oneirodex Admin</title>' in response.data

    def test_igdb_id_prefilled_from_query_arg(self, client, admin_user, sample_library):
        _login(client, admin_user)
        response = client.get(
            f'/add_game_manual?igdb_id=123456&library_uuid={sample_library.uuid}'
        )
        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data

    def test_no_igdb_id_query_arg_does_not_error(self, client, admin_user, sample_library):
        _login(client, admin_user)
        response = client.get(f'/add_game_manual?library_uuid={sample_library.uuid}')
        assert response.status_code == 200

    def test_invalid_igdb_id_query_arg_ignored(self, client, admin_user, sample_library):
        _login(client, admin_user)
        response = client.get(
            f'/add_game_manual?igdb_id=not-a-number&library_uuid={sample_library.uuid}'
        )
        assert response.status_code == 200
