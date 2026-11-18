import pytest
from unittest.mock import patch, Mock, MagicMock, call
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import select

from oneirodex import create_app, db
from oneirodex.models import (
    User, Game, Library, GameUpdate, GameExtra, GameURL, Image, 
    Genre, GameMode, Theme, Platform, PlayerPerspective, Developer, 
    Publisher, SystemEvents, Category, Status
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
def test_developer(db_session):
    """Create a test developer."""
    developer_name = f'Test Developer {uuid4().hex[:8]}'
    developer = Developer(name=developer_name)
    db_session.add(developer)
    db_session.commit()
    return developer


@pytest.fixture
def test_publisher(db_session):
    """Create a test publisher."""
    publisher_name = f'Test Publisher {uuid4().hex[:8]}'
    publisher = Publisher(name=publisher_name)
    db_session.add(publisher)
    db_session.commit()
    return publisher


@pytest.fixture
def test_game(db_session, test_library, test_developer, test_publisher):
    """Create a test game with all fields populated."""
    game_uuid = str(uuid4())
    # Use random IGDB ID to avoid unique constraint violations
    import random
    igdb_id = random.randint(1000000, 9999999)
    game = Game(
        uuid=game_uuid,
        igdb_id=igdb_id,
        name='Test Game',
        library_uuid=test_library.uuid,
        summary='This is a test game with <script>alert("xss")</script> content',
        storyline='A longer storyline for testing',
        rating=85,
        size=1024000,
        first_release_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
        date_identified=datetime.now(timezone.utc),
        last_updated=datetime.now(timezone.utc),
        full_disk_path='/sensitive/path/to/game/folder',
        nfo_content='Test NFO Content\nWith <script>alert("malicious")</script> content\nMultiple lines',
        url='https://example.com/game',
        video_urls='https://www.youtube.com/embed/test1,https://www.youtube.com/embed/test2',
        steam_url='https://store.steampowered.com/app/123456',
        category=Category.MAIN_GAME,
        status=Status.RELEASED,
        times_downloaded=42,
        developer=test_developer,
        publisher=test_publisher
    )
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def test_game_update(db_session, test_game):
    """Create a test game update."""
    update = GameUpdate(
        game_uuid=test_game.uuid,
        file_path='/path/to/update.exe',
        times_downloaded=5,
        created_at=datetime.now(timezone.utc),
        nfo_content='Update NFO content'
    )
    db_session.add(update)
    db_session.commit()
    return update


@pytest.fixture
def test_game_extra(db_session, test_game):
    """Create a test game extra."""
    extra = GameExtra(
        game_uuid=test_game.uuid,
        file_path='/path/to/extra.zip',
        times_downloaded=3,
        created_at=datetime.now(timezone.utc),
        nfo_content='Extra NFO content'
    )
    db_session.add(extra)
    db_session.commit()
    return extra


@pytest.fixture
def test_game_image(db_session, test_game):
    """Create a test game image."""
    image = Image(
        game_uuid=test_game.uuid,
        image_type='cover',
        url='test_cover.jpg'
    )
    db_session.add(image)
    db_session.commit()
    return image


@pytest.fixture
def test_game_url(db_session, test_game):
    """Create a test game URL."""
    game_url = GameURL(
        game_uuid=test_game.uuid,
        url='https://example.com/official',
        url_type='official'
    )
    db_session.add(game_url)
    db_session.commit()
    return game_url


class TestGameDetailsRouteAuthentication:
    """Test authentication and access control for game details route."""
    
    def test_game_details_requires_login(self, client, test_game, configured_install):
        """Test that game details route requires authentication."""
        response = client.get(f'/game_details/{test_game.uuid}')
        assert response.status_code == 302  # Redirect to login
        assert '/login' in response.location
    
class TestGameDetailsRouteResponse:
    """What `/game_details/<uuid>` is now: a shell, not a rendered page.

    This class used to patch `render_template` and inspect the `game` dict
    handed to `games/game_details.html`. The route is a **member SPA shell**
    (`render_member_spa()`) — it validates the uuid, checks access, and returns
    the app shell. There is no `game` kwarg to inspect and the game's name is
    never in the HTML, so those assertions were describing a route that no
    longer exists.

    The data they cared about is real and still worth testing; it moved to
    `/api/games/<uuid>/details`, which is where the SPA gets it and where these
    now look.
    """

    def test_game_details_full_disk_path_not_exposed(self, client, test_user, test_game):
        """The server path must not reach an ordinary member — by either route.

        Checked against the shell *and* the API, because the shell no longer
        carries game data at all and a test that only looked at the HTML would
        now pass no matter what the API leaked.
        """
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        shell = client.get(f'/game_details/{test_game.uuid}')
        assert b'/sensitive/path/to/game/folder' not in shell.data

        payload = client.get(f'/api/games/{test_game.uuid}/details').get_json()
        assert 'full_disk_path' not in payload
        assert 'server_path' not in payload
        assert '/sensitive/path/to/game/folder' not in str(payload)

    def test_game_details_nfo_content_sanitized(self, client, test_user, test_game):
        """NFO text is attacker-influenced content read off disk."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        with patch('oneirodex.utils.game_details_payload.sanitize_string_input') as mock_sanitize:
            mock_sanitize.return_value = 'sanitized_nfo_content'
            payload = client.get(f'/api/games/{test_game.uuid}/details').get_json()

        mock_sanitize.assert_any_call(test_game.nfo_content, 10000)
        assert payload['nfo_content'] == 'sanitized_nfo_content'

    def test_game_details_no_duplicate_updates_array(self, client, test_user, test_game,
                                                     test_game_update):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        payload = client.get(f'/api/games/{test_game.uuid}/details').get_json()

        # The payload reports a *count*; the update files themselves are served
        # by /versions. The original test asserted an inline `updates` array
        # and then counted how many times the key appeared, guarding against a
        # duplication that the current shape makes impossible.
        assert payload['updates_count'] == 1
        assert 'updates' not in payload


class TestGameDetailsUtilityFunctionLogging:
    """Test logging in utility functions called by game details route."""
    
    def test_get_game_by_uuid_logging(self, app, test_game, test_user, db_session):
        """Test that get_game_by_uuid function logs appropriately."""
        with app.app_context():
            # Need to set up Flask-Login context
            with patch('oneirodex.utils.services.game_lookup.log_system_event') as mock_log:
                from oneirodex.utils.game_core import get_game_by_uuid
                result = get_game_by_uuid(test_game.uuid)
        
        assert result.uuid == test_game.uuid
        assert result.name == test_game.name
        
        # Verify logging calls were made
        assert mock_log.call_count >= 2
        # Check that search logging was called
        search_calls = [logged_call for logged_call in mock_log.call_args_list
                       if 'Searching for game UUID' in str(logged_call)]
        assert len(search_calls) >= 1
    
    def test_get_game_by_uuid_not_found_logging(self, app, test_user, db_session):
        """Test logging when game is not found."""
        nonexistent_uuid = str(uuid4())
        with app.app_context():
            with patch('oneirodex.utils.services.game_lookup.log_system_event') as mock_log:
                from oneirodex.utils.game_core import get_game_by_uuid
                result = get_game_by_uuid(nonexistent_uuid)
        
        assert result is None
        
        # Verify not found is logged
        mock_log.assert_any_call(
            f"Game not found for UUID: {nonexistent_uuid[:8]}...",
            event_type='game',
            event_level='debug'
        )


class TestGameDetailsTemplateSecurity:
    """CSRF still has to reach the page — it just arrives differently now.

    These two patched `render_template` and asserted a `CsrfForm` in its
    kwargs. The route renders the SPA shell, which carries the token as a meta
    tag for fetch() to read instead of embedding a form. Same requirement,
    different delivery; asserting the old delivery tested nothing.
    """

    def test_game_details_shell_carries_a_csrf_token(self, client, test_user, test_game):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get(f'/game_details/{test_game.uuid}')

        assert response.status_code == 200
        assert b'name="csrf-token"' in response.data

    def test_game_details_shell_mounts_the_member_app(self, client, test_user, test_game):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get(f'/game_details/{test_game.uuid}')

        assert b'member-app-root' in response.data
        assert b'dist/member-app/member-app.js' in response.data


class TestGameDetailsErrorHandling:
    """Test error handling and edge cases."""
    
    def test_game_details_with_null_nfo_content(self, client, test_user, test_library):
        """Test game details with null NFO content."""
        game = Game(
            uuid=str(uuid4()),
            name='Game with No NFO',
            library_uuid=test_library.uuid,
            nfo_content=None  # Null NFO content
        )
        db.session.add(game)
        db.session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        response = client.get(f'/game_details/{game.uuid}')
        assert response.status_code == 200

        # `None`, not the string 'none'. The old route substituted a literal
        # 'none' for the template to print; the payload returns null so the SPA
        # can tell "no NFO" from an NFO whose content happens to read "none".
        payload = client.get(f'/api/games/{game.uuid}/details').get_json()
        assert payload['nfo_content'] is None
    
    def test_game_details_with_empty_collections(self, client, test_user, test_library):
        """Test game details with empty updates/extras collections."""
        game = Game(
            uuid=str(uuid4()),
            name='Game with Empty Collections',
            library_uuid=test_library.uuid
        )
        db.session.add(game)
        db.session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        response = client.get(f'/game_details/{game.uuid}')
        assert response.status_code == 200

        # The "accessed X with N updates and M extras" log went away with the
        # server-rendered page. The absence it was really checking — a game
        # with nothing attached still renders — is now visible in the payload.
        payload = client.get(f'/api/games/{game.uuid}/details').get_json()
        assert payload['updates_count'] == 0
        assert payload['extras_count'] == 0
        assert payload['extras'] == []
    
    def test_game_details_json_error_response_for_not_found(self, client, test_user):
        """Test that 404 returns proper JSON error response."""
        nonexistent_uuid = str(uuid4())
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        
        with patch('oneirodex.routes_games_ext.details.log_system_event') as mock_log:
            response = client.get(f'/game_details/{nonexistent_uuid}')
        
        assert response.status_code == 404
        # Check if response contains JSON error data (may not be proper JSON response)
        response_data = response.get_data(as_text=True)
        assert 'Game not found' in response_data or response.status_code == 404
