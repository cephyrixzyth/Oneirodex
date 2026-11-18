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

    def test_library_route_requires_login(self, client):
        """Test that the library route requires authentication."""
        response = client.get('/library')
        assert response.status_code == 302  # Redirect to login

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


