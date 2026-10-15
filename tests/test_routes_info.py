import pytest
from unittest.mock import patch, Mock, MagicMock
from datetime import datetime, timezone
from uuid import uuid4

from oneirodex import create_app, db
from oneirodex.models import User
from oneirodex.utils.event_logging import log_system_event




@pytest.fixture
def admin_user(db_session):
    """Create an admin test user."""
    unique_id = uuid4()
    admin = User(
        name=f'admin_{unique_id.hex[:8]}',
        email=f'admin_{unique_id.hex[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=unique_id
    )
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    """Create a regular test user."""
    unique_id = uuid4()
    user = User(
        name=f'user_{unique_id.hex[:8]}',
        email=f'user_{unique_id.hex[:8]}@example.com',
        password_hash='hashed_password',
        role='user',
        user_id=unique_id
    )
    db_session.add(user)
    db_session.commit()
    return user


class TestAdminServerStatusRoute:
    """The standalone page is retired; Ops is the one health surface (W27-D1)."""

    def test_admin_server_status_requires_login(self, client, configured_install):
        """Test that admin server status route requires authentication."""
        response = client.get('/admin/server_status_page')

        assert response.status_code == 302
        assert '/login' in response.location

    @patch('oneirodex.utils.auth.current_user', new_callable=MagicMock)
    def test_admin_server_status_requires_admin_role(self, mock_current_user, client, regular_user):
        """Test that admin server status route requires admin role."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'user'
        mock_current_user.id = regular_user.id

        with patch('flask_login.utils._get_user', return_value=regular_user):
            response = client.get('/admin/server_status_page')

        assert response.status_code in [302, 403]

    def test_admin_server_status_redirects_admins_to_ops(self, client, admin_user):
        """Bookmarks of the old page land on the Ops console."""
        with patch('flask_login.utils._get_user', return_value=admin_user):
            response = client.get('/admin/server_status_page')

        assert response.status_code == 302
        assert '/admin/ops' in response.location


class TestRouteIntegration:
    """Test route integration and blueprint registration."""

    def test_info_blueprint_registration(self, app):
        """Test that the info blueprint is registered correctly."""
        with app.app_context():
            # Check that the route exists
            rules = [rule.rule for rule in app.url_map.iter_rules()]
            assert '/admin/server_status_page' in rules

    def test_info_blueprint_has_no_template_context_processor(self, app):
        """The JSON-only info blueprint no longer injects settings into templates."""
        with app.app_context():
            from oneirodex.routes_info import info_bp

            processors = info_bp.template_context_processors.get(None, [])
            assert all(
                processor.__name__ == '_default_template_ctx_processor'
                for processor in processors
            )


class TestUtilityFunctionIntegration:
    """Test integration with utility functions."""

    def test_format_bytes_integration(self, app):
        """Test format_bytes function integration."""
        from oneirodex.routes_info import format_bytes
        
        # Test various byte values
        assert format_bytes(1024) is not None
        assert format_bytes(1048576) is not None
        assert format_bytes(0) is not None

    def test_app_version_import(self, app):
        """Test that app_version is imported correctly."""
        from oneirodex.routes_info import app_version
        
        assert app_version is not None
        assert isinstance(app_version, str)

    def test_app_start_time_import(self, app):
        """Test that app_start_time is imported correctly."""
        from oneirodex.routes_info import app_start_time
        
        assert app_start_time is not None
        assert isinstance(app_start_time, datetime)


class TestErrorHandling:
    """Retired page no longer branches on settings checks — it redirects to Ops."""

    def test_server_status_page_still_redirects_when_settings_would_have_failed(
        self, client, admin_user
    ):
        with patch('flask_login.utils._get_user', return_value=admin_user):
            response = client.get('/admin/server_status_page')

        assert response.status_code == 302
        assert '/admin/ops' in response.location

class TestOpsLogsApi:
    """Recent system events served to the Ops console (W27-D2).

    Reading the log used to mean leaving Ops for a separate page — the same
    "hold two screens side by side" problem that the Server info page had, and
    the reason it was retired. These pin the contract the console depends on.
    """

    def test_requires_login(self, client, configured_install):
        response = client.get('/admin/api/ops/logs')

        assert response.status_code == 302
        assert '/login' in response.location

    @patch('oneirodex.utils.auth.current_user', new_callable=MagicMock)
    def test_requires_admin_role(self, mock_current_user, client, regular_user):
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'user'
        mock_current_user.id = regular_user.id

        with patch('flask_login.utils._get_user', return_value=regular_user):
            response = client.get('/admin/api/ops/logs')

            assert response.status_code in [302, 403]

    @patch('oneirodex.utils.auth.current_user', new_callable=MagicMock)
    def test_returns_events_with_the_shape_the_console_renders(
        self, mock_current_user, client, admin_user
    ):
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_current_user.id = admin_user.id

        with patch('flask_login.utils._get_user', return_value=admin_user):
            response = client.get('/admin/api/ops/logs')

            assert response.status_code == 200
            events = response.get_json()['events']
            assert isinstance(events, list)

            if events:
                # Every key the Ops columns read. A silently renamed field would
                # render a table of blanks rather than an error.
                assert set(events[0]) >= {
                    'id', 'timestamp', 'level', 'type', 'text', 'user',
                }

    @patch('oneirodex.utils.auth.current_user', new_callable=MagicMock)
    def test_limit_is_clamped(self, mock_current_user, client, admin_user):
        """An unbounded limit would ask the console to render the whole table."""
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_current_user.id = admin_user.id

        with patch('flask_login.utils._get_user', return_value=admin_user):
            response = client.get('/admin/api/ops/logs?limit=99999')

            assert response.status_code == 200
            assert len(response.get_json()['events']) <= 200

    @patch('oneirodex.utils.auth.current_user', new_callable=MagicMock)
    def test_retired_server_info_page_is_gone(
        self, mock_current_user, client, admin_user
    ):
        """/admin/new_server_info was folded into Ops (W27-D1).

        Asserted here rather than trusted: a retired page that still answers is
        a second copy of the truth, which is what the merge was for.
        """
        mock_current_user.is_authenticated = True
        mock_current_user.role = 'admin'
        mock_current_user.id = admin_user.id

        with patch('flask_login.utils._get_user', return_value=admin_user):
            response = client.get('/admin/new_server_info')

            assert response.status_code == 404
