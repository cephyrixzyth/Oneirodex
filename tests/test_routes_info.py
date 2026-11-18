from contextlib import contextmanager
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


@contextmanager
def _signed_in(client, user):
    """Sign the client in as ``user`` for the block (a real session, not a patch)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    yield


class TestAdminServerStatusRoute:
    """The standalone page is retired; Ops is the one health surface (W27-D1)."""

    def test_admin_server_status_requires_login(self, client, configured_install):
        """Test that admin server status route requires authentication."""
        response = client.get('/admin/server_status_page')

        assert response.status_code == 302
        assert '/login' in response.location

    def test_admin_server_status_requires_admin_role(self, client, regular_user):
        """Test that admin server status route requires admin role."""

        with _signed_in(client, regular_user):
            response = client.get('/admin/server_status_page')

        assert response.status_code in [302, 403]

    def test_admin_server_status_redirects_admins_to_ops(self, client, admin_user):
        """Bookmarks of the old page land on the Ops console."""
        with _signed_in(client, admin_user):
            response = client.get('/admin/server_status_page')

        assert response.status_code == 302
        assert '/admin/ops' in response.location


class TestRouteIntegration:
    """Test route integration and blueprint registration."""




class TestUtilityFunctionIntegration:
    """Test integration with utility functions."""

    def test_format_bytes_integration(self, app):
        """Test format_bytes function integration."""
        from oneirodex.utils.system_stats import format_bytes
        
        # Test various byte values
        assert format_bytes(1024) is not None
        assert format_bytes(1048576) is not None
        assert format_bytes(0) is not None

    def test_app_version_import(self, app):
        """Test that app_version is imported correctly."""
        from oneirodex.runtime_info import app_version
        
        assert app_version is not None
        assert isinstance(app_version, str)

    def test_app_start_time_import(self, app):
        """Test that app_start_time is imported correctly."""
        from oneirodex.runtime_info import app_start_time
        
        assert app_start_time is not None
        assert isinstance(app_start_time, datetime)


class TestErrorHandling:
    """Retired page no longer branches on settings checks — it redirects to Ops."""

    def test_server_status_page_still_redirects_when_settings_would_have_failed(
        self, client, admin_user
    ):
        with _signed_in(client, admin_user):
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

    def test_requires_admin_role(self, client, regular_user):

        with _signed_in(client, regular_user):
            response = client.get('/admin/api/ops/logs')

            assert response.status_code in [302, 403]

    def test_returns_events_with_the_shape_the_console_renders(
        self, client, admin_user
    ):

        with _signed_in(client, admin_user):
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

    def test_limit_is_clamped(self, client, admin_user):
        """An unbounded limit would ask the console to render the whole table."""

        with _signed_in(client, admin_user):
            response = client.get('/admin/api/ops/logs?limit=99999')

            assert response.status_code == 200
            assert len(response.get_json()['events']) <= 200

    def test_retired_server_info_page_is_gone(
        self, client, admin_user
    ):
        """/admin/new_server_info was folded into Ops (W27-D1).

        Asserted here rather than trusted: a retired page that still answers is
        a second copy of the truth, which is what the merge was for.
        """

        with _signed_in(client, admin_user):
            response = client.get('/admin/new_server_info')

            assert response.status_code == 404
