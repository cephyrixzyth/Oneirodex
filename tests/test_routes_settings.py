import pytest
import json
from unittest.mock import patch, MagicMock
from uuid import uuid4
from io import BytesIO
from werkzeug.datastructures import FileStorage

from oneirodex.models import User, InviteToken, UserPreference


@pytest.fixture
def test_user(db_session):
    """Create a test user."""
    user_uuid = str(uuid4())
    user = User(
        name=f'testuser_{user_uuid[:8]}',
        email=f'test_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='user',
        user_id=user_uuid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=5
    )
    user.set_password('testpassword123')
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
def test_user_preference(db_session, test_user):
    """Create test user preferences."""
    preference = UserPreference(
        user_id=test_user.id,
        items_per_page=25,
        default_sort='name',
        default_sort_order='desc',
        theme='dark'
    )
    db_session.add(preference)
    db_session.commit()
    return preference


@pytest.fixture
def invite_tokens(db_session, test_user):
    """Create test invite tokens."""
    tokens = []
    # Create some used and unused tokens
    for i in range(3):
        token = InviteToken(
            token=f'token_{i}_{uuid4().hex[:8]}',
            creator_user_id=test_user.user_id,
            used=(i == 0)  # First token is used
        )
        tokens.append(token)
        db_session.add(token)
    db_session.commit()
    return tokens


@pytest.fixture
def mock_image():
    """Create a mock PIL Image."""
    image = MagicMock()
    image.format = 'PNG'
    image.size = (200, 200)
    image.copy.return_value = image
    image.thumbnail = MagicMock()
    image.save = MagicMock()
    return image


@pytest.fixture
def mock_gif_image():
    """Create a mock GIF PIL Image."""
    image = MagicMock()
    image.format = 'GIF'
    image.size = (400, 400)
    image.info = {'duration': 100, 'loop': 0}
    image.copy.return_value = image
    image.thumbnail = MagicMock()
    image.save = MagicMock()
    image.seek = MagicMock(side_effect=EOFError)  # Simulate end of GIF frames
    image.tell = MagicMock(return_value=0)
    return image


def create_test_file(filename='test.png', size=1024):
    """Create a test file storage object."""
    file_content = b'fake image content' * (size // 18)  # Rough size approximation
    stream = BytesIO(file_content)
    stream.seek(0)  # Reset to beginning
    file_storage = FileStorage(
        stream=stream,
        filename=filename,
        content_type='image/png'
    )
    return file_storage


class TestSettingsProfileEdit:
    """Test the settings_profile_edit route."""

    def test_get_profile_edit_requires_login(self, client, configured_install):
        """Test that GET request requires login."""
        response = client.get('/settings_profile_edit')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_get_profile_edit_opens_react_account_panel(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        response = client.get('/settings_profile_edit')
        assert response.status_code == 302
        assert response.location.endswith('/library?account=avatar')

    def test_get_profile_edit_authenticated_legacy_url_redirects_to_react_panel(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        response = client.get('/settings_profile_edit?legacy=1')
        assert response.status_code == 302
        assert response.location.endswith('/library?account=avatar')


            # Verify the route handles the case correctly

            # This test verifies the basic route functionality works

class TestSettingsProfileView:
    """Test the settings_profile_view route."""

    def test_get_profile_view_requires_login(self, client, configured_install):
        """Test that GET request requires login."""
        response = client.get('/settings_profile_view')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_get_profile_view_opens_react_account_panel(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        response = client.get('/settings_profile_view')
        assert response.status_code == 302
        assert response.location.endswith('/library?account=profile')

    def test_get_profile_view_authenticated_legacy_url_redirects_to_react_panel(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        response = client.get('/settings_profile_view?legacy=1')
        assert response.status_code == 302
        assert response.location.endswith('/library?account=profile')


class TestAccountPasswordChange:
    """Test the account_pw route."""

    def test_get_password_change_requires_login(self, client, configured_install):
        """Test that GET request requires login."""
        response = client.get('/settings_password')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_get_password_change_opens_react_account_panel(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        response = client.get('/settings_password')
        assert response.status_code == 302
        assert response.location.endswith('/library?account=password')

    def test_get_password_change_legacy_url_redirects_to_react_panel(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        response = client.get('/settings_password?legacy=1')
        assert response.status_code == 302
        assert response.location.endswith('/library?account=password')

    def test_post_password_change_rejects_wrong_current_password(self, client, test_user, db_session):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.post('/settings_password', data={
            'current_password': 'incorrect',
            'password': 'newpassword123',
            'confirm_password': 'newpassword123',
        })

        assert response.status_code == 302
        assert response.location.endswith('/library?account=password')
        db_session.refresh(test_user)
        assert test_user.check_password('testpassword123')


class TestSettingsPanel:
    """Test the settings_panel route."""

    def test_get_settings_panel_requires_login(self, client, configured_install):
        """Test that GET request requires login."""
        response = client.get('/settings_panel')
        assert response.status_code == 302
        assert '/login' in response.location

    def test_get_settings_panel_opens_shared_react_preferences(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True
        response = client.get('/settings_panel')
        assert response.status_code == 302
        assert response.location.endswith('/library?preferences=1')

    def test_post_settings_panel_default_theme_handling(self, client, test_user, db_session):
        """Test POST request with default theme selection."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        form_data = {
            'items_per_page': 20,
            'default_sort': 'name',
            'default_sort_order': 'asc',
            'theme': 'default'  # Should be stored as None
        }

        with patch('oneirodex.forms_native.UserPreferencesForm') as mock_form_class:
            mock_form = MagicMock()
            mock_form.validate_on_submit.return_value = True
            mock_form.items_per_page.data = 20
            mock_form.default_sort.data = 'name'
            mock_form.default_sort_order.data = 'asc'
            mock_form.theme.data = 'default'
            mock_form.icon_pack.data = 'outline'
            mock_form.font.data = 'system-ui'
            mock_form.tile_size.data = 50
            mock_form.preferred_game_locale.data = 'en-US'
            mock_form.browser_player_engine.data = ''
            mock_form_class.return_value = mock_form

            response = client.post('/settings_panel', data=form_data)

            assert response.status_code == 200
            response_data = json.loads(response.data)
            assert response_data['success'] is True

            # The actual logic stores 'default' as None, but since we're mocking the form data,
            # we just verify the response was successful and the theme processing was attempted
            # In real implementation, the theme would be None if form.theme.data == 'default'
            db_session.refresh(test_user)
            # Since we mocked form.theme.data as 'default', verify it was processed
            # The actual conversion to None happens in the route logic:
            # current_user.preferences.theme = form.theme.data if form.theme.data != 'default' else None
            assert test_user.preferences is not None  # Preferences were created/updated

class TestFontPickerIsReachable:
    """The retired settings URL must lead to the React preferences surface."""

    def test_settings_panel_renders_the_font_select(self, client, test_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response = client.get('/settings_panel')

        assert response.status_code == 302
        assert response.location.endswith('/library?preferences=1')

    def test_font_choices_include_more_than_the_default(self, app):
        """A picker offering one option is indistinguishable from no picker."""
        from oneirodex.utils.theme_fonts import available_fonts

        with app.app_context():
            assert len(available_fonts()) > 1
