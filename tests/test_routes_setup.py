import pytest


@pytest.fixture(autouse=True)
def _keyring(reusable_secret_keyring):
    return reusable_secret_keyring
import json
import re
from html import unescape
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
    
class TestSetupIgdbRoute:
    """Test the /setup/igdb route."""
    
    def test_igdb_skip_bypasses_required_browser_validation(self, client, db_session, admin_user):
        from oneirodex.utils.setup import set_setup_step

        set_setup_step(4)
        response = client.get('/setup/igdb')
        assert response.status_code == 200
        assert b'id="member-auth-root"' in response.data
        assert b'igdb_client_secret' not in response.data
    
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
        assert start_scan.call_args.kwargs['queue_policy'] == 'queue'
        assert 'force_parallel' not in start_scan.call_args.kwargs
        assert get_current_setup_step() is None
        with client.session_transaction() as session:
            assert session['_flashes'][-1] == (
                'success', 'Your first library is ready and its initial scan has started or queued.',
            )

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

    def test_first_library_reports_missing_directory_inside_allowed_root(
        self, client, db_session, admin_user, tmp_path, monkeypatch,
    ):
        from oneirodex.utils.setup import set_setup_step

        monkeypatch.setattr(
            'oneirodex.utils.security.get_allowed_base_directories',
            lambda _app: [str(tmp_path)],
        )
        set_setup_step(6)
        missing = tmp_path / 'not-created'
        response = client.post('/setup/library', data={
            'name': 'Missing path library', 'platform': 'NES',
            'folder_path': str(missing), 'scan_mode': 'folders', 'scan_depth': '1',
        })

        assert response.status_code == 200
        assert b'That folder is not available as a directory on the server.' in response.data
        assert db_session.execute(
            select(Library).filter_by(name='Missing path library')
        ).scalars().first() is None

    def test_first_library_scan_queue_failure_finishes_with_warning(self, client, db_session, admin_user, tmp_path, monkeypatch):
        from oneirodex.utils.setup import get_current_setup_step, set_setup_step

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
            monkeypatch.setattr(f'oneirodex.init_data.{name}', lambda *a, **k: None)

        def fail_scan(**_kwargs):
            raise OSError('synthetic queue failure')

        monkeypatch.setattr('oneirodex.utils.scan_queue.start_or_queue_scan', fail_scan)
        response = client.post('/setup/library', data={
            'name': 'Queue failure library', 'platform': 'NES',
            'folder_path': str(folder), 'scan_mode': 'folders', 'scan_depth': '1',
        })

        assert response.status_code == 302
        assert response.location.endswith('/libraries')
        assert get_current_setup_step() is None
        library = db_session.execute(
            select(Library).filter_by(name='Queue failure library')
        ).scalars().first()
        assert library is not None
        with client.session_transaction() as session:
            assert session['_flashes'][-1] == (
                'warning', 'Your first library is ready. Start its first scan from Libraries & scans.',
            )


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
        assert b'id="member-auth-root"' in page.data
        assert b'existing-secret-value' not in page.data

        response = client.post('/setup/integrations', data={
            'configure_steam_web_api_key': 'on',
            'steam_web_api_key': 'new-steam-api-key',
            'steamgriddb_api_key': 'typed-but-unchecked',
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
        from oneirodex.utils.secret_store import read_global_secret
        assert read_global_secret(saved, 'steam_web_api_key') == 'new-steam-api-key'
        assert read_global_secret(saved, 'steamgriddb_api_key') == 'existing-secret-value'
        assert saved.enable_hltb_integration is False
        assert saved.oidc_issuer_url == 'https://sso.example.test'
        assert saved.oidc_client_id == 'oneirodex-stage'
        assert read_global_secret(saved, 'oidc_client_secret') == 'oidc-stage-secret'
        assert saved.oidc_enabled is False
        assert get_current_setup_step() == 6

    def test_skip_preserves_existing_api_preferences(self, client, db_session, admin_user):
        from oneirodex.utils.setup import get_current_setup_step

        settings = _park_wizard_at(db_session, 5)
        settings.enable_hltb_integration = True
        settings.steam_web_api_key = 'existing-provider-key'
        db_session.commit()
        response = client.post('/setup/integrations', data={
            'skip_integrations': '1',
            'configure_steam_web_api_key': 'on',
            'steam_web_api_key': 'typed-but-skipped',
        })
        assert response.location.endswith('/setup/library')
        db_session.refresh(settings)
        assert settings.enable_hltb_integration is True
        assert settings.steam_web_api_key == 'existing-provider-key'
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
        
        # The server returns the shared auth shell and preserves validation
        # feedback as an escaped alert for the React setup wizard.
        assert response.status_code == 200
        assert b'id="member-auth-root"' in response.data
        notices = self._server_notices(response)
        assert all(notice['role'] == 'alert' for notice in notices)
        messages = ' '.join(notice['message'] for notice in notices)
        assert 'Invalid email address' in messages
        assert 'Password must be at least 8 characters long' in messages
        assert 'Passwords must match' in messages
    
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
        
        # Validation feedback is inserted into the shared auth shell.
        assert response.status_code == 200
        assert b'id="member-auth-root"' in response.data
        notices = self._server_notices(response)
        assert {'role': 'alert', 'message': 'Client ID: Client ID must be between 20 and 50 characters'} in notices
        assert {'role': 'alert', 'message': 'Client Secret: Client Secret must be between 20 and 50 characters'} in notices

    @staticmethod
    def _server_notices(response):
        # React creates the alert elements from the escaped shell payload.
        match = re.search(r' data-auth-notices="([^"]+)"', response.get_data(as_text=True))
        assert match is not None
        notices = json.loads(unescape(match.group(1)))
        assert notices
        return notices
