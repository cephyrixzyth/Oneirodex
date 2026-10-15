"""The shared two-bar chrome contract after template retirement (UIR-4).

Both app surfaces are React and use the same shared stylesheet.

That arrangement only holds if the class names stay in step. Renaming
`od-seg__item` in one place and not the other would not break either build, it
would just quietly make admin look different again — which is precisely the
drift this refresh exists to end. These tests fail instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / 'oneirodex' / 'setup' / 'default_theme' / 'css' / 'od-appbar.css'
REACT = ROOT / 'frontend' / 'member-app' / 'src' / 'chrome' / 'ContextBar.tsx'

# The contract: every class the context bar is built from.
CONTEXT_BAR_CLASSES = (
    'od-contextbar',
    'od-contextbar__views',
    'od-contextbar__actions',
    'od-contextbar__count',
    'od-seg',
    'od-seg__item',
)


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


@pytest.mark.parametrize('css_class', CONTEXT_BAR_CLASSES)
def test_class_is_defined_in_the_shared_stylesheet(css_class):
    assert f'.{css_class}' in _read(CSS), (
        f'{css_class} is used by a renderer but has no rule in od-appbar.css'
    )


@pytest.mark.parametrize('css_class', CONTEXT_BAR_CLASSES)
def test_react_context_bar_emits_the_class(css_class):
    assert css_class in _read(REACT), f'React ContextBar is missing {css_class}'


def test_admin_react_pages_retire_their_titles_too():
    """base_admin.html has always set the v2 marker, so the admin SPA inherited
    it and none of the effect — member pages lost their headings while every
    admin h1 stayed. "Library and admin should look the same" is the point of
    the refresh, and that was the most visible way to fail it."""
    css = _read(CSS)
    assert ":root[data-chrome='v2'] .od-admin-page > h1" in css
    assert ":root[data-chrome='v2'] .od-admin-page > .od-admin-lede" in css


def test_stylesheet_is_linked_by_each_python_shell_builder():
    """The non-template shells both include shared chrome CSS."""
    for shell in ('member_spa.py', 'admin_pilot.py'):
        base = 'runtime_native' if shell == 'admin_pilot.py' else 'utils'
        markup = _read(ROOT / 'oneirodex' / base / shell)
        assert 'od-appbar.css' in markup, f'{shell} does not link od-appbar.css'
    assert 'od-appbar.css' in _read(ROOT / 'oneirodex' / 'utils' / 'styleguide_page.py')


def test_v2_marker_is_set_by_the_shared_shell_builders():
    """Page-header retirement remains controlled by the shared feature flag."""
    member = _read(ROOT / 'oneirodex' / 'utils' / 'member_spa.py')
    admin = _read(ROOT / 'oneirodex' / 'utils' / 'admin_spa.py')
    assert 'enable-new-chrome' in member
    assert 'data-chrome="v2"' in admin
    assert 'ENABLE_NEW_CHROME' in member and 'ENABLE_NEW_CHROME' in admin


def test_the_chrome_stylesheet_stays_syncable_into_every_theme():
    """Every theme must keep tracking edits to od-appbar.css.

    Two mechanisms carry it there: `theme_asset` falls back to `default` when a
    theme has no copy, and `sync_preset_themes` overwrites any copy whose
    content has drifted. Both work — *unless* the file is listed in
    PRESET_MANAGED_FILES, which is the opt-out for files a preset legitimately
    owns (its colours). od-appbar.css there would freeze all nine presets at
    whatever the CSS looked like the day they were installed.

    Note this deliberately does not inspect static/library/themes: that tree is
    generated at boot and every preset holding a synced copy is correct.
    """
    from oneirodex.utils.preset_themes import PRESET_MANAGED_FILES

    assert 'css/od-appbar.css' not in PRESET_MANAGED_FILES, (
        'od-appbar.css is protected from theme sync — presets will not track '
        'changes to the shared chrome'
    )
    # And the only tracked source of it is the default theme, so there is one
    # place to edit.
    sources = sorted((ROOT / 'oneirodex' / 'setup').glob('*/css/od-appbar.css'))
    assert [p.parent.parent.name for p in sources] == ['default_theme']


ADMIN_ROUTES = ROOT / 'frontend' / 'admin-app' / 'src' / 'components' / 'AdminRoutes.tsx'
NATIVE_LIBRARIES = ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'NativeLibrariesPage.tsx'
LIBRARIES_PANEL = ROOT / 'frontend' / 'admin-app' / 'src' / 'components' / 'LibrariesPanel.tsx'
SCAN_CONTROLS = ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'ScanControlsPage.tsx'
SCANS_PAGE = ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'ScansPage.tsx'


def test_library_and_scan_destinations_are_separate_react_routes():
    routes = _read(ADMIN_ROUTES)
    for path in ("path=\"/libraries\"", "path=\"/scan_management\"", "path=\"/admin/scan-jobs\""):
        assert path in routes
    assert 'function ScanManagementRoute()' in routes
    assert "if (tab === 'jobs') return <ScansPage />" in routes
    assert "if (tab === 'tools' || tab === 'libraries') return <NativeLibrariesPage />" in routes
    assert 'return <ScanControlsPage />' in routes


def test_manual_scan_and_jobs_render_as_single_page_sections():
    controls = _read(SCAN_CONTROLS)
    jobs = _read(SCANS_PAGE)
    assert 'Manual scan' in controls or 'Manual Scan' in controls
    assert 'queue_policy: queuePolicy' in controls
    assert "chooseManualConflict(policy: 'queue' | 'force')" in controls
    assert '<DataTable' in jobs
    assert 'error_message' in jobs
    assert 'Refresh all libraries' in jobs


def test_library_tools_and_refresh_all_are_owned_by_react_components():
    panel = _read(LIBRARIES_PANEL)
    page = _read(NATIVE_LIBRARIES)
    for workflow in ('Add many libraries', 'Import CSV/JSON'):
        assert workflow in panel
    for workflow in ('Rename one game', 'Tidy folder names'):
        assert workflow in _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'components' / ('RenameGamePanel.tsx' if workflow == 'Rename one game' else 'LibraryDoctorPanel.tsx'))
    assert '<LibrariesPanel />' in page
    assert 'Refresh all libraries' in page
    assert 'useLibraryRefreshAll' in page


def test_scan_document_routes_emit_the_shared_shell_and_defer_content():
    routes = _read(ROOT / 'oneirodex' / 'routes_admin_ext' / 'scan_management.py')
    manual = _read(ROOT / 'oneirodex' / 'routes_admin_ext' / 'scan_jobs.py')
    assert "render_admin_spa(title='Libraries & scans · Oneirodex Admin')" in routes
    assert "render_admin_spa(title='Libraries & scans · Oneirodex Admin')" in manual
    assert 'render_template(' not in routes and 'render_template(' not in manual


def test_in_page_views_satisfy_what_bootstrap_actually_binds_to():
    """Both of these were checked against the vendored bootstrap 5.3.2 bundle.

    The plugin binds via `closest('.list-group, .nav, [role="tablist"]')` and
    silently does nothing when that misses, and `_getActiveElem()` keys off
    Bootstrap's own `active` class to find the pane to hide. A segmented strip
    that renders beautifully and switches nothing is the failure mode here, and
    it produces no console error to point at.
    """
    assert '.od-seg__item.active' in _read(CSS), (
        'the stylesheet no longer styles the class bootstrap actually sets'
    )

    bundle = ROOT / 'oneirodex' / 'static' / 'vendor' / 'bootstrap' / '5.3.2' / 'js'
    bundle = bundle / 'bootstrap.bundle.min.js'
    if not bundle.is_file():
        pytest.skip('bootstrap bundle not vendored in this checkout')
    source = _read(bundle)
    # If a future bump changes either contract, this test should fail loudly
    # rather than let the strip quietly stop working.
    assert '.list-group, .nav, [role="tablist"]' in source
    assert 'Fs="active"' in source


def test_integrations_react_route_keeps_legacy_deep_link_targets():
    """The React hub owns legacy fragments plus the controls that were in Jinja."""
    source = (ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'IntegrationsPage.tsx').read_text(encoding='utf-8')
    nav = (ROOT / 'frontend' / 'admin-app' / 'src' / 'components' / 'navConfig.ts').read_text(encoding='utf-8')
    community = (ROOT / 'frontend' / 'admin-app' / 'src' / 'components' / 'CommunityChatSettingsPanel.tsx').read_text(encoding='utf-8')
    for anchor_id in ('oidc', 'meta_quest', 'indexers'):
        assert anchor_id in nav
    assert 'id="community"' in community
    assert 'MetadataProvidersSettingsPanel' in source
    assert 'RetroAchievementsSettingsPanel' in source

def test_image_queue_has_its_own_react_data_loader():
    images = _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'ImagesPage.tsx')
    assert '/admin/api/image_queue_list' in images
    assert 'Retry' in images


def test_scan_management_legacy_urls_dispatch_to_react_pages():
    routes = _read(ADMIN_ROUTES)
    assert "const tab = new URLSearchParams(search).get('active_tab') || 'auto'" in routes
    for tab in ('jobs', 'tools', 'unmatched', 'scan_filters', 'file_extensions', 'image_queue'):
        assert f"tab === '{tab}'" in routes
    assert 'return <ScanControlsPage />' in routes


def test_context_bar_declares_view_and_action_regions():
    source = _read(REACT)
    assert 'od-contextbar__views' in source
    assert 'od-contextbar__actions' in source


LIBRARIES = NATIVE_LIBRARIES
LIBRARIES_PANEL = ROOT / 'frontend' / 'admin-app' / 'src' / 'components' / 'LibrariesPanel.tsx'
SCANJOBS_CSS = ROOT / 'oneirodex' / 'setup' / 'default_theme' / 'css' / 'admin' / 'admin_manage_scanjobs.css'


def test_libraries_page_has_no_sibling_contextbar():
    """Libraries landing is LHN-only — no duplicate THN strip."""
    markup = _read(LIBRARIES)
    assert 'contextbar' not in markup.lower()


def test_libraries_panel_is_not_a_card_inside_the_page_card():
    """Libraries & scans already has a page shell. A Bootstrap .card around the
    libraries table was a second frame — the nested-tables complaint."""
    markup = _read(LIBRARIES)
    panel = _read(LIBRARIES_PANEL)
    assert '<LibrariesPanel />' in markup
    assert 'card' not in panel.lower()
    route = _read(ROOT / 'oneirodex' / 'routes_library.py')
    assert "render_admin_spa(title='Libraries & scans - Oneirodex Admin')" in route


def test_scan_jobs_and_unmatched_are_not_nested_glass_cards():
    """One primary list per pane: jobs / unmatched sit on the page shell, not
    inside another blurred card."""
    css = _read(SCANJOBS_CSS)
    jobs = css.split('.scan-jobs-card {', 1)[1].split('}', 1)[0]
    assert 'background: transparent' in jobs
    unmatched = css.split('.admin_manage_scanjobs-unmatched-panel {', 1)[1].split('}', 1)[0]
    assert 'background: transparent' in unmatched
    panel = css.split('.admin_manage_scanjobs-nav-panel {', 1)[1].split('}', 1)[0]
    assert 'background: transparent' in panel
