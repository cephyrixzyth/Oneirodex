"""
Unit tests for oneirodex.routes_apis.admin_search

Tests the admin-only games search endpoint used by the Identify page's
"link to existing library game" workflow.
"""

import pytest
from uuid import uuid4

from sqlalchemy import text

from oneirodex.models import User, Game, Library, LibraryPlatform


@pytest.fixture
def regular_user(db_session):
    """Create a test regular (non-admin) user."""
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
def admin_user(db_session):
    """Create a test admin user."""
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
def sample_library(db_session):
    library = Library(name='Search Test Library', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def sample_games(db_session, sample_library):
    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.commit()

    games = [
        Game(
            name='Alpha Quest',
            full_disk_path='/allowed/games/alpha-quest',
            library_uuid=sample_library.uuid,
            igdb_id=300001
        ),
        Game(
            name='Alpha Strike',
            full_disk_path='/allowed/games/alpha-strike',
            library_uuid=sample_library.uuid,
            igdb_id=300002
        ),
        Game(
            name='Beta Runner',
            full_disk_path='/allowed/games/beta-runner',
            library_uuid=sample_library.uuid,
            igdb_id=300003
        ),
    ]
    for game in games:
        db_session.add(game)
    db_session.commit()

    yield games

    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.commit()


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestAdminGamesSearchAPI:
    def test_requires_login(self, client):
        response = client.get('/api/admin/games_search?q=alpha')
        assert response.status_code == 302

    def test_requires_admin(self, client, regular_user):
        _login(client, regular_user)
        response = client.get('/api/admin/games_search?q=alpha')
        # admin_required redirects non-admins rather than 403ing
        assert response.status_code == 403

    def test_empty_query_returns_empty_list(self, client, admin_user):
        _login(client, admin_user)
        response = client.get('/api/admin/games_search?q=')
        assert response.status_code == 200
        assert response.get_json() == []

    def test_missing_query_returns_empty_list(self, client, admin_user):
        _login(client, admin_user)
        response = client.get('/api/admin/games_search')
        assert response.status_code == 200
        assert response.get_json() == []

    def test_query_too_long_returns_400(self, client, admin_user):
        _login(client, admin_user)
        long_query = 'a' * 101
        response = client.get(f'/api/admin/games_search?q={long_query}')
        assert response.status_code == 400
        data = response.get_json()
        assert data['ok'] is False
        assert data['error'] == 'Search term too long'
        assert data['error_code'] == 'bad_request'

    def test_search_matches_by_name_case_insensitive(self, client, admin_user, sample_games):
        _login(client, admin_user)
        response = client.get('/api/admin/games_search?q=alpha')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        names = sorted(item['name'] for item in data)
        assert names == ['Alpha Quest', 'Alpha Strike']

    def test_search_result_shape_includes_full_disk_path(self, client, admin_user, sample_games):
        _login(client, admin_user)
        response = client.get('/api/admin/games_search?q=Beta')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 1
        item = data[0]
        assert set(item.keys()) == {'uuid', 'name', 'full_disk_path'}
        assert item['name'] == 'Beta Runner'
        assert item['full_disk_path'] == '/allowed/games/beta-runner'

    def test_search_no_results(self, client, admin_user, sample_games):
        _login(client, admin_user)
        response = client.get('/api/admin/games_search?q=Nonexistent')
        assert response.status_code == 200
        assert response.get_json() == []

    def test_search_limits_results(self, client, admin_user, sample_library, db_session):
        db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
        db_session.commit()
        for i in range(25):
            db_session.add(Game(
                name=f'Limit Test Game {i:02d}',
                full_disk_path=f'/allowed/games/limit-{i:02d}',
                library_uuid=sample_library.uuid,
                igdb_id=400000 + i
            ))
        db_session.commit()

        _login(client, admin_user)
        response = client.get('/api/admin/games_search?q=Limit Test')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 20

        db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
        db_session.commit()
