"""Icon pack registry unit tests."""

from __future__ import annotations

import re
from pathlib import Path

from oneirodex.utils.icon_themes import (
    BUILTIN_PACKS,
    CORE_ICON_KEYS,
    DRAWING_PACKS,
    PACK_CSS,
    PACK_DRAWING_KEYS,
    PACK_GLYPH_KEYS,
    PACK_STYLED_DATA_ICONS,
    _pack_base_selector,
    pack_glyph_override_css,
)

REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / 'oneirodex' / 'setup' / 'icon_themes'


def test_builtin_packs_have_css():
    assert len(BUILTIN_PACKS) >= 6
    for pack in BUILTIN_PACKS:
        assert pack['id'] in PACK_CSS
        assert 'od-icon' in PACK_CSS[pack['id']] or pack['id'] == 'outline'


def test_core_icon_keys_cover_nav():
    for key in ('library', 'download', 'discover', 'settings', 'favorites'):
        assert key in CORE_ICON_KEYS


def test_setup_icon_themes_seeded():
    for pack in BUILTIN_PACKS:
        assert (SETUP / pack['id'] / 'manifest.json').is_file()
        assert (SETUP / pack['id'] / 'pack.css').is_file()
    assert (SETUP / 'previews.css').is_file()


def test_drawing_packs_ship_pack_drawing_key_svgs():
    assert set(PACK_GLYPH_KEYS).issubset(PACK_DRAWING_KEYS)
    assert set(PACK_DRAWING_KEYS) == set(CORE_ICON_KEYS)
    for pack_id in DRAWING_PACKS:
        for key in PACK_DRAWING_KEYS:
            svg = SETUP / pack_id / 'icons' / f'{key}.svg'
            assert svg.is_file(), svg
            text = svg.read_text(encoding='utf-8')
            assert '<svg' in text
        css = SETUP / pack_id / 'pack.css'
        body = css.read_text(encoding='utf-8')
        assert f'[data-icon="library"]' in body
        assert f'[data-icon="settings"]' in body
        assert pack_glyph_override_css(pack_id) in PACK_CSS[pack_id]


def test_drawing_pack_base_styles_only_target_icons_with_pack_drawings():
    supported = set(PACK_STYLED_DATA_ICONS)
    assert 'downloads' in supported
    assert 'activity' not in supported
    for pack_id in DRAWING_PACKS:
        expected = _pack_base_selector(pack_id)
        source = (SETUP / pack_id / 'pack.css').read_text(encoding='utf-8')
        fallback = PACK_CSS[pack_id]
        assert source.splitlines()[0] == f'{expected} {{'
        assert fallback.splitlines()[0] == f'{expected} {{'
        assert 'activity' not in source.splitlines()[0]
        assert 'activity' not in fallback.splitlines()[0]


def test_member_rail_icon_exposes_data_icon():
    """`data-icon` is what the icon-pack CSS hooks onto, so it must survive.

    The glyphs moved to `@oneirodex/ui` (one module instead of two copies that
    had drifted), and the member path is now a re-export shim — so this reads
    the shared module. A source-text assertion has to follow the source.
    """
    text = (REPO / 'frontend' / 'shared' / 'src' / 'railIcons.tsx').read_text(encoding='utf-8')
    assert 'data-icon={canonicalName}' in text
    assert 'sharedIconAliases[name] ?? name' in text

    # And the old paths still resolve, or every call site breaks.
    for shim in (
        REPO / 'frontend' / 'member-app' / 'src' / 'chrome' / 'railIcons.tsx',
        REPO / 'frontend' / 'admin-app' / 'src' / 'components' / 'railIcons.tsx',
    ):
        assert 'RailIcon' in shim.read_text(encoding='utf-8'), shim


def test_chrome_icon_components_expose_leftover_data_icons():
    text = (REPO / 'frontend' / 'member-app' / 'src' / 'chrome' / 'icons.tsx').read_text(
        encoding='utf-8'
    )
    for key in ('user', 'menu'):
        assert f'RailIcon name="{key}"' in text


def test_preferences_pack_chips_preview_pack_glyph_keys():
    component = (
        REPO / 'frontend' / 'shared' / 'src' / 'PreferencesModal.tsx'
    ).read_text(encoding='utf-8')
    chip = component.split('id="iconPackPreview"', 1)[1].split('icon-pack-chip-label', 1)[0]
    keys = tuple(
        match.group(1)
        for match in re.finditer(r'RailIcon name="([a-z]+)"', chip)
    )
    assert keys == PACK_GLYPH_KEYS
