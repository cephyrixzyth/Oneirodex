"""The apply-theme endpoint is retired (W28).

This file used to assert the route existed, rejected anonymous callers and was
CSRF-protected. `POST /admin/themes/apply` set the calling admin's own
`preferences.theme` — the same write Preferences performs — from a second swatch
grid on the admin Themes page. Two surfaces writing one value could disagree
about what was selected, with nothing to say which had last won.

Nothing was lost by removing it: `UserPreferencesForm` builds its choices from
`get_installed_themes()`, so Preferences already lists uploaded packs as well as
the presets, and it is where font, icon pack and tile size are chosen too.

The tests now pin the retirement, on the same principle the file always had —
a route contract is worth asserting, and "gone" is a contract.

Kept free of database fixtures so this still runs when no test Postgres is up.
"""

import pytest
from flask import Flask

from oneirodex import login_manager
from oneirodex.routes_admin_ext import admin2_bp


@pytest.fixture
def bare_app(tmp_path):
    """A minimal app with only the admin blueprint mounted."""
    app = Flask('bare_admin', root_path=str(tmp_path))
    app.config.update(SECRET_KEY='test-secret-key', TESTING=True, WTF_CSRF_ENABLED=False)
    login_manager.init_app(app)
    app.register_blueprint(admin2_bp)
    return app


def test_apply_theme_route_is_gone(bare_app):
    rules = {rule.rule for rule in bare_app.url_map.iter_rules()}
    assert '/admin/themes/apply' not in rules


def test_apply_theme_endpoint_is_gone(bare_app):
    endpoints = {rule.endpoint for rule in bare_app.url_map.iter_rules()}
    assert 'admin2.apply_theme' not in endpoints


def test_the_page_that_drove_it_no_longer_posts_to_it(bare_app):
    """A retired handler with live markup still pointing at it would 404 on
    click, which is worse than either keeping or removing it cleanly."""
    from pathlib import Path

    page = (
        Path(__file__).resolve().parents[1]
        / 'frontend' / 'admin-app' / 'src' / 'pages' / 'ThemesPage.tsx'
    ).read_text(encoding='utf-8')
    assert 'apply_theme' not in page
    assert 'adminThemeGrid' not in page


def test_the_themes_page_still_survives_without_it(bare_app):
    """Upload, reset and delete are what only this page can do; retiring the
    per-account picker must not have taken them with it."""
    rules = {rule.rule for rule in bare_app.url_map.iter_rules()}
    assert '/admin/themes/reset' in rules
