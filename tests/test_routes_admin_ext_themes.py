import pytest
import json
import zipfile
from unittest.mock import MagicMock
from oneirodex.models import User
from oneirodex.utils.theme_validation import validate_theme_file, is_valid_theme_name
from uuid import uuid4
from io import BytesIO


def logged_messages(mock_log):
    """Every message handed to log_system_event, joined for substring checks.

    Asserting only that the mock was *called* cannot tell the success path from
    the error path — both log — which is how several tests below used to pass
    while exercising the branch they meant to avoid.
    """
    return '\n'.join(str(call.args[0]) for call in mock_log.call_args_list if call.args)


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
def theme_sandbox(app, tmp_path, monkeypatch):
    """Point the app's root at a throwaway tree before the theme routes run.

    `/admin/themes/reset` resolves both the source and the target from
    `current_app.root_path` and really calls `shutil.rmtree` on the target, so
    any test that drives it against the installed package deletes the
    developer's generated `static/library/themes/default` for real. The
    copy-failure test mocked `copytree` but not `rmtree`, which removed that
    tree and then failed before anything put it back — every page in a running
    dev instance came back unstyled.

    Redirecting `root_path` keeps the writes inside tmp_path, which also means
    the reset can be exercised for real instead of being mocked into a shape
    that no longer matches the route.
    """
    root = tmp_path / 'app_root'

    source = root / 'setup' / 'default_theme'
    (source / 'css').mkdir(parents=True)
    (source / 'theme.json').write_text(
        json.dumps({'name': 'Default Theme', 'author': 'Oneirodex', 'version': '2.1.0'}),
        encoding='utf-8',
    )
    # Same shape as the source tree in test_preset_themes.py: preset generation
    # rewrites these variables, so a stand-in that omits them is not a stand-in.
    (source / 'css' / 'base.css').write_text(
        ':root {\n'
        '    --bg-dark-40: rgba(18, 22, 28, 0.92);\n'
        '    --bg-dark-30: rgba(12, 16, 22, 0.96);\n'
        '    --btn-primary: #ff5a36;\n'
        '    --btn-primary-hover: #e04520;\n'
        '    --od-accent: var(--btn-primary);\n'
        '}\n',
        encoding='utf-8',
    )
    (source / 'css' / 'od-tokens.css').write_text(
        ':root {\n'
        '  --od-bg: #0b0d10;\n'
        '  --od-surface: #141820;\n'
        '  --od-text: #f2f4f8;\n'
        '  --od-accent: #ff5a36;\n'
        '  --od-accent-contrast: #0b0d10;\n'
        '}\n',
        encoding='utf-8',
    )

    installed = root / 'static' / 'library' / 'themes' / 'default'
    installed.mkdir(parents=True)
    (installed / 'theme.json').write_text(
        json.dumps({'name': 'Stale Default'}), encoding='utf-8'
    )

    monkeypatch.setattr(app, 'root_path', str(root))
    return root


@pytest.fixture
def sample_theme_data():
    """Sample theme.json data for testing."""
    return {
        'name': 'Test Theme',
        'description': 'A test theme for unit testing',
        'author': 'Test Author',
        'release_date': '2024-01-01'
    }


def create_test_zip_file(theme_data, include_css=True, include_theme_json=True, size_mb=None):
    """Helper function to create a test zip file."""
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        if include_theme_json:
            zip_file.writestr('theme.json', json.dumps(theme_data))
        if include_css:
            zip_file.writestr('css/style.css', 'body { color: red; }')
        
        # Add large file if size_mb is specified
        if size_mb:
            large_content = 'x' * (size_mb * 1024 * 1024)  # Create file of specified size
            zip_file.writestr('large_file.txt', large_content)
    
    zip_buffer.seek(0)
    return zip_buffer


class TestValidationFunctions:
    """Tests for validation helper functions."""

    def test_validate_theme_file_valid_zip(self, sample_theme_data):
        """Test validation of a valid ZIP file."""
        zip_file = create_test_zip_file(sample_theme_data)
        zip_file.filename = 'test.zip'  # Ensure filename is set
        is_valid, error = validate_theme_file(zip_file)
        assert is_valid is True
        assert error is None

    def test_validate_theme_file_no_file(self):
        """Test validation when no file is provided."""
        is_valid, error = validate_theme_file(None)
        assert is_valid is False
        assert "No file provided" in error

    def test_validate_theme_file_empty_filename(self):
        """Test validation when file has empty filename."""
        mock_file = MagicMock()
        mock_file.filename = ""
        is_valid, error = validate_theme_file(mock_file)
        assert is_valid is False
        assert "No file provided" in error

    def test_validate_theme_file_too_large(self, sample_theme_data):
        """Test validation of file that's too large."""
        # Mock a large file using MagicMock to simulate the file size behavior
        mock_file = MagicMock()
        mock_file.filename = 'large_test.zip'
        mock_file.tell.return_value = 27 * 1024 * 1024  # 27MB
        mock_file.read.return_value = b'PK\x03\x04'  # Valid ZIP magic bytes
        
        is_valid, error = validate_theme_file(mock_file)
        assert is_valid is False
        assert "exceeds maximum allowed size" in error

    def test_validate_theme_file_empty_file(self):
        """Test validation of empty file."""
        mock_file = MagicMock()
        mock_file.filename = "test.zip"
        mock_file.tell.return_value = 0
        is_valid, error = validate_theme_file(mock_file)
        assert is_valid is False
        assert "File is empty" in error

    def test_validate_theme_file_invalid_zip(self):
        """Test validation of non-ZIP file."""
        mock_file = MagicMock()
        mock_file.filename = "test.zip"
        mock_file.tell.return_value = 1024  # Non-zero size
        mock_file.read.return_value = b"NOT A ZIP"  # Invalid magic bytes
        is_valid, error = validate_theme_file(mock_file)
        assert is_valid is False
        assert "not a valid ZIP archive" in error

    def test_is_valid_theme_name_valid(self):
        """Test validation of valid theme names."""
        valid_names = ["MyTheme", "theme_2024", "Cool-Theme", "Theme123"]
        for name in valid_names:
            is_valid, error = is_valid_theme_name(name)
            assert is_valid is True
            assert error is None

    def test_is_valid_theme_name_empty(self):
        """Test validation of empty theme name."""
        for name in ["", "   ", None]:
            is_valid, error = is_valid_theme_name(name)
            assert is_valid is False
            assert "cannot be empty" in error

    def test_is_valid_theme_name_reserved_windows_names(self):
        """Test validation of Windows reserved names."""
        reserved_names = ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1", "con", "prn"]
        for name in reserved_names:
            is_valid, error = is_valid_theme_name(name)
            assert is_valid is False
            assert "reserved system name" in error

    def test_is_valid_theme_name_reserved_with_extension(self):
        """Test validation of Windows reserved names with extensions."""
        reserved_names = ["CON.txt", "PRN.zip", "COM1.theme"]
        for name in reserved_names:
            is_valid, error = is_valid_theme_name(name)
            assert is_valid is False
            assert "reserved system name" in error

    def test_is_valid_theme_name_dangerous_characters(self):
        """Test validation of names with dangerous characters."""
        dangerous_names = ["theme<", "theme>", "theme:", 'theme"', "theme|", 
                          "theme?", "theme*", "theme\\", "theme/"]
        for name in dangerous_names:
            is_valid, error = is_valid_theme_name(name)
            assert is_valid is False
            assert "invalid characters" in error

    def test_is_valid_theme_name_path_traversal(self):
        """Test validation of names with path traversal attempts."""
        # Test names that would trigger the path traversal check specifically
        traversal_names = [".theme", "theme.", "theme..bad"]
        for name in traversal_names:
            is_valid, error = is_valid_theme_name(name)
            assert is_valid is False
            assert "invalid path elements" in error
        
        # Test names with slashes that will be caught by dangerous character check
        slash_names = ["../theme", "theme/.."] 
        for name in slash_names:
            is_valid, error = is_valid_theme_name(name)
            assert is_valid is False
            assert ("invalid characters" in error or "invalid path elements" in error)


class TestManageThemesRoute:
    """Tests for the manage_themes route."""

    def test_manage_themes_requires_login(self, client, configured_install):
        """Test that manage themes page requires login."""
        response = client.get('/admin/themes')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_manage_themes_requires_admin(self, client, regular_user):
        """Test that manage themes page requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/admin/themes')
        assert response.status_code == 302
        assert 'login' in response.location


class TestThemeReadmeRoute:
    """Tests for the theme_readme route."""

    def test_theme_readme_requires_login(self, client, configured_install):
        """Test that theme readme page requires login."""
        response = client.get('/admin/themes/readme')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_theme_readme_requires_admin(self, client, regular_user):
        """Test that theme readme page requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.get('/admin/themes/readme')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_theme_readme_admin_access(self, client, admin_user):
        """Test that admin can access theme readme page."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        response = client.get('/admin/themes/readme')
        assert response.status_code == 200
        assert b'id="admin-app-root"' in response.data

    def test_theme_readme_get_method_only(self, client, admin_user):
        """Test that theme readme only accepts GET requests."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # GET should work
        response_get = client.get('/admin/themes/readme')
        assert response_get.status_code == 200
        
        # POST should not be allowed
        response_post = client.post('/admin/themes/readme')
        assert response_post.status_code == 405


class TestDeleteThemeRoute:
    """Tests for the delete_theme route."""

    def test_delete_theme_requires_login(self, client, configured_install):
        """Test that delete theme requires login."""
        response = client.post('/admin/themes/delete/test_theme')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_delete_theme_requires_admin(self, client, regular_user):
        """Test that delete theme requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/themes/delete/test_theme')
        assert response.status_code == 302
        assert 'login' in response.location


    def test_delete_theme_post_method_only(self, client, admin_user):
        """Test that delete theme only accepts POST requests."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # GET should not be allowed
        response_get = client.get('/admin/themes/delete/test_theme')
        assert response_get.status_code == 405


class TestResetDefaultThemesRoute:
    """Tests for the reset_default_themes route."""

    def test_reset_default_themes_requires_login(self, client, configured_install):
        """Test that reset default themes requires login."""
        response = client.post('/admin/themes/reset')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_reset_default_themes_requires_admin(self, client, regular_user):
        """Test that reset default themes requires admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        response = client.post('/admin/themes/reset')
        assert response.status_code == 302
        assert 'login' in response.location


    def test_reset_default_themes_post_method_only(self, client, admin_user):
        """Test that reset default themes only accepts POST requests."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        
        # GET should not be allowed
        response_get = client.get('/admin/themes/reset')
        assert response_get.status_code == 405


class TestApplyThemeRoute:
    """Retired (W28).

    POST /admin/themes/apply set the calling admin's own preferences.theme —
    the same write Preferences performs — from a second swatch grid on the
    admin Themes page, so two surfaces could disagree about what was selected.
    Nothing was lost removing it: Preferences builds its choices from
    get_installed_themes(), so it already covers uploaded packs too.

    The retirement itself is pinned in tests/test_theme_apply_registration.py.
    """

    def test_the_route_is_gone(self, app):
        endpoints = {r.endpoint for r in app.url_map.iter_rules()}
        assert 'admin2.apply_theme' not in endpoints


class TestThemeRoutesIntegration:
    """Integration tests for theme routes."""

            # admin2.apply_theme is deliberately absent — see TestApplyThemeRoute.

    def test_theme_routes_require_authentication(self, client, configured_install):
        """Test that all theme routes require authentication."""
        routes = [
            '/admin/themes',
            '/admin/themes/readme',
            '/admin/themes/reset'
        ]
        
        for route in routes:
            response = client.get(route) if 'reset' not in route else client.post(route)
            assert response.status_code == 302
            assert 'login' in response.location

    def test_theme_routes_require_admin_role(self, client, regular_user):
        """Test that all theme routes require admin role."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        
        routes = [
            '/admin/themes',
            '/admin/themes/readme',
            '/admin/themes/reset'
        ]
        
        for route in routes:
            response = client.get(route) if 'reset' not in route else client.post(route)
            assert response.status_code == 302
            assert 'login' in response.location

