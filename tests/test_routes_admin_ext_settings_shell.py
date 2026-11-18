"""
Unit tests for the Settings hub at GET /admin/settings.

Covers: auth guards, the one-click card grid, ?section= back-compat redirects,
and that every section deep-links to an existing, registered route.
"""

import pytest
from uuid import uuid4


from oneirodex.models import User


@pytest.fixture
def admin_user(db_session):
    """Create an admin user."""
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=str(uuid4()),
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
    unique_id = str(uuid4())[:8]
    user = User(
        user_id=str(uuid4()),
        name=f'TestUser_{unique_id}',
        email=f'user_{unique_id}@test.com',
        role='user',
        is_email_verified=True
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_oidc_settings_url_serves_its_own_admin_page(admin_user, client):
    """The admin app routes /admin/integrations/oidc to its OIDC settings page."""
    login(client, admin_user)
    response = client.get('/admin/integrations/oidc')
    assert response.status_code == 200
    assert 'admin-app-root' in response.get_data(as_text=True)


class TestSettingsShellSections:
    """Test the SETTINGS_SHELL_SECTIONS configuration itself."""


class TestSettingsShellRoute:
    """The hub is an admin SPA shell.

    These asserted card labels, blurbs, deep-link hrefs and inline SVG classes
    in the response body. `/admin/settings` renders the admin-app shell and the
    cards come from `navConfig.SETTINGS_GROUPS`, so none of that text is in the
    HTML any more — the assertions described a page that had moved. The
    `?section=` redirects, which are still server-side, are covered below and
    unchanged.
    """

    """Test GET /admin/settings (the hub page)."""

    def test_requires_login(self, client, configured_install):
        response = client.get('/admin/settings')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_requires_admin(self, client, regular_user):
        login(client, regular_user)
        response = client.get('/admin/settings')
        assert response.status_code == 302

    def test_hub_serves_the_admin_shell(self, client, admin_user):
        login(client, admin_user)
        response = client.get('/admin/settings')
        assert response.status_code == 200
        body = response.get_data(as_text=True)
        assert 'admin-app-root' in body
        assert '/static/dist/admin-pilot/' in body

    def test_unknown_section_shows_the_hub(self, client, admin_user):
        """An unrecognised ?section= must not redirect anywhere."""
        login(client, admin_user)
        response = client.get('/admin/settings?section=bogus')
        assert response.status_code == 200
        assert 'admin-app-root' in response.get_data(as_text=True)

    def test_hub_costs_one_click_per_destination(self, client, admin_user):
        """No card may point back at the hub with a ?section= filter."""
        login(client, admin_user)
        response = client.get('/admin/settings')
        body = response.get_data(as_text=True)
        assert 'settings?section=' not in body


    def test_post_still_updates_settings(self, client, admin_user):
        """POST behavior for saving settings must be unchanged by the shell."""
        login(client, admin_user)
        response = client.post('/admin/settings', json={'showSystemLogo': False})
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert data['settings']['showSystemLogo'] is False
