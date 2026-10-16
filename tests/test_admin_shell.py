"""DB-free guards for the Python-built React admin SPA shell."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'oneirodex' / 'templates'
ADMIN_TEMPLATES = TEMPLATES / 'admin'
ADMIN_SHELL = ROOT / 'oneirodex' / 'utils' / 'admin_spa.py'
ADMIN_APP_SRC = ROOT / 'frontend' / 'admin-app' / 'src'
#: How the brand mark is rendered, which is no longer a file reference.
#:
#: It used to be `oneirodex_mark.svg` in an <img src>. That raster bakes the
#: default green and a dark plate into the file, and an external SVG loaded
#: through <img> cannot read the page's custom properties — so on every preset
#: but the default the whole shell changed colour and the mark stayed green.
#: The mark is now painted: a `.od-brand-mark` element masked with a monochrome
#: silhouette and filled with var(--od-accent).
#:
#: Counting the *class* rather than a filename is the same guard one level up.
#: The comment below already argued that naming a location is what keeps
#: breaking this test; naming an asset turned out to have the same flaw, and
#: this is the second half of that lesson.
BRAND_MARK = 'od-brand-mark'

#: The silhouette the class masks, and the stylesheet that paints it. A class
#: reference alone is hollow — it renders a blank box if either is missing.
BRAND_GLYPH = 'oneirodex_glyph.svg'
BRAND_CSS = 'od-shell.css'

#: Admin shell chrome — the components making up the persistent nav frame.
#: Deliberately a *category* rather than a filename: the mark moving between
#: chrome components stays green, which is the whole point of counting, while
#: it leaking into an ordinary page or vanishing from the frame does not.
CHROME_STEM = re.compile(r'^App$|^Admin.*(Nav|Rail|Shell|Chrome)$')
SOURCE_PATTERNS = ('*.jsx', '*.js', '*.tsx', '*.ts')
TEST_SUFFIXES = ('.test.jsx', '.test.js', '.test.tsx', '.test.ts',
                 '.spec.jsx', '.spec.js', '.spec.tsx', '.spec.ts')


def test_python_admin_shell_has_no_member_sidebar_and_loads_the_spa():
    text = ADMIN_SHELL.read_text(encoding='utf-8')
    assert 'id="sidebar"' not in text
    assert 'id="admin-app-root"' in text
    assert 'id="admin-legacy-content"' in text
    assert "admin-app/admin-app.js" in text
    assert "admin-app/admin-app.css" in text


def test_base_admin_loads_spa_assets():
    text = ADMIN_SHELL.read_text(encoding='utf-8')
    assert 'admin-spa' in text
    assert 'csrf-token' in text
    assert 'generate_csrf()' in text


def test_the_admin_brand_mark_is_rendered_by_exactly_one_chrome_component():
    """The mark has now moved twice, and each move broke this guard.

    It first asserted against base_admin.html, was repointed at `AdminTopNav`
    when admin bar one became React, then broke again when GT-B2 moved the
    brand to `AdminSideRail` — repeating it in the top bar was the duplication
    that made admin feel like two navs. Naming the file is what keeps breaking:
    each rewrite re-pinned a location, and the location is the part that
    changes. What the guard actually protects is that admin chrome renders the
    brand exactly once — never zero (a shell with no brand at all) and never
    twice (the GT-B2 duplication coming back). So count instead of naming, and
    a future move of the mark between chrome components stays green on its own.

    A third break, and the same lesson one level up: the mark stopped being a
    raster in an <img> and became a masked `.od-brand-mark` element, so it could
    follow the selected theme. Counting a *filename* re-pinned an asset the way
    the earlier versions re-pinned a location. The class is what "renders the
    brand" now means, so that is what is counted — with the glyph and the
    stylesheet checked separately, since a class whose mask or paint is missing
    renders an invisible box and would otherwise count as success.

    The count is scoped to chrome (`CHROME_STEM`). Counting across all of `src`
    was not the same guard: the mark could drop out of the rail and be picked up
    by any ordinary page, the total would still be one, and the shell would
    render with no brand at all — the zero case this is supposed to catch.
    """
    sources = sorted(
        path
        for pattern in SOURCE_PATTERNS
        for path in ADMIN_APP_SRC.rglob(pattern)
        if not path.name.endswith(TEST_SUFFIXES)
    )
    rendering = [
        path.relative_to(ADMIN_APP_SRC).as_posix()
        for path in sources
        if BRAND_MARK in path.read_text(encoding='utf-8')
    ]
    chrome = [rel for rel in rendering if CHROME_STEM.match(Path(rel).stem)]
    assert len(chrome) == 1, (
        f'expected exactly one admin chrome component to render {BRAND_MARK}, '
        f'found {len(chrome)}: {chrome}'
    )
    outside = [rel for rel in rendering if rel not in chrome]
    assert not outside, (
        f'{BRAND_MARK} is rendered outside admin chrome by {outside} — '
        'the brand belongs to the shell frame, not to a page'
    )
    # A reference alone is hollow if what it points at is gone. For a masked
    # mark that means two things, and missing either renders a blank box rather
    # than failing loudly in the browser.
    glyph = ROOT / 'oneirodex' / 'static' / 'newstyle' / BRAND_GLYPH
    assert glyph.is_file(), f'{BRAND_GLYPH} is missing — .od-brand-mark has nothing to mask'

    paint = ROOT / 'oneirodex' / 'setup' / 'default_theme' / 'css' / BRAND_CSS
    css = paint.read_text(encoding='utf-8')
    assert f'.{BRAND_MARK}' in css, f'no .{BRAND_MARK} rule in {BRAND_CSS}'
    assert BRAND_GLYPH in css, f'.{BRAND_MARK} in {BRAND_CSS} does not reference {BRAND_GLYPH}'
    # The point of the rewrite: the fill follows the theme rather than the file.
    assert '--od-accent' in css.split(f'.{BRAND_MARK}', 1)[1][:400], (
        f'.{BRAND_MARK} does not paint with var(--od-accent) — the mark would '
        'stop following the selected theme, which is the whole reason it is masked'
    )


def test_admin_dashboard_uses_the_non_template_react_shell():
    renderer = (ROOT / 'oneirodex' / 'utils' / 'admin_spa.py').read_text(encoding='utf-8')
    route = (ROOT / 'oneirodex' / 'routes_site.py').read_text(encoding='utf-8')
    assert 'data-admin-render="spa"' in renderer
    assert "render_admin_spa(title='Dashboard · Oneirodex Admin')" in route
    assert not (ADMIN_TEMPLATES / 'admin_dashboard.html').exists()
    for name in ('admin_manage_extensions.html', 'admin_ops.html', 'admin_settings_shell.html', 'storage.html', 'admin_plugins.html'):
        assert not (ADMIN_TEMPLATES / name).exists()


def test_discovery_sections_uses_react_shell():
    route = (ROOT / 'oneirodex' / 'routes_admin_ext' / 'system.py').read_text(encoding='utf-8')
    assert "render_admin_spa(title='Discovery sections · Oneirodex Admin')" in route
    assert not (ADMIN_TEMPLATES / 'admin_discovery_sections.html').exists()


def test_statistics_uses_react_shell():
    route = (ROOT / 'oneirodex' / 'routes_downloads_ext' / 'statistics.py').read_text(encoding='utf-8')
    page = (ADMIN_APP_SRC / 'pages' / 'StatisticsPage.tsx').read_text(encoding='utf-8')
    assert "render_admin_spa(title='Statistics · Oneirodex Admin')" in route
    assert "getJson('/api/admin/statistics')" in page
    assert not (ADMIN_TEMPLATES / 'admin_statistics.html').exists()


def test_features_uses_react_shell():
    route = (ROOT / 'oneirodex' / 'routes_admin_ext' / 'features.py').read_text(encoding='utf-8')
    assert "render_admin_spa(title='Features · Oneirodex Admin')" in route
    assert not (ADMIN_TEMPLATES / 'features_settings.html').exists()


def test_themes_and_authoring_guide_use_react_shell():
    route = (ROOT / 'oneirodex' / 'routes_admin_ext' / 'themes.py').read_text(encoding='utf-8')
    assert "render_admin_spa(title='Themes · Oneirodex Admin')" in route
    assert "render_admin_spa(title='Theme authoring guide · Oneirodex Admin')" in route
    assert not (ADMIN_TEMPLATES / 'admin_manage_themes.html').exists()
    assert not (ADMIN_TEMPLATES / 'admin_manage_themes_readme.html').exists()


def test_server_settings_uses_react_shell():
    route = (ROOT / 'oneirodex' / 'routes_admin_ext' / 'settings.py').read_text(encoding='utf-8')
    assert "render_admin_spa(title='Server settings · Oneirodex Admin')" in route
    assert not (ADMIN_TEMPLATES / 'new_server_settings.html').exists()


def test_arr_module_uses_react_shell():
    route = (ROOT / 'oneirodex' / 'routes_arr.py').read_text(encoding='utf-8')
    assert "render_admin_spa(title='Arr module · Oneirodex Admin')" in route
    assert not (ADMIN_TEMPLATES / 'arr_module.html').exists()


def test_attract_mode_uses_react_shell():
    route = (ROOT / 'oneirodex' / 'routes_admin_ext' / 'attract_mode.py').read_text(encoding='utf-8')
    assert "render_admin_spa(title='Attract mode · Oneirodex Admin')" in route
    assert not (ADMIN_TEMPLATES / 'attract_mode_settings.html').exists()


def test_no_hardcoded_default_theme_js_in_admin_templates():
    remaining = []
    for path in sorted(ADMIN_TEMPLATES.glob('*.html')):
        text = path.read_text(encoding='utf-8')
        if 'library/themes/default/js' in text or "library/themes/' + current_theme" in text:
            remaining.append(path.name)
        if "filename='library/themes/" in text or 'filename="library/themes/' in text:
            remaining.append(path.name)
    assert remaining == [], f'hardcoded theme paths remain in: {remaining}'


def test_admin_app_package_exists():
    pkg = ROOT / 'frontend' / 'admin-app' / 'package.json'
    assert pkg.is_file()
    assert 'admin-app' in pkg.read_text(encoding='utf-8')


def test_ops_dashboard_uses_main_as_page_scroll_under_thn():
    """Ops/Dashboard must not nest a board scrollport under a collapsed THN inset.

    A prior rule set ``padding-top: 0.35rem`` and ``overflow: hidden`` on
    ``.od-admin-main:has(.od-dash)`` with ``overflow: auto`` on ``.od-dash__board``,
    so the board painted past the thin top bar and scrolled as a page-within-a-page.
    Shell contract: main keeps the topbar inset and is the page scrollport.
    """
    css = (ADMIN_APP_SRC / 'ops.css').read_text(encoding='utf-8')
    body = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)

    main_has = re.search(
        r'\.od-admin-main:has\(\.od-dash\)\s*\{([^{}]*)\}',
        body,
    )
    assert main_has, 'missing .od-admin-main:has(.od-dash) rule'
    main_block = main_has.group(1)
    assert 'padding-top: 0.35rem' not in main_block
    assert 'overflow-y: hidden' not in main_block
    assert 'overflow: hidden' not in main_block
    assert 'overflow-y: auto' in main_block

    board = re.search(
        r'\.od-admin-page\s+\.od-dash__board\s*\{([^{}]*)\}',
        body,
    )
    assert board, 'missing .od-dash__board overflow rule'
    board_block = board.group(1)
    assert 'overflow: auto' not in board_block
    assert 'overflow: visible' in board_block
