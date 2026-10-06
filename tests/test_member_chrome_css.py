"""Member chrome contracts: rail size, pager, chromeless top-bar controls.

Filesystem-only — no app, no database.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
THEME = REPO_ROOT / 'oneirodex' / 'setup' / 'default_theme' / 'css'


def _read(name: str) -> str:
    return (THEME / name).read_text(encoding='utf-8')


def _strip_comments(css: str) -> str:
    return re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)


def _rule(css: str, selector: str) -> str:
    match = re.search(
        re.escape(selector) + r'\s*\{([^}]*)\}',
        css,
    )
    assert match, f'missing rule for {selector}'
    return match.group(1)


def _blocks_for(css: str, selector: str) -> str:
    """Bodies of every rule whose selector list includes `selector`."""
    css = _strip_comments(css)
    bodies = []
    for match in re.finditer(r'([^{}]+)\{([^}]*)\}', css):
        raw = match.group(1).strip()
        if raw.startswith('@'):
            continue
        parts = [part.strip() for part in raw.split(',')]
        if selector in parts:
            bodies.append(match.group(2))
    assert bodies, f'missing rule containing {selector!r}'
    return '\n'.join(bodies)


def test_expanded_rail_icons_are_unscaled_with_matching_labels():
    """Icons stay 1x the column; the column is readable; labels match."""
    density = _read('od-density.css')
    shell = _read('od-shell.css')
    assert '--od-rail-icon-scale: 1;' in density
    assert '--od-rail-icon-w: 1.125rem;' in density
    assert 'font-size: var(--od-font-xs)' in _rule(shell, '.od-rail__link')
    assert 'var(--od-rail-icon-scale, 1)' in shell
    assert 'var(--od-rail-icon-scale, 1.8)' not in shell


def test_expanded_brand_mark_is_independent_of_the_icon_column():
    """Shrinking destination glyphs must not shrink the logo."""
    density = _read('od-density.css')
    shell = _read('od-shell.css')
    assert '--od-rail-mark-expanded: 5.5rem;' in density
    body = _rule(shell, '.od-rail__brand--mark-only .od-rail__mark')
    assert '--od-rail-mark-expanded' in body
    assert 'var(--od-rail-icon-w)' not in body


def test_library_pager_stays_at_the_foot_without_following_or_a_surface():
    """Pager is the library footer, not a sticky overlay with glass chrome."""
    css = _read('games/library_browser.css')
    body = _rule(css, '.pagination-controls')
    assert 'position: sticky' not in body
    assert 'position: static' in body
    assert 'backdrop-filter' not in body or 'backdrop-filter: none' in body
    assert 'border-top' not in body
    assert 'border: 0' in body
    assert 'background: transparent' in body
    assert 'box-shadow: none' in body


def test_library_pager_moves_and_perpage_have_no_segment_box():
    """First/Previous/Next/Last and per-page are words, not a framed control."""
    css = _read('games/library_browser.css')
    moves = _blocks_for(css, '.od-pagination__moves.od-seg')
    assert 'border: 0' in moves
    assert 'background: transparent' in moves
    assert '1px solid' not in moves
    items = _blocks_for(css, '.od-pagination__moves .btn-pagination')
    assert 'border: 0' in items
    assert 'background: transparent' in items
    hover = _blocks_for(
        css, '.od-pagination__moves .btn-pagination:hover:not(:disabled)'
    )
    assert 'border: 0' in hover
    assert 'box-shadow: none' in hover
    perpage = _rule(css, '.dropdown-perpage')
    assert 'border: 0' in perpage
    assert 'backdrop-filter: none' in perpage
    assert 'container-glass' not in perpage
    assert '1px solid' not in perpage
    scoped = _blocks_for(css, '.od-pagination .dropdown-perpage')
    assert 'border: 0' in scoped
    assert 'background: transparent' in scoped


def test_topbar_account_hamburger_and_filters_have_no_resting_outline():
    """Resting stroke is border: 0, not a transparent 1px that still boxes."""
    appbar = _read('od-appbar.css')
    shell = _read('od-shell.css')
    rest = _blocks_for(appbar, '.od-cbtn.od-topbar__account')
    assert 'border: 0' in rest
    assert 'background: transparent' in rest
    toggle = _blocks_for(appbar, '.od-cbtn.od-topbar__rail-toggle')
    assert 'border: 0' in toggle
    filters = _blocks_for(appbar, '.od-topbar__cluster .od-pop > .od-cbtn')
    assert 'border: 0' in filters
    hover = _blocks_for(
        appbar,
        ".od-cbtn.od-topbar__account:hover:not(:disabled):not([aria-disabled='true'])",
    )
    assert 'border: 0' in hover
    assert 'background: color-mix' in hover
    focus = _rule(appbar, '.od-cbtn:focus-visible')
    if 'outline:' not in focus:
        # `_rule` can match `a.od-cbtn:focus-visible` first (substring).
        assert 'outline: 2px solid var(--od-focus-ring' in appbar
    avatar = _rule(shell, '.od-topbar__account-avatar')
    assert 'box-shadow: none' in avatar
    expanded = _rule(shell, ".od-topbar__account[aria-expanded='true']")
    assert 'border: 0' in expanded


def test_account_dropdown_panel_is_a_vertical_menu():
    """Admin uses the same panel classes as member. Layout must live in
    od-shell.css (both shells load it). Member TopNav.css is SPA-only;
    od-chrome.css is scoped to .member-spa-content and never reaches admin."""
    shell = _read('od-shell.css')
    panel = _rule(shell, '.od-topnav__dropdown-panel')
    assert 'position: absolute' in panel
    assert 'flex-direction: column' in panel
    assert 'background: var(--od-surface-2)' in panel
    item = _blocks_for(shell, '.od-topnav__dropdown-panel a')
    assert 'display: block' in item
    assert 'width: 100%' in item


def test_topbar_cluster_is_not_a_shared_outline():
    """Hamburger + Filters are adjacent, not one merged outlined box."""
    appbar = _read('od-appbar.css')
    shell = _read('od-shell.css')
    cluster = _rule(appbar, '.od-cbtn-group.od-topbar__cluster')
    assert 'gap:' in cluster
    child = _blocks_for(appbar, '.od-cbtn-group.od-topbar__cluster > .od-cbtn')
    assert 'margin-inline-start: 0' in child
    assert 'border-radius: var(--od-radius-sm)' in child
    filters = _rule(shell, '.od-topbar__cluster .od-pop > .od-cbtn')
    assert 'margin-inline-start: -1px' not in filters
    assert 'margin-inline-start: 0' in filters
    assert 'border-radius: 0' not in filters


def test_tile_hover_has_no_accent_glow_and_grows_from_center():
    """Enlarge is scale + drop shadow + hover-only outline; origin is the tile centre."""
    components = _strip_comments(_read('components.css'))
    hover = _blocks_for(components, '.game-card:hover')
    assert 'transform: scale(var(--od-tile-hover-scale, 1.25))' in hover
    assert 'transform-origin: center center' in hover
    assert 'z-index: 40' in hover
    assert 'outline: 2px solid' in hover
    assert 'outline-offset: 0' in hover
    assert 'outline-offset: 2px' not in hover
    assert '0 0 33px' not in hover
    shadow = ';'.join(
        part for part in hover.split(';') if 'box-shadow' in part
    )
    assert 'var(--shadow-dark-strong)' in shadow
    assert 'var(--od-accent)' not in shadow

    overlay = _rule(components, ".game-card[data-overlay-open='true']")
    assert 'z-index: 50' in overlay

    # Resting covers are quiet — no hairline or accent ring on every tile.
    rest = _blocks_for(components, '.game-card .game-cover')
    assert 'border-color: transparent' in rest
    assert 'border-width: 0' in rest
    assert '34%' not in rest

    shell = _read('od-shell.css')
    assert 'grid-template-areas: \'rail main\'' in shell
    assert 'grid-area: main' in _rule(shell, '.od-topbar')
    assert 'z-index: 30' in _rule(shell, '.od-topbar')
    # Top bar stays solid at a constant z-index. Hover must not flip the scroll
    # pane above it: the flip toggled between tiles and made the bar blink.
    assert '.od-shell:has(.game-card:hover) .od-topbar' not in shell
    assert 'opacity: 0' not in _rule(shell, '.od-topbar')
    assert 'transition: opacity' not in _rule(shell, '.od-topbar')
    assert '.od-shell:has(.game-card:hover) .od-shell__main' not in shell
    assert '.od-shell:has(.game-card :focus-visible) .od-shell__main' not in shell
    assert 'padding-inline: max(var(--od-gutter), var(--od-tile-hover-bleed-x))' not in shell
    assert 'padding-inline: calc(var(--od-gutter) + var(--od-tile-hover-pad-x))' in shell
    assert 'padding: calc(var(--od-topbar-h) + var(--od-stack)) var(--od-gutter)' in shell
    assert 'overflow-x: clip' in shell
    assert 'overflow-clip-margin-inline:' in shell
    assert '#main-content.od-shell__main:has(.od-library-selection)' in shell
    assert 'calc(var(--od-topbar-h) + 0.15rem)' in shell
    # Cover is 3:4 — upward growth tracks height; side growth tracks width.
    # × 1.5 covers auto-fill 1fr stretch past --od-tile-min.
    assert '* 4 / 3 *' in shell
    assert '* 1.5 + 12px' in shell
    assert '--od-tile-hover-bleed-y:' in shell
    assert '--od-tile-hover-bleed-x:' in shell
    # Catalog Grid shelves must not inherit the Tile hover-pad negative margin
    # (it clipped genre titles under overflow-x: clip).
    assert '[data-library-grid]:not(.catalog-grid-sections)' in shell

    era = _read('od-era.css')
    assert 'transform-origin: center center' in era


SPA_COMPONENTS = REPO_ROOT / 'frontend' / 'member-app' / 'src' / 'components'


def test_discover_news_art_cannot_grow_past_the_cover_box():
    """News images stay within the portrait 2:3 cover frame and the slider."""
    news = (SPA_COMPONENTS / 'NewsCard.css').read_text(encoding='utf-8')
    wrap = _rule(news, '.od-news-card__art-wrap')
    assert 'aspect-ratio: 2 / 3' in wrap
    assert 'max-height: 100%' in wrap
    art = _rule(news, '.od-news-card__art')
    assert 'position: absolute' in art
    assert 'inset: 0' in art
    card = _rule(news, '.od-news-card')
    assert 'height: auto' in card
    assert 'max-height: 100%' in card
    hover_art = _blocks_for(news, '.od-news-card:hover .od-news-card__art-wrap')
    assert 'outline-offset: 0' in hover_art
    assert 'outline-offset: 2px' not in news


def test_discover_hbar_uses_one_gap_token_for_every_row():
    """News must not park the slider on its own offset; every row shares the token."""
    shelf = (SPA_COMPONENTS / 'DiscoverShelf.css').read_text(encoding='utf-8')
    assert '--od-shelf-scrollbar-gap:' in shelf
    hbar = _rule(_strip_comments(shelf), '.od-shelf__hbar')
    assert 'var(--od-shelf-scrollbar-gap)' in hbar
    assert 'news' not in hbar.lower()
    assert '.od-shelf--news' not in shelf
    assert 'data-discover-section=news' not in shelf


def test_legacy_admin_content_fills_its_grid_track():
    """Found by the virtual-device sweep: without width:100% the item shrank to
    fit-content and one unbreakable string widened the page past a phone."""
    shell = _read('od-shell.css')
    body = _blocks_for(shell, 'body.od-shell-host > #admin-legacy-content')
    assert 'width: 100%' in body
    assert 'box-sizing: border-box' in body
