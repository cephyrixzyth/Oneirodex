import pytest
from oneirodex.models import GlobalSettings, User
from oneirodex import db
from uuid import uuid4
import time
from unittest.mock import patch

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures('reusable_secret_keyring'),
]


@pytest.fixture
def admin_user(db_session):
    """Create an admin user."""
    admin_uuid = str(uuid4())
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=admin_uuid,
        name=f'TestAdmin_{unique_id}',
        email=f'admin_{unique_id}@test.com',
        role='admin',
        is_email_verified=True
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin

@pytest.fixture
def regular_user(db_session):
    """Create a regular user."""
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
def clean_global_settings(db_session):
    """Clean GlobalSettings and create a fresh one."""
    # Clear any existing settings
    db_session.execute(db.delete(GlobalSettings))
    db_session.commit()
    
    settings = GlobalSettings(
        igdb_client_id='test_client_id',
        igdb_client_secret='test_client_secret'
    )
    db_session.add(settings)
    db_session.commit()
    return settings

@pytest.fixture
def clean_db(db_session):
    """Clean GlobalSettings table."""
    # Clear any existing settings
    db_session.execute(db.delete(GlobalSettings))
    db_session.commit()


class TestIGDBSettingsRoute:
    
    def test_igdb_settings_requires_login(self, client, configured_install):
        """Test that IGDB settings requires login."""
        response = client.get('/admin/igdb_settings')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_igdb_settings_requires_admin(self, client, regular_user):
        """Test that IGDB settings requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/admin/igdb_settings')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_igdb_settings_get_admin_access(self, client, admin_user):
        """Test that admin can access IGDB settings page."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/admin/igdb_settings')
        assert response.status_code == 200
    
    def test_igdb_settings_get_with_existing_settings(self, client, admin_user, clean_global_settings):
        """Test GET request displays existing IGDB settings."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/admin/igdb_settings')
        assert response.status_code == 200
        # The React settings route is served from the shared admin shell.
        response_data = response.get_data(as_text=True)
        assert 'id="admin-app-root"' in response_data
        assert 'admin_manage_igdb_settings.html' not in response_data
    
    def test_igdb_settings_get_no_existing_settings(self, client, admin_user):
        """Test GET request when no settings exist."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/admin/igdb_settings')
        assert response.status_code == 200
    
    def test_igdb_settings_post_create_new_settings(self, client, admin_user, clean_db):
        """Test POST request creates new settings when none exist."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        test_data = {
            'igdb_client_id': 'new_client_id',
            'igdb_client_secret': 'new_client_secret'
        }
        
        response = client.post('/admin/igdb_settings', 
                             json=test_data,
                             content_type='application/json')
        
        assert response.status_code == 200
        response_data = response.get_json()
        assert response_data['status'] == 'success'
        assert 'updated successfully' in response_data['message']
        
        # Verify settings were created in database
        settings = db.session.execute(db.select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
        assert settings is not None
        assert settings.igdb_client_id == 'new_client_id'
        from oneirodex.utils.secret_store import read_global_secret
        assert read_global_secret(settings, 'igdb_client_secret') == 'new_client_secret'
    
    def test_igdb_settings_post_update_existing_settings(self, client, admin_user, clean_global_settings):
        """Test POST request updates existing settings."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        test_data = {
            'igdb_client_id': 'updated_client_id',
            'igdb_client_secret': 'updated_client_secret'
        }
        
        response = client.post('/admin/igdb_settings', 
                             json=test_data,
                             content_type='application/json')
        
        assert response.status_code == 200
        response_data = response.get_json()
        assert response_data['status'] == 'success'
        
        # Verify settings were updated in database
        db.session.refresh(clean_global_settings)
        assert clean_global_settings.igdb_client_id == 'updated_client_id'
        from oneirodex.utils.secret_store import read_global_secret
        assert read_global_secret(clean_global_settings, 'igdb_client_secret') == 'updated_client_secret'
    
    def test_igdb_settings_post_partial_data(self, client, admin_user, clean_db):
        """Test POST request with partial data."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        test_data = {
            'igdb_client_id': 'only_client_id'
            # Missing igdb_client_secret
        }
        
        response = client.post('/admin/igdb_settings', 
                             json=test_data,
                             content_type='application/json')
        
        assert response.status_code == 200
        response_data = response.get_json()
        assert response_data['status'] == 'success'
        
        # Verify settings were saved
        settings = db.session.execute(db.select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
        assert settings.igdb_client_id == 'only_client_id'
        assert settings.igdb_client_secret is None
    
    def test_igdb_settings_post_empty_data(self, client, admin_user):
        """Test POST request with empty data."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/igdb_settings', 
                             json={},
                             content_type='application/json')
        
        assert response.status_code == 200
        response_data = response.get_json()
        assert response_data['status'] == 'success'
    
    def test_igdb_settings_post_database_error(self, client, admin_user, global_settings):
        """Test POST request handles database errors."""
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        test_data = {
            'igdb_client_id': 'test_id',
            'igdb_client_secret': 'test_secret'
        }
        
        # Fail only the request's settings write. The signed-in client also commits
        # its own transaction after dispatch to persist the synthetic session.
        from sqlalchemy import event
        from sqlalchemy.orm import Session

        original_id = global_settings.igdb_client_id

        def fail_settings_commit(session):
            if any(isinstance(row, GlobalSettings) and row.igdb_client_id == 'test_id'
                   for row in session.dirty):
                raise RuntimeError('Database error')

        event.listen(Session, 'before_commit', fail_settings_commit)
        try:
            response = client.post('/admin/igdb_settings', json=test_data)
        finally:
            event.remove(Session, 'before_commit', fail_settings_commit)

        assert response.status_code == 500
        response_data = response.get_json()
        assert response_data['ok'] is False
        assert response_data['success'] is False
        assert response_data['message'] == 'Could not save IGDB settings'
        db.session.refresh(global_settings)
        assert global_settings.igdb_client_id == original_id
    
    def test_igdb_settings_post_invalid_json(self, client, admin_user):
        """Test POST request with invalid JSON."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/igdb_settings', 
                             data='invalid json',
                             content_type='application/json')
        
        assert response.status_code == 400
        assert response.get_data(as_text=True) == (
            '<!doctype html>\n<html lang=en>\n<title>400 Bad Request</title>\n'
            '<h1>Bad Request</h1>\n'
            '<p>The browser (or proxy) sent a request that this server could not understand.</p>\n'
        )


class TestIGDBTestRoute:
    
    def test_test_igdb_requires_login(self, client, configured_install):
        """Test that IGDB test requires login."""
        response = client.post('/admin/test_igdb')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_test_igdb_requires_admin(self, client, regular_user):
        """Test that IGDB test requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/test_igdb')
        assert response.status_code == 302
        assert 'login' in response.location
    
    def test_test_igdb_no_settings(self, client, admin_user):
        """Test IGDB test when no settings exist."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/test_igdb')
        assert response.status_code == 400
        response_data = response.get_json()
        assert response_data['ok'] is False
        assert response_data['success'] is False
        assert 'not configured' in response_data['message']
    
    def test_test_igdb_incomplete_settings(self, client, admin_user):
        """Test IGDB test with incomplete settings."""
        # Configure the singleton rather than inserting a second row — the
        # secret is cleared explicitly because the row may carry one from an
        # earlier test, and "incomplete" is the whole point here.
        from oneirodex.utils.global_settings import global_settings_row_or_create

        settings = global_settings_row_or_create()
        settings.igdb_client_id = 'test_id'
        settings.igdb_client_secret = None
        db.session.commit()
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/test_igdb')
        assert response.status_code == 400
        response_data = response.get_json()
        assert response_data['ok'] is False
        assert response_data['success'] is False
        assert 'not configured' in response_data['message']
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_test_igdb_successful_api_call(self, mock_api_request, client, admin_user, clean_global_settings):
        """Test successful IGDB API test."""
        # Mock successful API response
        mock_api_request.return_value = [{'name': 'Test Game'}]
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/test_igdb')
        assert response.status_code == 200
        response_data = response.get_json()
        assert response_data['status'] == 'success'
        assert 'successful' in response_data['message']
        
        # Verify API was called with correct parameters
        mock_api_request.assert_called_once_with(
            'https://api.igdb.com/v4/games', 
            'fields name; limit 1;'
        )
        
        # Verify last_tested timestamp was updated
        db.session.refresh(clean_global_settings)
        assert clean_global_settings.igdb_last_tested is not None
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_test_igdb_invalid_api_response(self, mock_api_request, client, admin_user, clean_global_settings):
        """Test IGDB test with invalid API response."""
        # Mock invalid API response (not a list)
        mock_api_request.return_value = {'error': 'Invalid response'}
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/test_igdb')
        assert response.status_code == 500
        response_data = response.get_json()
        assert response_data['ok'] is False
        assert response_data['success'] is False
        assert 'Invalid API response' in response_data['message']
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_test_igdb_api_exception(self, mock_api_request, client, admin_user, clean_global_settings):
        """Test IGDB test when API call raises exception."""
        # Mock API request to raise an exception
        mock_api_request.side_effect = Exception("API connection failed")
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/test_igdb')
        assert response.status_code == 500
        response_data = response.get_json()
        assert response_data['ok'] is False
        assert response_data['success'] is False
        assert response_data['message'] == 'IGDB API test failed'
    
    def test_test_igdb_get_method_not_allowed(self, client, admin_user):
        """Test that GET method is not allowed for IGDB test."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/admin/test_igdb')
        assert response.status_code == 405  # Method Not Allowed


class TestIGDBIntegration:
    
    @patch('oneirodex.utils.igdb_api.make_igdb_api_request', return_value=[{'name': 'Test Game'}])
    def test_igdb_settings_and_test_workflow(self, mock_api_request, client, admin_user):
        """Test complete workflow: set settings then test them."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # First, set IGDB settings
        settings_data = {
            'igdb_client_id': 'workflow_client_id',
            'igdb_client_secret': 'workflow_client_secret'
        }
        
        settings_response = client.post('/admin/igdb_settings', 
                                      json=settings_data,
                                      content_type='application/json')
        assert settings_response.status_code == 200
        
        test_response = client.post('/admin/test_igdb')
        assert test_response.status_code == 200
        assert test_response.get_json()['status'] == 'success'
        mock_api_request.assert_called_once_with(
            'https://api.igdb.com/v4/games', 'fields name; limit 1;',
        )

    def test_legacy_and_current_igdb_settings_routes_share_configuration(self, client, admin_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        saved = client.post('/admin/igdb_settings', json={
            'igdb_client_id': 'legacy-client', 'igdb_client_secret': 'legacy-secret',
        })
        assert saved.status_code == 200
        current = client.get('/api/admin/igdb/settings')
        assert current.status_code == 200
        assert current.get_json()['settings']['igdb_client_id'] == 'legacy-client'
        assert current.get_json()['settings']['secret_present'] is True
        assert 'legacy-secret' not in current.get_data(as_text=True)

    @patch('oneirodex.utils.igdb_api.make_igdb_api_request')
    def test_igdb_last_tested_timestamp_update(self, mock_api_request, client, admin_user, clean_global_settings):
        """Test that igdb_last_tested timestamp is properly updated."""
        # Mock successful API response
        mock_api_request.return_value = [{'name': 'Test Game'}]
        
        # Record original timestamp
        original_timestamp = clean_global_settings.igdb_last_tested
        
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # Small delay to ensure timestamp difference
        time.sleep(0.01)
        
        response = client.post('/admin/test_igdb')
        assert response.status_code == 200
        
        # Verify timestamp was updated
        db.session.refresh(clean_global_settings)
        assert clean_global_settings.igdb_last_tested != original_timestamp
        assert clean_global_settings.igdb_last_tested is not None
    
    def test_igdb_settings_persistence(self, client, admin_user, clean_db):
        """Test that IGDB settings persist correctly."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # Set settings
        settings_data = {
            'igdb_client_id': 'persist_client_id',
            'igdb_client_secret': 'persist_client_secret'
        }
        
        client.post('/admin/igdb_settings', 
                   json=settings_data,
                   content_type='application/json')
        
        # Retrieve settings via GET request
        response = client.get('/admin/igdb_settings')
        assert response.status_code == 200
        
        # Verify settings are still in database
        settings = db.session.execute(db.select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
        assert settings.igdb_client_id == 'persist_client_id'
        from oneirodex.utils.secret_store import read_global_secret
        assert read_global_secret(settings, 'igdb_client_secret') == 'persist_client_secret'
