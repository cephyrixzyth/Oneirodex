import pytest
import json
from oneirodex.models import User, GlobalSettings
from oneirodex import cache
from uuid import uuid4


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
def global_settings(db_session):
    """Create a GlobalSettings record."""
    # Clear existing settings
    db_session.query(GlobalSettings).delete()
    db_session.commit()
    
    settings = GlobalSettings(
        settings={
            'showSystemLogo': True,
            'enableNewsletterFeature': False,
            'siteUrl': 'http://test.local'
        },
        enable_delete_game_on_disk=True,
        scan_thread_count=2,
        turbo_download_threads=10,
        turbo_download_batch_size=150
    )
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.fixture
def clean_settings(db_session):
    """Clean settings for isolated testing."""
    db_session.query(GlobalSettings).delete()
    db_session.commit()
    cache.clear()


class TestSettingsRoutes:
    """Test the settings route handlers."""
    
    def test_get_settings_requires_login(self, client, configured_install):
        """Test that GET settings requires login."""
        response = client.get('/admin/settings')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_get_settings_requires_admin(self, client, regular_user):
        """Test that GET settings requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/settings')
        assert response.status_code == 302

    def test_get_settings_success(self, client, admin_user, global_settings):
        """Test successful GET settings request."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/new_server_settings')
        assert response.status_code == 200

    def test_update_settings_requires_login(self, client):
        """Test that POST settings requires login."""
        response = client.post('/admin/settings', json={'test': 'data'})
        assert response.status_code == 302

    def test_update_settings_requires_admin(self, client, regular_user):
        """Test that POST settings requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True

        response = client.post('/admin/settings', json={'test': 'data'})
        assert response.status_code == 403

    def test_update_settings_invalid_json(self, client, admin_user):
        """Test POST settings with invalid JSON."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.post('/admin/settings', data='invalid json')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_update_settings_no_data(self, client, admin_user):
        """Test POST settings with no data."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        # Test with empty JSON object
        response = client.post('/admin/settings', json={})
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'No settings data provided' in data['error']

    def test_update_settings_validation_errors(self, client, admin_user):
        """Test POST settings with validation errors."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        invalid_data = {'scanThreadCount': 10}  # Invalid value
        response = client.post('/admin/settings', json=invalid_data)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['error_code'] == 'bad_request'
        assert 'bounds' in data['error']

class TestLegacyRouteHandler:
    """Test the legacy manage_settings route handler."""
    
    def test_legacy_route_get(self, client, admin_user, global_settings):
        """Test legacy route with GET method."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        response = client.get('/admin/new_server_settings')
        assert response.status_code == 200

    def test_legacy_route_post(self, client, admin_user, clean_settings):
        """Test legacy route with POST method."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        valid_data = {'showSystemLogo': False}
        response = client.post('/admin/settings', json=valid_data)
        assert response.status_code == 200


class TestSettingsIntegration:
    """Integration tests for settings functionality."""
    
    def test_complete_settings_workflow(self, client, admin_user, db_session, clean_settings):
        """Test complete settings workflow from GET to POST."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        # Step 1: GET initial settings
        response = client.get('/admin/new_server_settings')
        assert response.status_code == 200
        
        # Step 2: Update settings
        new_settings = {
            'showSystemLogo': False,
            'enableNewsletterFeature': True,
            'scanThreadCount': 3,
            'turboDownloadThreads': 12,
            'turboDownloadBatchSize': 250,
            'updateFolderName': 'game_updates',
            'extrasFolderName': 'game_extras',
            'siteUrl': 'https://mygames.local'
        }
        
        response = client.post('/admin/settings', json=new_settings)
        assert response.status_code == 200
        
        # Step 3: Verify database state
        settings_record = db_session.query(GlobalSettings).first()
        assert settings_record is not None
        assert settings_record.settings == new_settings
        assert settings_record.scan_thread_count == 3
        assert settings_record.turbo_download_threads == 12
        assert settings_record.turbo_download_batch_size == 250
        assert settings_record.update_folder_name == 'game_updates'
        assert settings_record.extras_folder_name == 'game_extras'
        assert settings_record.site_url == 'https://mygames.local'
        
        # Step 4: GET updated settings to verify
        response = client.get('/admin/new_server_settings')
        assert response.status_code == 200

    def test_settings_persistence(self, client, admin_user, db_session, clean_settings):
        """Test that settings persist across requests."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        # Create initial settings
        initial_settings = {
            'showSystemLogo': False,
            'scanThreadCount': 2,
            'updateFolderName': 'persistent_updates'
        }
        
        response = client.post('/admin/settings', json=initial_settings)
        assert response.status_code == 200
        
        # Update some settings
        updated_settings = {
            'showSystemLogo': True,  # Changed
            'scanThreadCount': 2,    # Unchanged
            'turboDownloadThreads': 15  # New field
        }
        
        response = client.post('/admin/settings', json=updated_settings)
        assert response.status_code == 200
        
        # Verify final state combines both updates
        settings_record = db_session.query(GlobalSettings).first()
        final_settings = settings_record.settings
        
        assert final_settings['showSystemLogo'] == True  # Updated value
        assert final_settings['scanThreadCount'] == 2    # Persistent value
        assert final_settings['turboDownloadThreads'] == 15  # New value
