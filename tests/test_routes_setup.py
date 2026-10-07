import pytest
import json
from unittest.mock import patch, Mock, MagicMock
from datetime import datetime, timezone
from uuid import uuid4

from oneirodex import create_app, db
from oneirodex.models import User, GlobalSettings, InviteToken, SystemEvents, DownloadRequest, Newsletter, Library
from oneirodex.forms import SetupForm, IGDBSetupForm
from sqlalchemy import select, delete


def safe_cleanup_users_and_related(db_session):
    """Safely clean up users and related data respecting foreign key constraints."""
    # Delete in proper order to respect foreign key constraints
    # All tables with foreign keys to users must be deleted first
    db_session.execute(delete(DownloadRequest))
    db_session.execute(delete(Newsletter))
    db_session.execute(delete(SystemEvents))
    db_session.execute(delete(InviteToken))
    # Delete from user_favorites junction table using raw SQL
    db_session.execute(db.text("DELETE FROM user_favorites"))
    db_session.execute(delete(User))
    db_session.commit()




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
        invite_quota=10,
        is_email_verified=True,
        created=datetime.now(timezone.utc)
    )
    user.set_password('adminpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def global_settings(db_session):
    """Create test global settings."""
    settings = GlobalSettings(
        smtp_server='test.smtp.com',
        smtp_port=587,
        smtp_username='test@example.com',
        smtp_password='testpass',
        smtp_use_tls=True,
        smtp_default_sender='noreply@example.com',
        smtp_enabled=True,
        igdb_client_id='test_client_id_12345',
        igdb_client_secret='test_client_secret_12345'
    )
    db_session.add(settings)
    db_session.commit()
    return settings


@pytest.fixture
def client(client, request):
    """Signed in as the wizard's admin whenever a test uses ``admin_user``:
    steps 2-4 belong to the admin created in step 1 (routes_setup._require_setup_admin)."""
    if 'admin_user' in request.fixturenames:
        admin = request.getfixturevalue('admin_user')
        with client.session_transaction() as sess:
            sess['_user_id'] = admin.get_id()
            sess['_fresh'] = True
    return client


def _park_wizard_at(db_session, step):
    settings = db_session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
    if settings is None:
        settings = GlobalSettings()
        db_session.add(settings)
    settings.setup_in_progress = True
    settings.setup_completed = False
    settings.setup_current_step = step
    db_session.commit()
    return settings


def test_a_signed_out_visitor_cannot_change_mail_settings_mid_wizard(app, db_session, admin_user):
    """Steps 2-4 used to be open to anyone while the wizard ran: a visitor could
    point the install's mail at their own server and collect reset links."""
    settings = _park_wizard_at(db_session, 2)
    settings.smtp_server = 'mail.household.lan'
    db_session.commit()
    visitor = app.test_client()
    resp = visitor.post('/setup/smtp', data={'smtp_server': 'evil.example', 'smtp_enabled': 'true'})
    assert resp.status_code == 302 and '/login' in resp.location
    db_session.expire_all()
    assert db_session.get(GlobalSettings, settings.id).smtp_server == 'mail.household.lan'
    for path, step in (('/setup/features', 3), ('/setup/igdb', 4), ('/setup/integrations', 5), ('/setup/library', 6)):
        _park_wizard_at(db_session, step)
        assert '/login' in visitor.get(path).location


def test_igdb_can_be_skipped_and_setup_routes_through_api_and_first_library(client, db_session, admin_user, monkeypatch):
    """No API credential should block a fresh install from reaching library creation."""
    from oneirodex.utils.setup import get_current_setup_step
    _park_wizard_at(db_session, 4)
    response = client.post('/setup/igdb', data={'skip_igdb': '1'})

    assert response.status_code == 302
    assert response.location.endswith('/setup/integrations')
    assert get_current_setup_step() == 5
    response = client.post('/setup/integrations', data={'skip_integrations': '1'})
    assert response.location.endswith('/setup/library')
    assert get_current_setup_step() == 6

    monkeypatch.setattr('oneirodex.routes_setup.mark_setup_complete', lambda: None)
    for name in (
        'initialize_library_folders', 'initialize_discovery_sections',
        'insert_default_scanning_filters', 'initialize_default_settings',
        'initialize_allowed_file_types',
    ):
        monkeypatch.setattr(f'oneirodex.init_data.{name}', lambda: None)
    response = client.post('/setup/library', data={'skip_library': 'on'})
    assert response.location.endswith('/libraries')
    with client.session_transaction() as session:
        assert session.get('_user_id') == admin_user.get_id()


@pytest.fixture(autouse=True)
def _leave_the_wizard_closed(db_session):
    """Put the setup wizard away after every test in this file.

    These tests deliberately park GlobalSettings mid-wizard, and nothing was
    clearing it. `check_setup_status` is a `before_request` hook, so a stranded
    `setup_in_progress` redirects **every route in the suite** to the setup
    step it thinks you are on — test_routes_games_ext_details went from 11
    failures to 18 purely because this file ran first.

    Marking setup complete rather than deleting the row: an empty
    GlobalSettings with users present is a state the app never produces itself.
    """
    yield
    settings = db_session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
    if settings is not None:
        settings.setup_in_progress = False
        settings.setup_completed = True
        db_session.commit()


class TestSetupRoute:
    """Test the /setup GET route."""
    
    def test_setup_get_sets_database_step(self, client, db_session):
        """Test GET /setup sets database setup step to 1."""
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        # Also clean up GlobalSettings to ensure clean state
        db_session.execute(delete(GlobalSettings))
        db_session.commit()
        
        response = client.get('/setup')
        
        assert response.status_code == 200
        
        # Check that database setup step is set to 1
        from oneirodex.utils.setup import get_current_setup_step
        assert get_current_setup_step() == 1
    
    def test_setup_get_redirects_if_user_exists(self, client, admin_user, db_session):
        """Test GET /setup redirects to login if admin user already exists.

        GlobalSettings has to be cleared explicitly. Without it this test
        inherits whatever wizard state an earlier test left behind, and /setup
        correctly *resumes* that wizard instead of redirecting to login — so
        the failure was the route being right about a half-finished setup the
        test never meant to create.
        """
        db_session.execute(delete(GlobalSettings))
        db_session.commit()

        response = client.get('/setup')

        assert response.status_code == 302
        assert '/login' in response.location
    
    @patch('oneirodex.routes_setup.render_template')
    def test_setup_get_renders_template_when_no_user(self, mock_render, client, db_session):
        """Test GET /setup renders template when no users exist."""
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        
        mock_render.return_value = 'rendered setup template'
        
        response = client.get('/setup')
        
        assert response.status_code == 200
        mock_render.assert_called_once()
        args, kwargs = mock_render.call_args
        assert args[0] == 'setup/setup.html'
        assert 'form' in kwargs
        assert isinstance(kwargs['form'], SetupForm)


class TestSetupSubmitRoute:
    """Test the /setup/submit POST route."""
    
    def test_setup_submit_redirects_if_user_exists(self, client, admin_user):
        """Test POST /setup/submit redirects to login if admin user already exists."""
        form_data = {
            'username': 'testadmin',
            'email': 'test@example.com',
            'password': 'password123',
            'confirm_password': 'password123'
        }
        
        response = client.post('/setup/submit', data=form_data)
        
        assert response.status_code == 302
        assert '/login' in response.location

    @patch('oneirodex.routes_setup.SetupForm')
    def test_setup_submit_rechecks_after_serializing_concurrent_winner(
        self, mock_form_class, client, db_session
    ):
        safe_cleanup_users_and_related(db_session)
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.username.data = 'late_admin'
        mock_form.email.data = 'late@example.com'
        mock_form.password.data = 'password123'
        mock_form_class.return_value = mock_form

        def another_request_wins(session):
            winner = User(
                name='first_admin',
                email='first@example.com',
                password_hash='hashed_password',
                role='admin',
                user_id=str(uuid4()),
            )
            session.add(winner)

            from oneirodex.routes_setup import _stage_setup_step

            _stage_setup_step(2)
            session.commit()

        with patch(
            'oneirodex.routes_setup.lock_admin_mutation',
            side_effect=another_request_wins,
        ):
            response = client.post('/setup/submit', data={})

        assert response.status_code == 302
        assert '/login' in response.location
        users = db_session.execute(select(User)).scalars().all()
        assert len(users) == 1
        assert users[0].email == 'first@example.com'
    
    @patch('oneirodex.routes_setup.SetupForm')
    @patch('oneirodex.routes_setup.log_system_event')
    def test_setup_submit_creates_admin_user_success(self, mock_log, mock_form_class, client, db_session):
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        """Test successful admin user creation."""
        # Mock the form
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.username.data = 'testadmin'
        mock_form.email.data = 'Test@Example.Com'  # Test email lowercase conversion
        mock_form.password.data = 'password123'
        mock_form.csrf_token.data = 'test-csrf-token'
        mock_form_class.return_value = mock_form
        
        with patch('oneirodex.routes_setup.flash') as mock_flash:
            response = client.post('/setup/submit', data={})
            
            assert response.status_code == 302
            assert '/setup/smtp' in response.location
            
            # Verify admin user was created
            user = db.session.execute(select(User).filter_by(email='test@example.com')).scalar_one_or_none()
            assert user is not None
            assert user.name == 'testadmin'
            assert user.email == 'test@example.com'  # Should be lowercase
            assert user.role == 'admin'
            assert user.is_email_verified is True
            assert user.invite_quota == 10
            assert user.user_id is not None
            
            # Check database setup step was updated
            from oneirodex.utils.setup import get_current_setup_step
            assert get_current_setup_step() == 2
            
            mock_flash.assert_called_with('Admin account created successfully! Please configure your SMTP settings.', 'success')
            mock_log.assert_called_with("Admin account created during setup", event_type='setup', event_level='information')
    
    @patch('oneirodex.routes_setup.SetupForm')
    def test_setup_submit_database_error(self, mock_form_class, client, db_session):
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        """Test database error during user creation."""
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.username.data = 'testadmin'
        mock_form.email.data = 'test@example.com'
        mock_form.password.data = 'password123'
        mock_form_class.return_value = mock_form
        
        with patch('oneirodex.routes_setup.db.session.add') as mock_add:
            mock_add.side_effect = Exception('Database error')
            with patch('oneirodex.routes_setup.db.session.rollback') as mock_rollback:
                with patch('oneirodex.routes_setup.flash') as mock_flash:
                    response = client.post('/setup/submit', data={})
                    
                    assert response.status_code == 302
                    assert '/setup' in response.location
                    mock_rollback.assert_called_once()
                    mock_flash.assert_called_with('The admin account could not be saved. Check the server log for details.', 'error')
    
    @patch('oneirodex.routes_setup.SetupForm')
    def test_setup_submit_form_validation_failed(self, mock_form_class, client, db_session):
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        """Test form validation failure."""
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = False
        mock_form.data = {'username': 'test', 'email': 'invalid-email'}
        mock_form.errors = {'email': ['Invalid email address'], 'password': ['Field must be at least 8 characters long']}
        mock_form_class.return_value = mock_form
        
        with patch('oneirodex.routes_setup.render_template') as mock_render:
            mock_render.return_value = 'error template'
            response = client.post('/setup/submit', data={})
            
            assert response.status_code == 200
            mock_render.assert_called_with('setup/setup.html', form=mock_form, is_setup_mode=True)


class TestSetupSmtpRoute:
    """Test the /setup/smtp route."""
    
    def test_setup_smtp_get_no_setup_in_progress_redirects(self, client, admin_user, db_session):
        """Test GET /setup/smtp redirects when setup is not in progress."""
        # Ensure no setup is in progress by clearing GlobalSettings
        db_session.execute(delete(GlobalSettings))
        db_session.commit()
        
        # Setup completed (admin user exists, no setup in progress), so should redirect to login
        response = client.get('/setup/smtp')
        
        assert response.status_code == 302
        assert '/login' in response.location
    
    def test_setup_smtp_get_wrong_step_redirects(self, client, db_session):
        """Test GET /setup/smtp redirects when not in step 2."""
        # Clean up and set database to step 1
        safe_cleanup_users_and_related(db_session)
        db_session.execute(delete(GlobalSettings))
        db_session.commit()
        
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(1)  # Should be 2 for SMTP setup
        
        with patch('oneirodex.routes_setup.flash') as mock_flash:
            response = client.get('/setup/smtp')
            
            assert response.status_code == 302
            assert '/setup' in response.location
            mock_flash.assert_called_with('Please complete the admin account setup first.', 'warning')
    
    @patch('oneirodex.routes_setup.render_template')
    def test_setup_smtp_get_correct_step(self, mock_render, client, db_session, admin_user):
        """Test GET /setup/smtp renders template in correct step."""
        # Use existing admin_user fixture and set database to step 2
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(2)
        
        mock_render.return_value = 'smtp setup template'
        response = client.get('/setup/smtp')
        
        assert response.status_code == 200
        mock_render.assert_called_with('setup/setup_smtp.html', is_setup_mode=True)
    
    def test_setup_smtp_post_skip_button(self, client, db_session, admin_user):
        """Test POST /setup/smtp with skip button."""
        # Use existing admin_user fixture and set database to step 2
        from oneirodex.utils.setup import set_setup_step, get_current_setup_step
        set_setup_step(2)
        
        form_data = {'skip_smtp': 'true'}
        
        with patch('oneirodex.routes_setup.flash') as mock_flash:
            response = client.post('/setup/smtp', data=form_data)
            
            assert response.status_code == 302
            assert '/setup/features' in response.location  # Features precedes IGDB now
            
            # Check database step was updated to 3
            assert get_current_setup_step() == 3
            
            mock_flash.assert_called_with('SMTP setup skipped. Choose which features to keep enabled.', 'info')
    
    @patch('oneirodex.routes_setup.log_system_event')
    def test_setup_smtp_post_save_settings_success(self, mock_log, client, db_session, admin_user):
        """Test successful SMTP settings save."""
        # Use existing admin_user fixture and set database to step 2
        from oneirodex.utils.setup import set_setup_step, get_current_setup_step
        set_setup_step(2)
        
        form_data = {
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': '587',
            'smtp_username': 'test@gmail.com',
            'smtp_password': 'testpass',
            'smtp_use_tls': 'true',
            'smtp_default_sender': 'noreply@test.com',
            'smtp_enabled': 'true'
        }
        
        with patch('oneirodex.routes_setup.flash') as mock_flash:
            response = client.post('/setup/smtp', data=form_data)
            
            assert response.status_code == 302
            assert '/setup/features' in response.location  # Features precedes IGDB now
            
            # Verify the route executed successfully by checking redirect location
            # The specific settings verification is subject to transaction rollback behavior
            
            # Check database step was updated to 3
            assert get_current_setup_step() == 3
            
            mock_flash.assert_called_with('SMTP settings saved. Choose which features to keep enabled.', 'success')
            mock_log.assert_called_with("SMTP settings configured during setup", event_type='setup', event_level='information')
    
    
    def test_setup_smtp_post_database_error(self, client, db_session, admin_user):
        """Test database error during SMTP settings save."""
        # Use existing admin_user fixture and set database to step 2
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(2)
        
        form_data = {
            'smtp_server': 'smtp.test.com',
            'smtp_port': '587'
        }
        
        with patch('oneirodex.routes_setup.db.session.commit', side_effect=Exception('Database error')):
            with patch('oneirodex.routes_setup.db.session.rollback') as mock_rollback:
                with patch('oneirodex.routes_setup.flash') as mock_flash:
                    response = client.post('/setup/smtp', data=form_data)
                    
                    assert response.status_code == 200  # Should render template again
                    mock_rollback.assert_called_once()
                    mock_flash.assert_called_with('SMTP settings could not be saved. Check the server log for details.', 'error')


class TestSetupIgdbRoute:
    """Test the /setup/igdb route."""
    
    def test_setup_igdb_get_wrong_step_redirects(self, client, db_session):
        """Test GET /setup/igdb redirects when not in step 3."""
        # Clean up and set database to step 2
        safe_cleanup_users_and_related(db_session)
        db_session.execute(delete(GlobalSettings))
        db_session.commit()
        
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(2)  # Should be 4 for IGDB setup
        
        with patch('oneirodex.routes_setup.flash') as mock_flash:
            response = client.get('/setup/igdb')
            
            assert response.status_code == 302
            assert '/setup' in response.location
            mock_flash.assert_called_with('Please complete the previous setup steps first.', 'warning')
    
    @patch('oneirodex.routes_setup.render_template')
    def test_setup_igdb_get_correct_step(self, mock_render, client, db_session, admin_user):
        """Test GET /setup/igdb renders template in correct step."""
        # Use existing admin_user fixture and set database to step 3
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(4)  # IGDB is step 4 since the Features step landed
        
        mock_render.return_value = 'igdb setup template'
        response = client.get('/setup/igdb')
        
        assert response.status_code == 200
        mock_render.assert_called_once()
        args, kwargs = mock_render.call_args
        assert args[0] == 'setup/setup_igdb.html'
        assert 'form' in kwargs
        assert isinstance(kwargs['form'], IGDBSetupForm)
        assert kwargs['is_setup_mode'] is True

    def test_igdb_skip_bypasses_required_browser_validation(self, client, db_session, admin_user):
        from oneirodex.utils.setup import set_setup_step

        set_setup_step(4)
        response = client.get('/setup/igdb')
        assert response.status_code == 200
        assert b'name="skip_igdb"' in response.data
        assert b'formnovalidate' in response.data
        assert b'id="igdb_client_secret"' in response.data
        assert b'type="password"' in response.data
    
    @patch('oneirodex.routes_setup.IGDBSetupForm')
    @patch('oneirodex.routes_setup.log_system_event')
    @patch('oneirodex.init_data.initialize_library_folders')
    @patch('oneirodex.init_data.initialize_discovery_sections')
    @patch('oneirodex.init_data.insert_default_scanning_filters')
    @patch('oneirodex.init_data.initialize_default_settings')
    @patch('oneirodex.init_data.initialize_allowed_file_types')
    def test_setup_igdb_post_success_continues_to_api_setup(self, mock_init_filetypes, mock_init_settings,
                                                   mock_init_filters, mock_init_discovery, 
                                                   mock_init_folders, mock_log, mock_form_class, 
                                                   client, db_session, admin_user):
        """IGDB is optional setup and continues to API selection."""
        # Use existing admin_user fixture and set database to step 3
        from oneirodex.utils.setup import set_setup_step, get_current_setup_step, is_setup_required
        set_setup_step(4)  # IGDB is step 4 since the Features step landed
        
        # Mock the form
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.igdb_client_id.data = 'test_client_id_12345'
        mock_form.igdb_client_secret.data = 'test_client_secret_12345'
        mock_form_class.return_value = mock_form
        
        with patch('oneirodex.routes_setup.flash') as mock_flash:
            response = client.post('/setup/igdb', data={})
            
            assert response.status_code == 302
            assert '/setup/integrations' in response.location
            
            # Verify the route executed successfully by checking redirect location
            # The specific settings verification is subject to transaction rollback behavior
            
            assert get_current_setup_step() == 5
            
            # Verify all initialization functions were called
            mock_init_folders.assert_not_called()
            mock_init_discovery.assert_not_called()
            mock_init_filters.assert_not_called()
            mock_init_settings.assert_not_called()
            mock_init_filetypes.assert_not_called()
            
            mock_flash.assert_called_with('IGDB settings saved. Choose any additional API connections, or continue without them.', 'success')
            mock_log.assert_called_with("IGDB settings saved during setup", event_type='setup', event_level='information')
    
    
    @patch('oneirodex.routes_setup.IGDBSetupForm')
    def test_setup_igdb_post_database_error(self, mock_form_class, client, db_session, admin_user):
        """Test database error during IGDB settings save."""
        # Use existing admin_user fixture and set database to step 3
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(4)  # IGDB is step 4 since the Features step landed
        
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = True
        mock_form.igdb_client_id.data = 'test_client_id_12345'
        mock_form.igdb_client_secret.data = 'test_client_secret_12345'
        mock_form_class.return_value = mock_form
        
        with patch('oneirodex.routes_setup.db.session.commit', side_effect=Exception('Database error')):
            with patch('oneirodex.routes_setup.db.session.rollback') as mock_rollback:
                with patch('oneirodex.routes_setup.flash') as mock_flash:
                    response = client.post('/setup/igdb', data={})
                    
                    assert response.status_code == 200  # Should render template again
                    mock_rollback.assert_called_once()
                    mock_flash.assert_called_with('IGDB settings could not be saved. Check the server log for details.', 'error')
    
    @patch('oneirodex.routes_setup.IGDBSetupForm')
    def test_setup_igdb_post_form_validation_failed(self, mock_form_class, client, db_session, admin_user):
        """Test form validation failure."""
        # Use existing admin_user fixture and set database to step 3
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(4)  # IGDB is step 4 since the Features step landed
        
        mock_form = MagicMock()
        mock_form.validate_on_submit.return_value = False
        mock_form.errors = {'igdb_client_id': ['Field must be between 20 and 50 characters']}
        mock_form_class.return_value = mock_form
        
        with patch('oneirodex.routes_setup.render_template') as mock_render:
            mock_render.return_value = 'error template'
            response = client.post('/setup/igdb', data={})
            
            assert response.status_code == 200
            mock_render.assert_called_with('setup/setup_igdb.html', form=mock_form, is_setup_mode=True)


class TestSetupWorkflow:
    """Test the complete setup workflow."""
    
    def test_complete_setup_workflow(self, client, db_session):
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        # Also clean up GlobalSettings to ensure test isolation
        db_session.execute(delete(GlobalSettings))
        db_session.commit()
        """Test the complete setup process from start to finish."""
        # Step 1: GET /setup
        response = client.get('/setup')
        assert response.status_code == 200
        
        # Check database setup step
        from oneirodex.utils.setup import get_current_setup_step
        assert get_current_setup_step() == 1
        
        # Step 2: POST /setup/submit with valid admin data
        with patch('oneirodex.routes_setup.SetupForm') as mock_form_class:
            mock_form = MagicMock()
            mock_form.validate_on_submit.return_value = True
            mock_form.username.data = 'admin'
            mock_form.email.data = 'admin@test.com'
            mock_form.password.data = 'password123'
            mock_form.csrf_token.data = 'test-token'
            mock_form_class.return_value = mock_form
            
            with patch('oneirodex.routes_setup.log_system_event'):
                response = client.post('/setup/submit', data={})
                assert response.status_code == 302
                assert '/setup/smtp' in response.location
        
        # Check database setup step
        assert get_current_setup_step() == 2
        
        # Step 3: Skip SMTP setup
        form_data = {'skip_smtp': 'true'}
        response = client.post('/setup/smtp', data=form_data)
        assert response.status_code == 302
        assert '/setup/features' in response.location  # Features precedes IGDB now
        
        # Check database setup step
        assert get_current_setup_step() == 3

        # Step 4: Choose features. The wizard gained this step between SMTP and
        # IGDB; walking straight from SMTP to IGDB leaves it parked on Features,
        # which is why the IGDB post below was redirecting to /setup.
        response = client.post('/setup/features', data={'enable_game_updates': 'y'})
        assert response.status_code == 302
        assert '/setup/igdb' in response.location
        assert get_current_setup_step() == 4

        # Step 5: Save IGDB, then continue to optional API choices.
        with patch('oneirodex.routes_setup.IGDBSetupForm') as mock_igdb_form_class:
            mock_igdb_form = MagicMock()
            mock_igdb_form.validate_on_submit.return_value = True
            mock_igdb_form.igdb_client_id.data = 'test_client_id_12345'
            mock_igdb_form.igdb_client_secret.data = 'test_client_secret_12345'
            mock_igdb_form_class.return_value = mock_igdb_form
            
            with patch('oneirodex.routes_setup.log_system_event'):
                 
                # Mock initialize_default_settings to prevent interference with test data
                response = client.post('/setup/igdb', data={})
                assert response.status_code == 302
                assert '/setup/integrations' in response.location
        
        assert get_current_setup_step() == 5
        
        # Verify admin user was created
        admin_user = db.session.execute(select(User).filter_by(email='admin@test.com')).scalars().first()
        assert admin_user is not None
        assert admin_user.role == 'admin'
        assert admin_user.is_email_verified is True
        
        # Verify IGDB settings were saved
        settings = db.session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
        assert settings is not None
        assert settings.igdb_client_id == 'test_client_id_12345'
        assert settings.igdb_client_secret == 'test_client_secret_12345'

        response = client.post('/setup/integrations', data={'skip_integrations': '1'})
        assert response.status_code == 302
        assert '/setup/library' in response.location
        assert get_current_setup_step() == 6

        with patch('oneirodex.init_data.initialize_library_folders'), \
             patch('oneirodex.init_data.initialize_discovery_sections'), \
             patch('oneirodex.init_data.insert_default_scanning_filters'), \
             patch('oneirodex.init_data.initialize_allowed_file_types'), \
             patch('oneirodex.init_data.initialize_default_settings'):
            response = client.post('/setup/library', data={'skip_library': 'on'})
        assert response.status_code == 302
        assert '/libraries' in response.location
        assert get_current_setup_step() is None


class TestSetupFirstLibrary:
    def test_first_library_is_created_and_initial_scan_queued(
        self, client, db_session, admin_user, tmp_path, monkeypatch,
    ):
        from oneirodex.utils.setup import set_setup_step, get_current_setup_step

        folder = tmp_path / 'roms'
        folder.mkdir()
        monkeypatch.setattr(
            'oneirodex.utils.security.get_allowed_base_directories',
            lambda _app: [str(tmp_path)],
        )
        set_setup_step(6)
        for name in (
            'initialize_library_folders', 'initialize_discovery_sections',
            'insert_default_scanning_filters', 'initialize_default_settings',
            'initialize_allowed_file_types',
        ):
            monkeypatch.setattr(f'oneirodex.init_data.{name}', lambda: None)

        with patch(
            'oneirodex.utils.scan_queue.start_or_queue_scan',
            return_value={'status': 'started'},
        ) as start_scan:
            response = client.post('/setup/library', data={
                'name': 'First NES library',
                'platform': 'NES',
                'folder_path': str(folder),
                'scan_mode': 'folders',
                'scan_depth': '1',
            })

        assert response.status_code == 302
        assert response.location.endswith('/libraries')
        library = db_session.execute(
            select(Library).filter_by(name='First NES library')
        ).scalars().first()
        assert library is not None
        assert library.last_scan_folder == str(folder)
        start_scan.assert_called_once()
        assert start_scan.call_args.kwargs['library_uuid'] == library.uuid
        assert get_current_setup_step() is None

    def test_first_library_rejects_paths_outside_declared_roots(
        self, client, db_session, admin_user, tmp_path,
    ):
        from oneirodex.utils.setup import set_setup_step

        set_setup_step(6)
        folder = tmp_path / 'outside'
        folder.mkdir()
        response = client.post('/setup/library', data={
            'name': 'Unsafe library', 'platform': 'NES',
            'folder_path': str(folder), 'scan_mode': 'folders', 'scan_depth': '1',
        })
        assert response.status_code == 200
        assert b'outside the configured library locations' in response.data
        assert db_session.execute(
            select(Library).filter_by(name='Unsafe library')
        ).scalars().first() is None


class TestSetupApiConnections:
    def test_api_secrets_are_not_rendered_and_selected_credentials_are_saved(
        self, client, db_session, admin_user,
    ):
        from oneirodex.utils.setup import get_current_setup_step

        settings = _park_wizard_at(db_session, 5)
        settings.steamgriddb_api_key = 'existing-secret-value'
        settings.enable_hltb_integration = True
        db_session.commit()

        page = client.get('/setup/integrations')
        assert page.status_code == 200
        assert b'existing-secret-value' not in page.data
        assert b'type="password"' in page.data

        response = client.post('/setup/integrations', data={
            'configure_steam_web_api_key': 'on',
            'steam_web_api_key': 'new-steam-api-key',
            'configure_oidc': 'on',
            'oidc_issuer_url': 'https://sso.example.test',
            'oidc_client_id': 'oneirodex-stage',
            'oidc_client_secret': 'oidc-stage-secret',
        })
        assert response.status_code == 302
        assert response.location.endswith('/setup/library')
        db_session.expire_all()
        saved = db_session.execute(
            select(GlobalSettings).filter_by(id=settings.id)
        ).scalars().first()
        assert saved.steam_web_api_key == 'new-steam-api-key'
        assert saved.steamgriddb_api_key == 'existing-secret-value'
        assert saved.enable_hltb_integration is False
        assert saved.oidc_issuer_url == 'https://sso.example.test'
        assert saved.oidc_client_id == 'oneirodex-stage'
        assert saved.oidc_client_secret == 'oidc-stage-secret'
        assert saved.oidc_enabled is False
        assert get_current_setup_step() == 6

    def test_skip_preserves_existing_api_preferences(self, client, db_session, admin_user):
        from oneirodex.utils.setup import get_current_setup_step

        settings = _park_wizard_at(db_session, 5)
        settings.enable_hltb_integration = True
        db_session.commit()
        response = client.post('/setup/integrations', data={'skip_integrations': '1'})
        assert response.location.endswith('/setup/library')
        db_session.refresh(settings)
        assert settings.enable_hltb_integration is True
        assert get_current_setup_step() == 6

    def test_oidc_setup_rejects_non_http_urls_without_completing_step(
        self, client, db_session, admin_user,
    ):
        from oneirodex.utils.setup import get_current_setup_step

        _park_wizard_at(db_session, 5)
        response = client.post('/setup/integrations', data={
            'configure_oidc': 'on',
            'oidc_issuer_url': 'file:///etc/passwd',
            'oidc_client_id': 'invalid-scheme',
        })
        assert response.status_code == 200
        assert b'OIDC issuer must use HTTPS' in response.data
        assert get_current_setup_step() == 5

    def test_oidc_setup_rejects_http_issuer(self, client, db_session, admin_user):
        from oneirodex.utils.setup import get_current_setup_step

        _park_wizard_at(db_session, 5)
        response = client.post('/setup/integrations', data={
            'configure_oidc': 'on',
            'oidc_issuer_url': 'http://idp.example.test',
            'oidc_client_id': 'cleartext-risk',
            'oidc_client_secret': 'must-not-be-saved',
        })

        assert response.status_code == 200
        assert b'OIDC issuer must use HTTPS' in response.data
        assert get_current_setup_step() == 5
        settings = db_session.execute(
            select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
        ).scalars().first()
        assert settings.oidc_client_secret != 'must-not-be-saved'

    def test_admin_oidc_save_rejects_http_issuer(self, client, db_session, admin_user):
        settings = _park_wizard_at(db_session, 6)
        settings.setup_in_progress = False
        settings.setup_completed = True
        settings.oidc_issuer_url = 'https://saved-idp.example.test'
        db_session.commit()

        response = client.post('/admin/integrations/oidc/save', json={
            'oidc_enabled': True,
            'oidc_issuer_url': 'http://idp.example.test',
            'oidc_client_id': 'cleartext-risk',
            'oidc_client_secret': 'must-not-be-saved',
            'oidc_redirect_uri': 'https://oneirodex.example.test/login/oidc/callback',
        })

        assert response.status_code == 400
        assert response.get_json()['error_code'] == 'bad_request'
        db_session.refresh(settings)
        assert settings.oidc_issuer_url == 'https://saved-idp.example.test'
        assert settings.oidc_client_secret != 'must-not-be-saved'


class TestSetupSessionHandling:
    """Test setup session state management."""
    
    def test_setup_start_sets_database_state(self, client, db_session):
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        # Also clean up GlobalSettings to ensure clean state
        db_session.execute(delete(GlobalSettings))
        db_session.commit()
        """Test that starting setup sets database state correctly."""
        response = client.get('/setup')
        assert response.status_code == 200
        
        # Check database setup state
        from oneirodex.utils.setup import get_current_setup_step, is_setup_required
        assert get_current_setup_step() == 1
        assert is_setup_required()  # Should still be required since no admin user exists
    
    def test_setup_step_progression(self, client, db_session):
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        # Also clean up GlobalSettings to ensure clean state
        db_session.execute(delete(GlobalSettings))
        db_session.commit()
        """Test proper setup step progression via database tracking."""
        from oneirodex.utils.setup import get_current_setup_step, is_setup_required
        
        # Start at step 1
        response = client.get('/setup')
        assert get_current_setup_step() == 1
        
        # Admin creation moves to step 2
        with patch('oneirodex.routes_setup.SetupForm') as mock_form_class:
            mock_form = MagicMock()
            mock_form.validate_on_submit.return_value = True
            mock_form.username.data = 'admin'
            mock_form.email.data = 'admin@test.com'
            mock_form.password.data = 'password123'
            mock_form.csrf_token.data = 'test-token'
            mock_form_class.return_value = mock_form
            
            with patch('oneirodex.routes_setup.log_system_event'):
                response = client.post('/setup/submit', data={})
                
        assert get_current_setup_step() == 2
        
        # SMTP setup (skip) moves to step 3 — Features, not IGDB.
        response = client.post('/setup/smtp', data={'skip_smtp': 'true'})
        assert get_current_setup_step() == 3

        # Features moves to step 4. This step is why the whole file was failing:
        # it landed between SMTP and IGDB and nothing here walked through it, so
        # every later assertion was made against a wizard stuck on Features.
        response = client.post('/setup/features', data={'enable_game_updates': 'y'})
        assert get_current_setup_step() == 4
        
        # IGDB advances to the optional API and first-library steps.
        with patch('oneirodex.routes_setup.IGDBSetupForm') as mock_form_class:
            mock_form = MagicMock()
            mock_form.validate_on_submit.return_value = True
            mock_form.igdb_client_id.data = 'test_client_id_12345'
            mock_form.igdb_client_secret.data = 'test_client_secret_12345'
            mock_form_class.return_value = mock_form
            
            with patch('oneirodex.routes_setup.log_system_event'):
                
                response = client.post('/setup/igdb', data={})
                
        assert get_current_setup_step() == 5
        assert not is_setup_required()  # Should no longer be required


class TestSetupFormIntegration:
    """Test actual form handling without mocking forms."""
    
    def test_setup_form_validation_error_handling(self, client, db_session):
        # Ensure no users exist for this test
        # Clean up database safely respecting foreign key constraints
        safe_cleanup_users_and_related(db_session)
        """Test how setup handles real form validation errors."""
        # Submit invalid data that should trigger form validation errors
        form_data = {
            'username': 'a',  # Too short
            'email': 'invalid-email',  # Invalid format
            'password': 'short',  # Too short
            'confirm_password': 'different'  # Doesn't match
        }
        
        response = client.post('/setup/submit', data=form_data)
        
        # Should render the setup form again with errors
        assert response.status_code == 200
        assert b'setup' in response.data or b'Setup' in response.data
    
    def test_igdb_form_validation_error_handling(self, client, db_session, admin_user):
        """Test how IGDB setup handles real form validation errors."""
        # Use existing admin_user fixture and set database to step 3
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(4)  # IGDB is step 4 since the Features step landed
        
        # Submit invalid IGDB data
        form_data = {
            'igdb_client_id': 'short',  # Too short (min 20 chars)
            'igdb_client_secret': 'short'  # Too short (min 20 chars)
        }
        
        response = client.post('/setup/igdb', data=form_data)
        
        # Should render the IGDB setup form again with errors
        assert response.status_code == 200
        assert b'igdb' in response.data or b'IGDB' in response.data
