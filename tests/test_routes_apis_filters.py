"""
Unit tests for oneirodex.routes_apis.filters

Tests the filter API endpoints including authentication, successful data retrieval,
error handling, and logging functionality.
"""

import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from sqlalchemy.exc import SQLAlchemyError

from oneirodex.models import User, Genre, Theme, GameMode, PlayerPerspective


def safe_cleanup_database(db_session):
    """Safely clean up database records respecting foreign key constraints."""
    from sqlalchemy import delete
    from oneirodex.models import SystemEvents
    
    # Clean up in order of dependencies
    db_session.execute(delete(SystemEvents))
    db_session.execute(delete(Genre))
    db_session.execute(delete(Theme))
    db_session.execute(delete(GameMode))
    db_session.execute(delete(PlayerPerspective))
    db_session.execute(delete(User))
    db_session.commit()


@pytest.fixture
def regular_user(db_session):
    """Create a test regular user."""
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
    user.set_password('regularpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_genres(db_session):
    """Create sample genres for testing."""
    # Clear existing data first
    from sqlalchemy import delete
    db_session.execute(delete(Genre))
    db_session.commit()
    
    genres = [
        Genre(name='Action'),
        Genre(name='Adventure'),
        Genre(name='RPG')
    ]
    for genre in genres:
        db_session.add(genre)
    db_session.commit()
    
    yield genres
    
    # Cleanup
    db_session.execute(delete(Genre))
    db_session.commit()


@pytest.fixture
def sample_themes(db_session):
    """Create sample themes for testing."""
    # Clear existing data first
    from sqlalchemy import delete
    db_session.execute(delete(Theme))
    db_session.commit()
    
    themes = [
        Theme(name='Fantasy'),
        Theme(name='Sci-Fi'),
        Theme(name='Horror')
    ]
    for theme in themes:
        db_session.add(theme)
    db_session.commit()
    
    yield themes
    
    # Cleanup
    db_session.execute(delete(Theme))
    db_session.commit()


@pytest.fixture
def sample_game_modes(db_session):
    """Create sample game modes for testing."""
    # Clear existing data first
    from sqlalchemy import delete
    db_session.execute(delete(GameMode))
    db_session.commit()
    
    game_modes = [
        GameMode(name='Single Player'),
        GameMode(name='Multiplayer'),
        GameMode(name='Co-op')
    ]
    for mode in game_modes:
        db_session.add(mode)
    db_session.commit()
    
    yield game_modes
    
    # Cleanup
    db_session.execute(delete(GameMode))
    db_session.commit()


@pytest.fixture
def sample_player_perspectives(db_session):
    """Create sample player perspectives for testing."""
    # Clear existing data first
    from sqlalchemy import delete
    db_session.execute(delete(PlayerPerspective))
    db_session.commit()
    
    perspectives = [
        PlayerPerspective(name='First Person'),
        PlayerPerspective(name='Third Person'),
        PlayerPerspective(name='Top Down')
    ]
    for perspective in perspectives:
        db_session.add(perspective)
    db_session.commit()
    
    yield perspectives
    
    # Cleanup
    db_session.execute(delete(PlayerPerspective))
    db_session.commit()


class TestFiltersAPIAuthentication:
    """Test authentication requirements for all filter endpoints."""
    
    def test_genres_requires_login(self, client):
        """Test that /api/genres requires user login."""
        response = client.get('/api/genres')
        assert response.status_code == 302  # Redirect to login
    
    def test_themes_requires_login(self, client):
        """Test that /api/themes requires user login."""
        response = client.get('/api/themes')
        assert response.status_code == 302  # Redirect to login
    
    def test_game_modes_requires_login(self, client):
        """Test that /api/game_modes requires user login."""
        response = client.get('/api/game_modes')
        assert response.status_code == 302  # Redirect to login
    
    def test_player_perspectives_requires_login(self, client):
        """Test that /api/player_perspectives requires user login."""
        response = client.get('/api/player_perspectives')
        assert response.status_code == 302  # Redirect to login

    def test_library_platforms_requires_login(self, client):
        response = client.get('/api/library_platforms')
        assert response.status_code == 302

    def test_igdb_platforms_requires_login(self, client):
        response = client.get('/api/igdb_platforms')
        assert response.status_code == 302

    def test_filters_bundle_requires_login(self, client):
        response = client.get('/api/filters/bundle')
        assert response.status_code == 302


class TestFiltersAPISuccessful:
    """Test successful data retrieval for each filter endpoint."""
    
    def test_get_genres_success(self, client, regular_user, sample_genres):
        """Test successful retrieval of genres."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/genres')
        assert response.status_code == 200
        
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 3
        
        # Check data structure
        for item in data:
            assert 'id' in item
            assert 'name' in item
        
        # Check specific data
        names = [item['name'] for item in data]
        assert 'Action' in names
        assert 'Adventure' in names
        assert 'RPG' in names

    def test_filters_bundle_returns_all_keys(self, client, regular_user, sample_genres):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True

        response = client.get('/api/filters/bundle')
        assert response.status_code == 200
        data = response.get_json()
        for key in (
            'libraries',
            'libraryPlatforms',
            'igdbPlatforms',
            'genres',
            'themes',
            'gameModes',
            'playerPerspectives',
        ):
            assert key in data
            assert isinstance(data[key], list)
        genre_names = [item['name'] for item in data['genres']]
        assert 'Action' in genre_names
    
    def test_get_themes_success(self, client, regular_user, sample_themes):
        """Test successful retrieval of themes."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/themes')
        assert response.status_code == 200
        
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 3
        
        names = [item['name'] for item in data]
        assert 'Fantasy' in names
        assert 'Sci-Fi' in names
        assert 'Horror' in names
    
    def test_get_game_modes_success(self, client, regular_user, sample_game_modes):
        """Test successful retrieval of game modes."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/game_modes')
        assert response.status_code == 200
        
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 3
        
        names = [item['name'] for item in data]
        assert 'Single Player' in names
        assert 'Multiplayer' in names
        assert 'Co-op' in names
    
    def test_get_player_perspectives_success(self, client, regular_user, sample_player_perspectives):
        """Test successful retrieval of player perspectives."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/player_perspectives')
        assert response.status_code == 200
        
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 3
        
        names = [item['name'] for item in data]
        assert 'First Person' in names
        assert 'Third Person' in names
        assert 'Top Down' in names

    def test_get_library_platforms_used_only(self, client, regular_user, db_session):
        from oneirodex.models import Library
        from oneirodex.platform import LibraryPlatform
        from uuid import uuid4

        lib = Library(
            name=f'Lib {uuid4().hex[:8]}',
            platform=LibraryPlatform.NES,
            display_order=0,
        )
        db_session.add(lib)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True

        response = client.get('/api/library_platforms')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        values = {item['value'] for item in data}
        assert 'NES' in values
        nes = next(item for item in data if item['value'] == 'NES')
        assert nes['name'] == LibraryPlatform.NES.value
        assert nes['id'] == 'NES'
        assert 'game_count' in nes
        assert isinstance(nes['game_count'], int)

    def test_get_igdb_platforms_used_only(self, client, regular_user, db_session):
        from oneirodex.models import Library, Game, Platform
        from oneirodex.platform import LibraryPlatform
        from uuid import uuid4

        lib = Library(
            name=f'Lib {uuid4().hex[:8]}',
            platform=LibraryPlatform.PCWIN,
            display_order=0,
        )
        db_session.add(lib)
        db_session.flush()

        linked = Platform(name=f'WinTest-{uuid4().hex[:6]}')
        orphan = Platform(name=f'Orphan-{uuid4().hex[:6]}')
        db_session.add_all([linked, orphan])
        db_session.flush()

        game = Game(
            uuid=str(uuid4()),
            name='PGame',
            library_uuid=lib.uuid,
            full_disk_path=f'/test/{uuid4().hex}',
        )
        game.platforms.append(linked)
        db_session.add(game)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True

        response = client.get('/api/igdb_platforms')
        assert response.status_code == 200
        names = {item['name'] for item in response.get_json()}
        assert linked.name in names
        assert orphan.name not in names


class TestFiltersAPIEmptyDatabase:
    """Test behavior with empty database scenarios."""
    
    def test_get_genres_empty_database(self, client, regular_user, db_session):
        """Test genres endpoint with no genres in database."""
        # Clear any existing data first
        from sqlalchemy import delete
        db_session.execute(delete(Genre))
        db_session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/genres')
        assert response.status_code == 200
        
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_get_themes_empty_database(self, client, regular_user, db_session):
        """Test themes endpoint with no themes in database."""
        # Clear any existing data first
        from sqlalchemy import delete
        db_session.execute(delete(Theme))
        db_session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/themes')
        assert response.status_code == 200
        
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_get_game_modes_empty_database(self, client, regular_user, db_session):
        """Test game modes endpoint with no game modes in database."""
        # Clear any existing data first
        from sqlalchemy import delete
        db_session.execute(delete(GameMode))
        db_session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/game_modes')
        assert response.status_code == 200
        
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_get_player_perspectives_empty_database(self, client, regular_user, db_session):
        """Test player perspectives endpoint with no perspectives in database."""
        # Clear any existing data first
        from sqlalchemy import delete
        db_session.execute(delete(PlayerPerspective))
        db_session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/player_perspectives')
        assert response.status_code == 200
        
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) == 0


class TestFiltersAPIResponseFormat:
    """Test response formats and data structures."""
    
    def test_successful_response_structure(self, client, regular_user, sample_genres):
        """Test that successful responses have correct structure."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/api/genres')
        assert response.status_code == 200
        assert response.content_type == 'application/json'
        
        data = response.get_json()
        assert isinstance(data, list)
        
        for item in data:
            assert isinstance(item, dict)
            assert 'id' in item
            assert 'name' in item
            assert isinstance(item['id'], int)
            assert isinstance(item['name'], str)
    
