import pytest
from unittest.mock import patch, Mock
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from flask import Flask
from oneirodex import create_app, db
from oneirodex.models import (
    Game, Library, DiscoverySection, Image, User
)
from oneirodex.platform import LibraryPlatform
from sqlalchemy import select




@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user = User(
        name=f'testuser_{uuid4().hex[:8]}',
        email=f'test_{uuid4().hex[:8]}@example.com',
        password_hash='hashed_password',
        role='user'
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def test_games(db_session, test_libraries):
    """Create test games."""
    # Use the first library for all games
    library = test_libraries[0]
    
    games = []
    for i in range(5):
        game = Game(
            name=f'Test Game {i}',
            summary=f'Test summary for game {i}',
            rating=80.0 + i if i > 0 else None,
            # (i + 1) so every seeded game has a non-zero download count. The
            # `most_downloaded` query filters `times_downloaded > 0` and the
            # test asserts it sees all five; `i * 10` left game 0 at zero and
            # only passed while an unrelated row in the shared database filled
            # the gap.
            times_downloaded=(i + 1) * 10,
            first_release_date=datetime(2020, 1, 1 + i),
            library_uuid=library.uuid
        )
        games.append(game)
        db_session.add(game)
    
    db_session.commit()
    return games


@pytest.fixture
def test_libraries(db_session):
    """Create test libraries."""
    libraries = []
    for i in range(2):
        library = Library(
            name=f'Test Library {i}',
            image_url=f'/static/library_{i}.jpg',
            platform=LibraryPlatform.PCWIN
        )
        libraries.append(library)
        db_session.add(library)
    
    db_session.commit()
    return libraries


@pytest.fixture
def test_discovery_sections(db_session):
    """Get or create test discovery sections."""
    # Check if default sections already exist (from app initialization)
    existing_sections = db.session.execute(select(DiscoverySection)).scalars().all()
    
    if existing_sections:
        # Return existing sections if they exist
        return existing_sections
    
    # Create new sections only if none exist
    sections = [
        DiscoverySection(
            identifier='test_libraries',
            name='Test Libraries',
            is_visible=True,
            display_order=1
        ),
        DiscoverySection(
            identifier='test_latest_games',
            name='Test Latest Games',
            is_visible=True,
            display_order=2
        ),
        DiscoverySection(
            identifier='test_most_downloaded',
            name='Test Most Downloaded',
            is_visible=True,
            display_order=3
        ),
        DiscoverySection(
            identifier='test_highest_rated',
            name='Test Highest Rated',
            is_visible=True,
            display_order=4
        ),
        DiscoverySection(
            identifier='test_hidden_section',
            name='Test Hidden Section',
            is_visible=False,
            display_order=5
        )
    ]
    
    for section in sections:
        db_session.add(section)
    
    db_session.commit()
    return sections


@pytest.fixture
def test_images(db_session, test_games):
    """Create test images for games."""
    images = []
    for i, game in enumerate(test_games[:3]):  # Only create images for first 3 games
        image = Image(
            game_uuid=game.uuid,
            image_type='cover',
            url=f'/static/covers/game_{i}_cover.jpg'
        )
        images.append(image)
        db_session.add(image)
    
    db_session.commit()
    return images


class TestDiscoverRoute:
    """Test the discover route functionality."""

    def test_discover_route_requires_login(self, client, configured_install):
        """Test that discover route requires authentication."""
        response = client.get('/discover')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_discover_route_callable(self, app):
        """Test discover route core functionality with mocked authentication."""
        with app.app_context():
            from oneirodex.routes_discover import discover
            assert callable(discover)


class TestDiscoverSectionsApi:
    """JSON shelves endpoint used by the member SPA."""

    def test_discover_sections_api_requires_login(self, client):
        response = client.get('/api/discover/sections')
        assert response.status_code in (302, 401)

    def test_build_discover_sections_shape(self, app, db_session, test_user, test_discovery_sections, test_games):
        from oneirodex.routes_discover import build_discover_sections

        with app.app_context():
            with app.test_request_context('/'):
                latest = db.session.execute(
                    select(DiscoverySection).filter_by(identifier='latest_games')
                ).scalar_one_or_none()
                if latest is None:
                    latest = DiscoverySection(
                        identifier='latest_games',
                        name='Latest Games',
                        is_visible=True,
                        display_order=1,
                    )
                    db_session.add(latest)
                    db_session.commit()
                else:
                    latest.is_visible = True
                    db_session.commit()

                sections = build_discover_sections(test_user)
                assert isinstance(sections, list)
                for row in sections:
                    assert 'identifier' in row
                    assert 'title' in row
                    assert 'games' in row
                    assert isinstance(row['games'], list)


class TestDiscoverSectionQueries:
    """Test the database queries for different section types."""

    def test_discovery_sections_query(self, db_session, test_discovery_sections):
        """Test that visible discovery sections are queried correctly."""
        visible_sections = db.session.execute(select(DiscoverySection).filter_by(is_visible=True).order_by(DiscoverySection.display_order)).scalars().all()
        
        assert len(visible_sections) >= 3  # At least 3 visible sections
        assert all(section.is_visible for section in visible_sections)
        
        # Check they are ordered by display_order
        display_orders = [section.display_order for section in visible_sections]
        assert display_orders == sorted(display_orders)

    def test_libraries_query(self, db_session, test_libraries):
        """Test that libraries are queried correctly."""
        libraries = db.session.execute(select(Library)).scalars().all()
        
        assert len(libraries) >= 2  # At least our test libraries
        library_names = [lib.name for lib in libraries if 'Test Library' in lib.name]
        assert 'Test Library 0' in library_names
        assert 'Test Library 1' in library_names

    def test_latest_games_query(self, db_session, test_games):
        """Test latest games query."""
        latest_games = db.session.execute(select(Game).order_by(Game.date_created.desc()).limit(8)).scalars().all()
        
        assert len(latest_games) >= 5  # At least our test games
        
        # Check that games are ordered by date_created desc
        if len(latest_games) > 1:
            assert latest_games[0].date_created >= latest_games[1].date_created

    def test_most_downloaded_query(self, db_session, test_games):
        """Test most downloaded games query."""
        most_downloaded = db.session.execute(select(Game).filter(Game.times_downloaded > 0).order_by(Game.times_downloaded.desc()).limit(8)).scalars().all()
        
        assert len(most_downloaded) >= 5  # At least our test games
        
        # Check that games are ordered by times_downloaded desc  
        if len(most_downloaded) > 1:
            assert most_downloaded[0].times_downloaded >= most_downloaded[1].times_downloaded

    def test_highest_rated_query(self, db_session, test_games):
        """Test highest rated games query."""
        highest_rated = db.session.execute(select(Game).filter(Game.rating != None).order_by(Game.rating.desc()).limit(8)).scalars().all()
        
        assert len(highest_rated) >= 4  # 4 games with ratings in our fixture
        
        # Check that all returned games have ratings
        assert all(game.rating is not None for game in highest_rated)
        
        # Check that games are ordered by rating desc
        if len(highest_rated) > 1:
            assert highest_rated[0].rating >= highest_rated[1].rating


def _discover_game(**overrides):
    """A game row shaped like the one `serialize_discover_game` reads.

    Deliberately not a `Mock`. The serializer grew a play-URL step that reads
    `full_disk_path` and hands it to `os.path.abspath`; a Mock invents that
    attribute on demand, so the undeclared field arrived as a Mock object
    instead of failing as a missing one. A namespace can only supply what the
    test actually states.

    `Mock(name=...)` was a second trap here: `name` is consumed by the Mock
    constructor, so `game.name` was never the string these tests appeared to
    set — it reached the cover-placeholder code as a Mock.
    """
    fields = {
        'id': 1,
        'uuid': 'discover-game',
        'name': 'Discover Game',
        'summary': 'Summary',
        'url': None,
        'size': 0,
        'genres': [],
        'first_release_date': None,
        'date_identified': None,
        'date_created': None,
        'freshness_status': None,
        'updates': [],
        'full_disk_path': None,
        'library': None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestGameDetails:
    """Test game details functionality."""

    @patch('oneirodex.utils.discover_projections.game_card_flags')
    def test_discover_game_data_matches_shared_card_shape(
        self, mock_game_card_flags, tmp_path
    ):
        from oneirodex.routes_discover import serialize_discover_game

        # root_path decides where cover placeholders are rendered. Plain
        # `Flask(__name__)` puts it at tests/, so a resolved title wrote a real
        # JPEG into tests/static/library/generated/covers/ in the checkout.
        app = Flask(__name__, root_path=str(tmp_path))
        mock_game_card_flags.return_value = {'is_vr': True}
        game = _discover_game(url='https://example.test/game', size=1024)

        # What this test is about is the card *shape* — that the serializer
        # passes the resolver's answer through. Whether a local cover file is
        # on disk is resolve_cover_url's own contract, covered in
        # test_utils_cover_url.py, and depending on it here made the assertion
        # a statement about the developer's filesystem.
        with app.test_request_context(), patch(
            'oneirodex.utils.discover_projections.resolve_game_cover_url',
            return_value='/static/library/images/cover.jpg',
        ):
            result = serialize_discover_game(
                game,
                SimpleNamespace(url='cover.jpg', download_url='', is_downloaded=True),
                is_favorite=True,
                has_local_override=True,
            )

        assert result['cover_url'] == '/static/library/images/cover.jpg'
        assert result['is_favorite'] is True
        assert result['has_local_override'] is True
        assert result['is_vr'] is True
        assert result['lifecycle_state'] == 'not_downloaded'
        assert result['client_connected'] is False

    def test_discover_game_data_preserves_static_cover_url(self, tmp_path):
        from oneirodex.routes_discover import serialize_discover_game

        # Same reason as above: cover resolution runs for real here, and its
        # placeholder step writes to root_path.
        app = Flask(__name__, root_path=str(tmp_path))
        game = _discover_game()

        # No patching here: an already-app-static cover URL passing through
        # untouched is exactly the behaviour under test.
        with app.test_request_context():
            result = serialize_discover_game(
                game,
                SimpleNamespace(
                    url='/static/covers/discover.jpg',
                    download_url='',
                    is_downloaded=False,
                ),
                is_favorite=False,
                has_local_override=False,
            )

        assert result['cover_url'] == '/static/covers/discover.jpg'

    def test_game_cover_image_query(self, db_session, test_games, test_images):
        """Test that cover images are queried correctly for games."""
        game_with_image = test_games[0]  # First game has an image
        game_without_image = test_games[4]  # Last game has no image
        
        # Test game with cover image
        cover_image = db.session.execute(select(Image).filter_by(game_uuid=game_with_image.uuid, image_type='cover')).scalars().first()
        assert cover_image is not None
        assert '/static/covers/' in cover_image.url
        
        # Test game without cover image
        no_cover = db.session.execute(select(Image).filter_by(game_uuid=game_without_image.uuid, image_type='cover')).scalars().first()
        assert no_cover is None

    def test_game_attributes(self, test_games):
        """Test that games have the expected attributes for the discover page."""
        game = test_games[0]
        
        # Check required attributes exist
        assert hasattr(game, 'id')
        assert hasattr(game, 'uuid')
        assert hasattr(game, 'name')
        assert hasattr(game, 'summary')
        assert hasattr(game, 'url')
        assert hasattr(game, 'size')
        assert hasattr(game, 'genres')
        assert hasattr(game, 'first_release_date')
        
        # Check values
        assert game.name.startswith('Test Game')
        assert game.summary.startswith('Test summary')
        assert isinstance(game.size, int)


class TestContextProcessor:
    """Test the context processor functionality."""

    @patch('oneirodex.routes_discover.get_global_settings')
    def test_inject_settings_context_processor(self, mock_get_global_settings, app):
        """Test that the context processor injects global settings."""
        mock_settings = {'theme': 'default', 'site_name': 'Oneirodex'}
        mock_get_global_settings.return_value = mock_settings
        
        with app.app_context():
            from oneirodex.routes_discover import inject_settings
            result = inject_settings()
            
        assert result == mock_settings


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_game_with_none_first_release_date(self, db_session, test_libraries):
        """Test handling of games with None first_release_date."""
        library = test_libraries[0]
        game = Game(
            name='Game with None date',
            summary='Test summary',
            first_release_date=None,
            library_uuid=library.uuid
        )
        db_session.add(game)
        db_session.commit()
        
        # Should not raise an error when formatting the date
        assert game.first_release_date is None
        # The route should handle this gracefully

    def test_game_with_none_rating(self, db_session, test_libraries):
        """Test handling of games with None rating."""
        library = test_libraries[0]
        game = Game(
            name='Game with None rating',
            summary='Test summary',
            rating=None,
            library_uuid=library.uuid
        )
        db_session.add(game)
        db_session.commit()
        
        # Should not raise an error
        assert game.rating is None
        
        # Query should work properly with None ratings
        games_with_ratings = db.session.execute(select(Game).filter(Game.rating != None)).scalars().all()
        assert game not in games_with_ratings
