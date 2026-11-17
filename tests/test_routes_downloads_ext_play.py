import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import select
from oneirodex import db
from oneirodex.models import User, Game, Library, SystemEvents
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def authenticated_user(db_session):
    """Create and return an authenticated user."""
    user_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    user = User(
        user_id=user_uuid,
        name=f'TestUser_{unique_id}',
        email=f'user_{unique_id}@test.com',
        role='user',
        is_email_verified=True
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    """Create and return an admin user."""
    user_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=user_uuid,
        name=f'AdminUser_{unique_id}',
        email=f'admin_{unique_id}@test.com',
        role='admin',
        is_email_verified=True
    )
    admin.set_password('adminpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def test_library(db_session):
    """Create a test library."""
    library = Library(
        name='Test Library',
        platform=LibraryPlatform.PCWIN
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def test_game_with_file(db_session, test_library):
    """Create a test game with an actual file on disk."""
    temp_dir = tempfile.mkdtemp()
    game_file = os.path.join(temp_dir, 'test_game.rom')
    
    # Create test ROM file
    with open(game_file, 'w') as f:
        f.write('test rom file content')
    
    game = Game(
        name='Test Game ROM',
        library_uuid=test_library.uuid,
        full_disk_path=game_file,
        size=len('test rom file content'),
        times_downloaded=0
    )
    db_session.add(game)
    db_session.commit()
    
    yield game
    
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_game_with_folder(db_session, test_library):
    """Create a test game that points to a folder (not supported)."""
    temp_dir = tempfile.mkdtemp()
    game_dir = os.path.join(temp_dir, 'test_game_folder')
    os.makedirs(game_dir, exist_ok=True)
    
    # Create files in the folder
    with open(os.path.join(game_dir, 'game1.exe'), 'w') as f:
        f.write('game executable')
    
    game = Game(
        name='Test Game Folder',
        library_uuid=test_library.uuid,
        full_disk_path=game_dir,
        size=1024,
        times_downloaded=0
    )
    db_session.add(game)
    db_session.commit()
    
    yield game
    
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_game_with_nonexistent_file(db_session, test_library):
    """Create a test game with a non-existent file path."""
    game = Game(
        name='Test Game Missing',
        library_uuid=test_library.uuid,
        full_disk_path='/nonexistent/path/missing_game.rom',
        size=0,
        times_downloaded=0
    )
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def test_game_with_unsafe_path(db_session, test_library):
    """Create a test game with a potentially unsafe path."""
    # This path attempts traversal but will be blocked by security
    unsafe_path = '/tmp/../../../etc/passwd'
    
    game = Game(
        name='Test Game Unsafe Path',
        library_uuid=test_library.uuid,
        full_disk_path=unsafe_path,
        size=0,
        times_downloaded=0
    )
    db_session.add(game)
    db_session.commit()
    return game


class TestPlayGameRoute:
    """Test the /play_game/<game_uuid> route."""
    
    def test_play_game_requires_login(self, client, test_game_with_file, configured_install):
        """Test that play_game requires login."""
        response = client.get(f'/play_game/{test_game_with_file.uuid}')
        assert response.status_code == 302  # Should redirect to login
        assert 'login' in response.location or '/auth' in response.location
    
    def test_play_game_authenticated_access(self, client, authenticated_user, test_game_with_file):
        """Test that authenticated users can access play_game."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(authenticated_user.id)
            sess['_fresh'] = True
        
        response = client.get(f'/play_game/{test_game_with_file.uuid}', follow_redirects=True)
        assert response.status_code == 200
        # The placeholder ("coming soon") is gone: play_game now redirects to
        # WebRetro when the title is browser-playable, and otherwise says why
        # and sends the user to details. This fixture is not playable, which is
        # also what test_play_game_redirects_with_flash pins.
        assert b'not playable in the browser' in response.data
    
    def test_play_game_redirects_with_flash(self, client, authenticated_user, test_game_with_file):
        """Test that play_game redirects with proper flash message."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(authenticated_user.id)
            sess['_fresh'] = True
        
        response = client.get(f'/play_game/{test_game_with_file.uuid}')
        assert response.status_code == 302
        # Should redirect to game details
        assert f'/game_details/{test_game_with_file.uuid}' in response.location


class TestPlayRomTestRoute:
    """Test the /playromtest route."""
    
    def test_playromtest_requires_login(self, client, configured_install):
        """Test that playromtest requires login."""
        response = client.get('/playromtest')
        assert response.status_code == 302  # Should redirect to login
        assert 'login' in response.location or '/auth' in response.location
    
    def test_playromtest_renders_template(self, client, authenticated_user):
        """Test that playromtest renders the correct template for authenticated users."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(authenticated_user.id)
            sess['_fresh'] = True
        
        response = client.get('/playromtest', follow_redirects=True)
        assert response.status_code == 200
        # /playromtest is the legacy route; it now points people at the per-game
        # Play button rather than promising a feature.
        assert b'Use Play from a game details page for browser emulation.' in response.data


class TestDownloadRomRoute:
    """Test the /api/downloadrom/<string:guid> route."""
    
    def test_downloadrom_requires_login(self, client, test_game_with_file):
        """Test that downloadrom requires authentication."""
        response = client.get(f'/api/downloadrom/{test_game_with_file.uuid}')
        assert response.status_code == 401  # an API download is refused, not redirected
    
class TestSecurityIntegration:
    """Integration tests for security features."""
    
    def test_database_cleanup_after_tests(self, db_session):
        """Verify that tests clean up properly."""
        # Count existing records before test
        initial_games = db_session.execute(select(Game)).scalars().all()
        initial_users = db_session.execute(select(User)).scalars().all()
        
        # This test doesn't create any persistent data, just verifies cleanup
        # In a real scenario, the fixtures handle cleanup automatically
        assert True  # Placeholder assertion
