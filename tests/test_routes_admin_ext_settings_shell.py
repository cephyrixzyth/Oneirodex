"""
Unit tests for the Settings hub at GET /admin/settings.

Covers: auth guards, the one-click card grid, ?section= back-compat redirects,
and that every section deep-links to an existing, registered route.
"""

import pytest
from uuid import uuid4

from flask import url_for

from oneirodex.models import User
from oneirodex.routes_admin_ext.settings import (
    SETTINGS_SHELL_SECTIONS, DEFAULT_SETTINGS_SHELL_SECTION
)


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


def test_oidc_legacy_tab_url_still_redirects_to_existing_settings(admin_user, client):
    login(client, admin_user)
    response = client.get('/admin/integrations/oidc')
    assert response.status_code == 302
    assert response.headers['Location'] == '/admin/integrations#oidc'


class TestSettingsShellSections:
    """Test the SETTINGS_SHELL_SECTIONS configuration itself."""

    def test_lists_every_section_in_order(self):
        assert list(SETTINGS_SHELL_SECTIONS.keys()) == [
            'server', 'scan_match', 'attract', 'integrations', 'emulators',
            'reference_sets', 'arr', 'features', 'quality', 'layouts', 'ai',
            'storage', 'themes', 'art_studio', 'remote_play',
        ]

    def test_every_section_deep_link_is_reachable_from_the_react_hub(self, app):
        """The server keeps this map for `?section=` shortcuts; the cards are
        rendered by admin-app. Nothing makes the two agree, so a section added
        on one side and not the other is a shortcut to a card nobody can see —
        or a card whose shortcut 404s. This is the check that would notice."""
        import re
        from pathlib import Path

        nav = Path('frontend/admin-app/src/components/navConfig.ts').read_text(encoding='utf-8')
        # `to:` for router cards, `href:` for full-page links and the
        # integrations inventory — a section reachable from the top nav or an
        # inventory entry is reachable, even without a settings card. Fragments
        # are stripped: /admin/integrations#igdb still lands on integrations.
        card_targets = {
            target.split('#')[0]
            for target in re.findall(r"(?:to|href|path):\s*'([^']+)'", nav)
        }

        missing = []
        for key, section in SETTINGS_SHELL_SECTIONS.items():
            with app.test_request_context():
                url = url_for(section['endpoint'])
            if url not in card_targets:
                missing.append(f'{key} -> {url}')

        assert not missing, (
            'server sections with no card in admin-app: ' + ', '.join(missing)
        )

    def test_default_section_is_a_real_section(self):
        assert DEFAULT_SETTINGS_SHELL_SECTION in SETTINGS_SHELL_SECTIONS

    def test_each_section_has_required_fields(self):
        for key, section in SETTINGS_SHELL_SECTIONS.items():
            assert section['label']
            assert section['icon']
            assert section['description']
            assert section['endpoint']

    def test_icons_are_semantic_keys_not_font_awesome_classes(self):
        for key, section in SETTINGS_SHELL_SECTIONS.items():
            assert not section['icon'].startswith('fa-'), (
                f"{key} still carries a Font Awesome class; React icon consumers "
                "use semantic keys from the shared icon catalog"
            )

    def test_each_section_endpoint_resolves(self, app):
        """Every section endpoint must be a real, registered route."""
        with app.app_context():
            from flask import url_for
            for section in SETTINGS_SHELL_SECTIONS.values():
                url_for(section['endpoint'])  # raises if not registered


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
        assert 'dist/admin-app/admin-app.js' in body

    def test_known_section_redirects_straight_to_the_page(self, client, admin_user):
        """?section= is a one-click shortcut, not a filter on the hub."""
        login(client, admin_user)
        response = client.get('/admin/settings?section=attract')
        assert response.status_code == 302
        assert '/admin/attract_mode_settings' in response.location

    def test_unknown_section_shows_the_hub(self, client, admin_user):
        """An unrecognised ?section= must not redirect anywhere."""
        login(client, admin_user)
        response = client.get('/admin/settings?section=bogus')
        assert response.status_code == 200
        assert 'admin-app-root' in response.get_data(as_text=True)

    def test_section_shortcuts_land_on_real_pages(self, client, admin_user):
        """Replaces an assertion that the hrefs appeared in the hub's HTML.

        They are rendered by React now, so following each shortcut is both a
        truer test and a stronger one: it proves the endpoint exists and
        answers, not merely that a string was printed.
        """
        login(client, admin_user)
        for section in ('server', 'attract', 'integrations', 'themes'):
            response = client.get(f'/admin/settings?section={section}')
            assert response.status_code == 302, section
            followed = client.get(response.location)
            assert followed.status_code in (200, 302), f'{section} -> {response.location}'

    def test_hub_costs_one_click_per_destination(self, client, admin_user):
        """No card may point back at the hub with a ?section= filter."""
        login(client, admin_user)
        response = client.get('/admin/settings')
        body = response.get_data(as_text=True)
        assert 'settings?section=' not in body

    def test_no_section_carries_a_font_awesome_icon(self):
        """Replaces a check for inline SVG in the hub's HTML, which the React
        shell no longer contains. The underlying rule — icons are semantic keys
        the icon pack resolves, never Font Awesome classes — is still worth
        holding, and holds on the data rather than the rendering."""
        for key, section in SETTINGS_SHELL_SECTIONS.items():
            assert not section['icon'].startswith('fa-'), key
            assert ' ' not in section['icon'], f'{key} icon looks like a class list'

    def test_post_still_updates_settings(self, client, admin_user):
        """POST behavior for saving settings must be unchanged by the shell."""
        login(client, admin_user)
        response = client.post('/admin/settings', json={'showSystemLogo': False})
        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Settings updated successfully'
