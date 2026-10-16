"""
Unit tests for oneirodex.routes_apis.download

Tests the download API endpoints including authentication, authorization,
deletion functionality, security, and error handling.
"""

from sqlalchemy import text
import pytest
from unittest.mock import patch
from uuid import uuid4

from oneirodex.models import User, DownloadRequest, Game, Library, LibraryPlatform


def safe_cleanup_database(db_session):
    """Safely clean up database records respecting foreign key constraints.""" 
    from sqlalchemy import delete
    from oneirodex.models import SystemEvents
    
    # Clean up in order of dependencies
    db_session.execute(delete(DownloadRequest))
    db_session.execute(delete(SystemEvents))
    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.execute(delete(User))
    db_session.execute(delete(Library))
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
def admin_user(db_session):
    """Create a test admin user."""
    user_uuid = str(uuid4())
    user = User(
        name=f'adminuser_{user_uuid[:8]}',
        email=f'admin_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=user_uuid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=10
    )
    user.set_password('adminpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_library(db_session):
    """Create a sample library for testing."""
    library = Library(
        name='Test Library',
        platform=LibraryPlatform.PCWIN
    )
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def sample_game(db_session, sample_library):
    """Create a sample game for testing."""
    game = Game(
        name='Test Game',
        full_disk_path='/tmp/test_game_folder',
        library_uuid=sample_library.uuid
    )
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def sample_download_request(db_session, regular_user, sample_game):
    """Create a sample download request for testing."""
    download_request = DownloadRequest(
        user_id=regular_user.id,
        game_uuid=sample_game.uuid,
        status='completed',
        zip_file_path=None,
        download_size=1000.0
    )
    db_session.add(download_request)
    db_session.commit()
    return download_request




class TestDeleteDownloadRequest:
    """Test the api_delete_download_request API endpoint."""
    
    def test_delete_requires_login(self, client):
        """Test that delete_download requires user login."""
        response = client.delete('/api/delete_download/1')
        assert response.status_code == 302  # Redirect to login


    def test_delete_requires_admin(self, client, regular_user):
        """Test that delete_download requires admin privileges."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.delete('/api/delete_download/1')
        assert response.status_code == 302  # Redirect due to admin_required decorator
    
    def test_delete_invalid_request_id_negative(self, client, admin_user):
        """Test deletion with negative request ID - Flask routing returns 404."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.delete('/api/delete_download/-1')
        assert response.status_code == 404  # Flask routing handles this
    
    def test_delete_invalid_request_id_zero(self, client, admin_user):
        """Test deletion with zero request ID."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.delete('/api/delete_download/0')
        assert response.status_code == 400
        
        data = response.get_json()
        assert data['ok'] is False
        assert 'Invalid request ID' in data['error']
    
    def test_delete_nonexistent_request(self, client, admin_user):
        """Test deletion of non-existent download request."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.delete('/api/delete_download/99999')
        assert response.status_code == 404
    
    def test_delete_request_without_zip_file(self, client, admin_user, sample_download_request):
        """Test successful deletion of download request."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.delete(f'/api/delete_download/{sample_download_request.id}')
        assert response.status_code == 200

        data = response.get_json()
        assert data['ok'] is True
        assert 'deleted successfully' in data['message']
    
    def test_delete_request_with_zip_file_success(self, client, admin_user, sample_download_request):
        """Test successful deletion of download request (ZIP files no longer managed)."""
        # Set a zip_file_path to simulate old download request
        sample_download_request.zip_file_path = '/some/old/path.zip'

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.delete(f'/api/delete_download/{sample_download_request.id}')
        assert response.status_code == 200

        data = response.get_json()
        assert data['ok'] is True
        assert 'deleted successfully' in data['message']
    
    def test_delete_request_zip_outside_save_path(self, client, admin_user, sample_download_request):
        """Test deletion handles old ZIP paths gracefully."""
        # Set an external zip path (should be ignored with new system)
        sample_download_request.zip_file_path = '/external/path/file.zip'

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.delete(f'/api/delete_download/{sample_download_request.id}')
        assert response.status_code == 200

        data = response.get_json()
        assert data['ok'] is True
        assert 'deleted successfully' in data['message']
    
    def test_delete_request_zip_deletion_error(self, client, admin_user, sample_download_request):
        """Test deletion succeeds even with old ZIP file references."""
        sample_download_request.zip_file_path = '/some/file.zip'

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.delete(f'/api/delete_download/{sample_download_request.id}')
        assert response.status_code == 200

        data = response.get_json()
        assert data['ok'] is True
        assert 'deleted successfully' in data['message']
    
    @patch('oneirodex.routes_apis.download.db')
    def test_delete_request_database_error(self, mock_db, client, admin_user, sample_download_request):
        """Test handling of database errors during deletion."""
        mock_db.session.delete.side_effect = Exception("Database error")
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.delete(f'/api/delete_download/{sample_download_request.id}')
        assert response.status_code == 500
        
        data = response.get_json()
        assert data['ok'] is False
        assert 'Could not delete the download request' in data['error']
    
    @patch('oneirodex.routes_apis.download.log_system_event')
    def test_delete_request_logging(self, mock_log, client, admin_user, sample_download_request):
        """Test that proper logging occurs during deletion."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.delete(f'/api/delete_download/{sample_download_request.id}')
        assert response.status_code == 200
        
        # Verify logging calls
        mock_log.assert_called()
        log_calls = mock_log.call_args_list
        
        # Check for deletion and success log messages
        deletion_logged = any(
            'Deleting download request' in str(call) for call in log_calls
        )
        success_logged = any(
            'Successfully deleted download request' in str(call) for call in log_calls
        )
        
        assert deletion_logged
        assert success_logged


class TestAdminDownloadRequestList:
    def test_list_requires_login(self, client):
        response = client.get('/api/admin/download-requests')
        assert response.status_code == 302

    def test_list_requires_admin(self, client, regular_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        response = client.get('/api/admin/download-requests')
        assert response.status_code == 302

    def test_list_redacts_full_paths_and_keeps_job_details(self, client, admin_user, regular_user, sample_download_request):
        sample_download_request.zip_file_path = r'C:\private\archives\game.zip'
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        response = client.get('/api/admin/download-requests')
        assert response.status_code == 200
        body = response.get_json()
        row = body['requests'][0]
        assert row['id'] == sample_download_request.id
        assert row['file_name'] == 'game.zip'
        assert row['username'] == regular_user.name
        assert row['game_uuid'] == sample_download_request.game_uuid[:8]
        assert r'C:\private\archives' not in response.get_data(as_text=True)
    
