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


class TestAddGameManualIgdbIdPrefill:
    def test_document_title_matches_manual_add_heading(self, client, admin_user, sample_library):
        _login(client, admin_user)
        response = client.get(f'/add_game_manual?library_uuid={sample_library.uuid}')

        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data

    def test_document_title_names_unmatched_identify_context(self, client, admin_user, sample_library):
        _login(client, admin_user)
        response = client.get(
            f'/add_game_manual?library_uuid={sample_library.uuid}&from_unmatched=true'
        )

        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data

    def test_document_title_matches_game_edit_context(self, client, admin_user, existing_game):
        _login(client, admin_user)
        response = client.get(f'/game_edit/{existing_game.uuid}')

        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data

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
