"""The member rail is owned by the React shell after template retirement."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_member_shell_mounts_the_react_app_and_has_one_main_region():
    source = (ROOT / 'oneirodex' / 'utils' / 'member_spa.py').read_text(encoding='utf-8')
    assert 'id="member-app-root"' in source
    assert '<div id="content" class="member-spa-content">' in source
    assert '<main id="content"' not in source


def test_member_rail_keeps_accessible_drawer_controls():
    source = (ROOT / 'frontend' / 'member-app' / 'src' / 'chrome' / 'SideRail.tsx').read_text(encoding='utf-8')
    topbar = (ROOT / 'frontend' / 'member-app' / 'src' / 'chrome' / 'TopBar.tsx').read_text(encoding='utf-8')
    app = (ROOT / 'frontend' / 'member-app' / 'src' / 'App.tsx').read_text(encoding='utf-8')
    for required in ('od-primary-navigation', 'od-rail__close', 'aria-modal', 'inert'):
        assert required in source
    assert 'aria-controls="od-primary-navigation"' in topbar
    assert 'aria-expanded=' in topbar
    assert 'od-rail__scrim' in app


def test_rail_destination_links_remain_in_react_navigation():
    source = (ROOT / 'frontend' / 'member-app' / 'src' / 'chrome' / 'navConfig.ts').read_text(encoding='utf-8')
    for href in ('/library', '/downloads', '/collections', '/wishlist', '/big-picture'):
        assert href in source


def test_auth_shell_has_no_member_navigation():
    source = (ROOT / 'oneirodex' / 'utils' / 'member_auth_spa.py').read_text(encoding='utf-8')
    assert 'member-auth' in source
    assert 'id="member-app-root"' not in source
