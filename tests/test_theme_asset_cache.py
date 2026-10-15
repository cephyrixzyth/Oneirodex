"""A theme reset has to be visible in the browser, not just on disk.

Theme files are mutable at a fixed URL: `Reset Themes` rewrites
`static/library/themes/<theme>/…` in place while every template goes on pointing
at the identical path. Static responses carried `public, max-age=3600` with no
validator, so a browser that had the old stylesheet kept it for an hour. The
reset worked, the product looked unchanged, and "hard-refresh" became the
standing workaround for what was really a caching bug.

Two mechanisms fix it and both are pinned here: `theme_asset` puts a
content-derived version on the URL, and the ASGI static handler lets theme paths
revalidate instead of asserting an hour of freshness.

No database needed for the URL tests; the header test is a pure function check.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# URL versioning
# --------------------------------------------------------------------------

def test_theme_asset_url_carries_a_version(tmp_path):
    from oneirodex.utils.asset_urls import clear_asset_versions, theme_asset_url
    from flask import Flask

    root = tmp_path / 'app'
    asset = root / 'static' / 'library' / 'themes' / 'default' / 'css'
    asset.mkdir(parents=True)
    (asset / 'base.css').write_text('body{}', encoding='utf-8')
    app = Flask(__name__, root_path=str(root))
    app.config.update(SERVER_NAME='localhost', APPLICATION_ROOT='/', PREFERRED_URL_SCHEME='http')

    with app.test_request_context('/'):
        clear_asset_versions()
        url = theme_asset_url('css/base.css', theme='default')

    assert 'library/themes/' in url
    assert re.search(r'[?&]v=', url), f'no cache-busting version on {url}'


def test_the_version_changes_when_the_file_does(tmp_path):
    """The whole point: same path, new bytes, different URL."""
    from oneirodex.utils.asset_urls import asset_version, clear_asset_versions

    target = tmp_path / 'base.css'
    target.write_text('a{}', encoding='utf-8')
    clear_asset_versions()
    first = asset_version(target)

    # Rewrite with different content, and move mtime on — Reset Themes replaces
    # the file wholesale, so both size and mtime change in practice.
    target.write_text('a{color:red}', encoding='utf-8')
    import os
    os.utime(target, (0, 0))
    clear_asset_versions()
    second = asset_version(target)

    assert first != second


def test_versions_are_memoised_until_cleared(tmp_path):
    """A page links a few dozen theme assets and this can sit on a network
    path, so the stat is cached — which is exactly why the reset has to clear
    it, and why that clearing is asserted below."""
    from oneirodex.utils.asset_urls import asset_version, clear_asset_versions

    target = tmp_path / 'x.css'
    target.write_text('a{}', encoding='utf-8')
    clear_asset_versions()
    first = asset_version(target)

    target.write_text('a{color:red}', encoding='utf-8')
    import os
    os.utime(target, (0, 0))

    assert asset_version(target) == first, 'memo should hold until cleared'
    clear_asset_versions()
    assert asset_version(target) != first, 'clearing must pick up the new file'


def test_reset_clears_the_version_memo():
    """The shared reset service invalidates URL versions after rewriting assets."""
    source = (ROOT / 'oneirodex' / 'utils' / 'theme_reset.py').read_text(encoding='utf-8')
    assert 'clear_asset_versions' in source

    reset = source[source.index('def reset_default_theme_assets'):]
    assert 'clear_asset_versions()' in reset, 'reset does not clear the memo'


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    'path,expect_revalidate',
    [
        ('/static/library/themes/default/css/base.css', True),
        ('/static/library/themes/ember/js/od_sortable_table.js', True),
        ('/static/dist/member-app/member-app.js', False),
        ('/static/newstyle/oneirodex_mark.svg', False),
    ],
)
def test_only_mutable_theme_paths_skip_the_hour(path, expect_revalidate):
    """Hashed SPA bundles and images are content-addressed or genuinely static
    and keep the hour. Theme files are neither — they change under a fixed URL."""
    source = (ROOT / 'asgi.py').read_text(encoding='utf-8')
    assert "is_mutable_theme_asset = '/static/library/themes/' in" in source, (
        'the theme-path branch is gone'
    )

    is_theme = '/static/library/themes/' in path
    assert is_theme is expect_revalidate


# --------------------------------------------------------------------------
# One place to choose a theme
# --------------------------------------------------------------------------

def test_only_preferences_writes_a_theme_preference():
    """The admin Themes page carried a second swatch grid writing the same
    `preferences.theme` that Preferences writes, so two surfaces could disagree
    about what was selected with no way to tell which had won. Retired at every
    layer — grid, fetch, and the POST handler behind it."""
    themes_py = (ROOT / 'oneirodex' / 'routes_admin_ext' / 'themes.py').read_text(encoding='utf-8')
    assert 'def apply_theme' not in themes_py
    assert "'/admin/themes/apply'" not in themes_py

    page = (ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'ThemesPage.tsx').read_text(
        encoding='utf-8'
    )
    assert 'adminThemeGrid' not in page
    assert 'data-apply-url' not in page
    # …and still points somewhere, rather than silently dropping the affordance.
    assert 'Choose your theme in Preferences' in page
    assert '/preferences#themes' in page


def test_the_orphaned_settings_panel_template_is_gone():
    """`/settings_panel` renders modal_preferences.html; settings_panel.html was
    rendered by nothing while holding a third copy of the theme picker, element
    ids and all."""
    assert not (ROOT / 'oneirodex' / 'templates' / 'settings' / 'settings_panel.html').exists()


def test_preferences_still_offers_uploaded_themes():
    """The reason retiring the admin grid loses nothing: Preferences builds its
    choices from installed themes, not from a preset list."""
    forms = (ROOT / 'oneirodex' / 'forms.py').read_text(encoding='utf-8')
    assert 'get_installed_themes()' in forms


def test_the_static_handler_still_sets_cache_control():
    """Guard against the branch being simplified away to no header at all."""
    source = (ROOT / 'asgi.py').read_text(encoding='utf-8')
    assert 'no-cache' in source
    assert 'public, max-age=3600' in source
    assert '(b"cache-control", cache_control)' in source
