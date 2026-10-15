import pytest
from unittest.mock import patch, Mock, MagicMock
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select, func

from oneirodex import create_app, db
from oneirodex.models import (
    User, Game, Library, Genre, GameMode, Theme, Platform, 
    PlayerPerspective, Image, UserPreference
)
from oneirodex.platform import LibraryPlatform




@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user_uuid = str(uuid4())
    user = User(
        name=f'testuser_{user_uuid[:8]}',
        email=f'test_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='user',
        user_id=user_uuid
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    """Create an admin user."""
    admin_uuid = str(uuid4())
    admin = User(
        name=f'admin_{admin_uuid[:8]}',
        email=f'admin_{admin_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=admin_uuid
    )
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def test_library(db_session):
    """Create a test library."""
    unique_name = f'Test Library {uuid4().hex[:8]}'
    library = Library(
        name=unique_name,
        image_url='/static/library_test.jpg',
        platform=LibraryPlatform.PCWIN,
        display_order=1
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def test_game(db_session, test_library):
    """Create a test game."""
    game = Game(
        uuid=str(uuid4()),
        name='Test Game',
        library_uuid=test_library.uuid,
        summary='A test game',
        rating=85,
        size=1024000,
        first_release_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
        date_identified=datetime.now(timezone.utc)
    )
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def test_genre(db_session):
    """Create a test genre."""
    # Check if genre already exists to avoid unique constraint violation
    genre = db.session.execute(select(Genre).filter_by(name='Action')).scalar_one_or_none()
    if not genre:
        genre = Genre(name='Action')
        db_session.add(genre)
        db_session.commit()
    return genre


@pytest.fixture
def test_user_preference(db_session, test_user):
    """Create test user preferences."""
    preference = UserPreference(
        user_id=test_user.id,
        items_per_page=25,
        default_sort='name',
        default_sort_order='desc'
    )
    db_session.add(preference)
    db_session.commit()
    return preference


class TestLibraryBlueprint:
    # NOTE (2026-08-06): `/library` serves the member SPA shell via
    # render_member_spa(); it no longer calls get_games(). Filter plumbing moved
    # to GET /api/browse and is covered by tests/test_routes_apis_browse.py and
    # the test_browse_*.py files. These tests now assert what the route really
    # does — auth, preference handling and redirect behaviour — instead of
    # asserting call args on a function the route never reaches.

    """Test cases for the library blueprint."""

    def test_libraries_route_requires_login(self, client):
        """Test that the libraries route requires authentication."""
        response = client.get('/libraries')
        assert response.status_code == 302  # Redirect to login

    def test_libraries_route_requires_admin(self, client, test_user):
        """Test that the libraries route requires admin privileges."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        response = client.get('/libraries')
        assert response.status_code == 302  # Redirect due to admin_required

    def test_libraries_route_success_admin(self, client, admin_user, test_library, db_session):
        """Test successful access to libraries route as admin."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        with patch('oneirodex.routes_library.render_admin_spa') as mock_render:
            mock_render.return_value = 'rendered admin shell'
            response = client.get('/libraries')
            
        assert response.status_code == 200
        mock_render.assert_called_once_with(title='Libraries & scans - Oneirodex Admin')

    def test_library_route_requires_login(self, client):
        """Test that the library route requires authentication."""
        response = client.get('/library')
        assert response.status_code == 302  # Redirect to login

    def test_library_route_creates_default_preferences(self, client, test_user, db_session):
        """Test that library route creates default preferences if none exist."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        # Ensure user has no preferences initially
        assert test_user.preferences is None
        
        with patch('oneirodex.routes_library.render_member_spa') as mock_render:
            mock_render.return_value = 'rendered member shell'
            response = client.get('/library')
        
        assert response.status_code == 200
        mock_render.assert_called_once()
        # Check that preferences were created
        db_session.refresh(test_user)
        assert test_user.preferences is not None

    def test_library_route_uses_existing_preferences(self, client, test_user, test_user_preference, db_session):
        """Existing preferences are left intact when the shell renders."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/library')

        assert response.status_code == 200
        db_session.refresh(test_user)
        # The route must not clobber preferences it did not create.
        assert test_user.preferences is not None
        assert test_user.preferences.default_sort == test_user_preference.default_sort
        assert test_user.preferences.default_sort_order == test_user_preference.default_sort_order

    def test_library_route_with_library_uuid_filter(self, client, test_user, test_library, db_session):
        """Test library route with library_uuid filter."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        response = client.get(f'/library?library_uuid={test_library.uuid}')

        # A known library renders the shell; the SPA reads the filter from the URL.
        assert response.status_code == 200

    def test_library_route_with_library_name_filter(self, client, test_user, test_library, db_session):
        """Test library route with library_name filter."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        response = client.get(f'/library?library_name={test_library.name}')

        # A resolvable name renders rather than redirecting — the invalid-name
        # case below is what must redirect.
        assert response.status_code == 200

    def test_library_route_with_invalid_library_name(self, client, test_user, db_session):
        """Test library route with invalid library_name."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        response = client.get('/library?library_name=NonExistentLibrary')
        assert response.status_code == 302  # Redirect back to library

    def test_library_route_with_filters(self, client, test_user, db_session):
        """Test library route with various filters."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        query_params = {
            'genre': 'Action',
            'rating': '80',
            'game_mode': 'Single player',
            'player_perspective': 'Third person',
            'theme': 'Science fiction',
            'sort_by': 'rating',
            'sort_order': 'desc',
            'per_page': '10'
        }
        
        query_string = '&'.join([f'{k}={v}' for k, v in query_params.items()])
        response = client.get(f'/library?{query_string}')

        # Extra query params the shell does not itself consume must not 500 it.
        assert response.status_code == 200


class TestGetGamesFunction:
    """Test cases for the get_games function."""

    def test_get_games_basic(self, app, db_session, test_game, test_library):
        """Test basic get_games functionality."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games()
                
        assert isinstance(games, list)
        assert total >= 0
        assert pages >= 0
        assert current_page == 1

    def test_get_games_with_library_filter(self, app, db_session, test_game, test_library):
        """Test get_games with library filter."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(library_uuid=test_library.uuid)
                
        assert isinstance(games, list)

    def test_get_games_with_library_name_filter(self, app, db_session, test_game, test_library):
        """Test get_games with library_name filter."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(library_name=test_library.name)
                
        assert isinstance(games, list)

    def test_get_games_with_invalid_library_name(self, app, db_session):
        """Test get_games with invalid library_name returns empty result."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(library_name='NonExistentLibrary')
                
        assert games == []
        assert total == 0
        assert pages == 0
        assert current_page == 1

    def test_get_games_with_genre_filter(self, app, db_session, test_game, test_genre):
        """Test get_games with genre filter."""
        # Add genre to game
        test_game.genres.append(test_genre)
        db_session.commit()
        
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(genre='Action')
                
        assert isinstance(games, list)

    def test_get_games_with_rating_filter(self, app, db_session, test_game):
        """Test get_games with rating filter."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(rating=80)
                
        assert isinstance(games, list)

    def test_get_games_sorting_by_name(self, app, db_session, test_game):
        """Test get_games sorting by name."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(sort_by='name', sort_order='asc')
                
        assert isinstance(games, list)

    def test_get_games_sorting_by_rating(self, app, db_session, test_game):
        """Test get_games sorting by rating."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(sort_by='rating', sort_order='desc')
                
        assert isinstance(games, list)

    def test_get_games_sorting_by_date(self, app, db_session, test_game):
        """Test get_games sorting by first_release_date."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(sort_by='first_release_date', sort_order='asc')
                
        assert isinstance(games, list)

    def test_get_games_sorting_by_size(self, app, db_session, test_game):
        """Test get_games sorting by size."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(sort_by='size', sort_order='asc')
                
        assert isinstance(games, list)

    def test_get_games_sorting_by_date_identified(self, app, db_session, test_game):
        """Test get_games sorting by date_identified."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(sort_by='date_identified', sort_order='desc')
                
        assert isinstance(games, list)

    def test_get_games_pagination(self, app, db_session, test_game):
        """Test get_games pagination."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games(page=1, per_page=5)
                
        assert isinstance(games, list)
        assert current_page == 1

    def test_get_games_with_cover_image(self, app, db_session, test_game):
        """Test get_games includes cover image information."""
        # Create a cover image for the game
        cover_image = Image(
            game_uuid=test_game.uuid,
            image_type='cover',
            url='test_cover.jpg'
        )
        db_session.add(cover_image)
        db_session.commit()
        
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games()
                
        assert isinstance(games, list)
        if games:
            assert 'cover_url' in games[0]

    @patch('oneirodex.routes_library.format_size')
    def test_get_games_formats_size(self, mock_format_size, app, db_session, test_game):
        """Test get_games formats game size."""
        mock_format_size.return_value = "1.0 MB"
        
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games()
                
        if games:
            mock_format_size.assert_called()

    def test_get_games_unauthenticated_user(self, app, db_session, test_game):
        """Test get_games with unauthenticated user."""
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = False
                mock_current_user.id = None
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games()
                
        assert isinstance(games, list)

    def test_get_games_game_data_structure(self, app, db_session, test_game, test_genre):
        """Test that get_games returns properly structured game data."""
        # Add genre to game
        test_game.genres.append(test_genre)
        db_session.commit()
        
        with app.app_context():
            with patch('oneirodex.routes_library.current_user', new_callable=MagicMock) as mock_current_user:
                mock_current_user.is_authenticated = True
                mock_current_user.id = 1
                
                from oneirodex.routes_library import get_games
                games, total, pages, current_page = get_games()
                
        if games:
            game_data = games[0]
            required_fields = [
                'id', 'uuid', 'name', 'cover_url', 'summary', 
                'url', 'size', 'genres', 'is_favorite', 'first_release_date'
            ]
            for field in required_fields:
                assert field in game_data
            
            assert isinstance(game_data['genres'], list)
            assert isinstance(game_data['is_favorite'], bool)
