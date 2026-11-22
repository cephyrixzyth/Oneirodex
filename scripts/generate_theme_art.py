"""Generate Oneirodex's per-theme art: icon packs, avatars, fallback covers and heroes.

Everything is drawn in code (scripts/theme_art/*), so the shipped files can be
reviewed as diffs and rebuilt after a design change:

    python scripts/generate_theme_art.py

Writes:
  oneirodex/setup/icon_themes/<pack>/        icons/*.svg, manifest.json, pack.css
  oneirodex/setup/icon_themes/previews.css   chip previews for every drawing pack
  oneirodex/setup/theme_art/<theme>/         avatars/*.svg, art/placeholders/{cover,hero}.svg
  oneirodex/setup/default_theme/avatars/     the default theme's drawn avatars
  oneirodex/static/newstyle/avatars/         same, as the un-themed fallback
  oneirodex/static/newstyle/                 default_cover.jpg/.svg, default_library*.jpg/.svg
  oneirodex/static/icons/                    app icons and favicons with the Oneirodex mark

Rasters (JPG/PNG) are rendered with the bundled headless Chromium.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oneirodex.utils.icon_themes import (  # noqa: E402
    BUILTIN_PACKS,
    CORE_ICON_KEYS,
    DRAWING_PACKS,
    PACK_CSS,
    PACK_GLYPH_KEYS,
    _pack_glyph_data_icons,
)
from scripts.theme_art import avatars as avatar_art  # noqa: E402
from scripts.theme_art import placeholders  # noqa: E402
from scripts.theme_art.icons import GLYPHS, render_pack  # noqa: E402

SETUP = ROOT / 'oneirodex' / 'setup'
STATIC = ROOT / 'oneirodex' / 'static'

# Which drawing each theme uses. 'outline' keeps the inline stroke glyphs.
THEME_ICON_STYLE = {
    'default': ('outline', 'outline'),
    'greenhouse': ('sprout', 'sprout'),
    'afterglow': ('pixel', 'pixel'),
    'monochrome': ('hairline', 'hairline'),
    'signal': ('dial', 'badge'),
    'tape-deck': ('bubble', 'bubble'),
    'deep-space': ('orbit', 'orbit'),
    'tideglass': ('engraved', 'engraved'),
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def write_icon_packs() -> None:
    meta = {p['id']: p for p in BUILTIN_PACKS}
    for theme, (pack_id, style) in THEME_ICON_STYLE.items():
        if pack_id == 'outline':
            continue
        pack_dir = SETUP / 'icon_themes' / pack_id
        for name, svg in render_pack(style).items():
            _write(pack_dir / 'icons' / f'{name}.svg', svg)
        info = meta[pack_id]
        manifest = {
            'id': pack_id,
            'name': info['name'],
            'description': info['description'],
            'version': '2.0.0',
            'style': info['style'],
            'icons': {key: f'icons/{key}.svg' for key in CORE_ICON_KEYS if key in GLYPHS},
            'images': {},
        }
        _write(pack_dir / 'manifest.json', json.dumps(manifest, indent=2) + '\n')
        _write(pack_dir / 'pack.css', PACK_CSS[pack_id])


def write_previews_css() -> None:
    rules = ['/* Chip previews: always loaded so unselected packs still show their drawing. */']
    for pack_id in DRAWING_PACKS:
        for key in PACK_GLYPH_KEYS:
            if not (SETUP / 'icon_themes' / pack_id / 'icons' / f'{key}.svg').is_file():
                continue
            for data_icon in _pack_glyph_data_icons(key):
                sel = f'.icon-pack-chip[data-icon-pack="{pack_id}"] .od-icon[data-icon="{data_icon}"]'
                url = f'{pack_id}/icons/{key}.svg'
                rules.append(
                    f'{sel} {{\n  background-color: currentColor;\n'
                    f'  -webkit-mask: url("{url}") center / contain no-repeat;\n'
                    f'  mask: url("{url}") center / contain no-repeat;\n}}\n'
                    f'{sel} > * {{\n  opacity: 0;\n}}'
                )
    _write(SETUP / 'icon_themes' / 'previews.css', '\n'.join(rules) + '\n')


def write_avatars() -> None:
    try:
        for theme in avatar_art.THEME_AVATAR_STYLE:
            for name, svg in avatar_art.render_avatars(theme).items():
                _write(SETUP / 'theme_art' / theme / 'avatars' / f'{name}.svg', svg)
                if theme == 'default':
                    _write(SETUP / 'default_theme' / 'avatars' / f'{name}.svg', svg)
                    _write(STATIC / 'newstyle' / 'avatars' / f'{name}.svg', svg)
    finally:
        avatar_art.close_rasterizer()


def write_placeholders() -> None:
    for theme in placeholders.THEME_ART:
        base = SETUP / 'theme_art' / theme / 'art' / 'placeholders'
        _write(base / 'cover.svg', placeholders.render_cover(theme))
        _write(base / 'hero.svg', placeholders.render_hero(theme))
        if theme == 'default':
            # The default theme is also the tree every preset is copied from.
            default_base = SETUP / 'default_theme' / 'art' / 'placeholders'
            _write(default_base / 'cover.svg', placeholders.render_cover(theme))
            _write(default_base / 'hero.svg', placeholders.render_hero(theme))
    for theme in placeholders.THEME_ART:
        # Title-less cover backgrounds; the server sets each game's title on them.
        _raster(placeholders.render_cover_blank(theme), STATIC / 'newstyle' / 'covers' / f'{theme}.jpg', 600, 900, 'jpeg')
    _write(STATIC / 'newstyle' / 'covers' / 'fonts.json', json.dumps(placeholders.PLACEHOLDER_TITLE_FONT, indent=2) + '\n')
    _write(STATIC / 'newstyle' / 'covers' / 'colors.json', json.dumps(
        {theme: {'text': t['text'], 'muted': t['muted'], 'accent': t['accent']} for theme, t in placeholders.THEME_ART.items()},
        indent=2) + '\n')
    cover = placeholders.render_cover('default')
    hero = placeholders.render_hero('default')
    _write(STATIC / 'newstyle' / 'default_cover.svg', cover)
    _write(STATIC / 'newstyle' / 'default_library.svg', hero)
    _raster(cover, STATIC / 'newstyle' / 'default_cover.jpg', 600, 900, 'jpeg')
    _raster(hero, STATIC / 'newstyle' / 'default_library.jpg', 960, 540, 'jpeg')
    _raster(hero, STATIC / 'newstyle' / 'default_library_large.jpg', 1920, 1080, 'jpeg')


def write_default_room() -> None:
    """The default theme's own room (the presets have painted ones)."""
    from io import BytesIO

    from PIL import Image

    from scripts.theme_art.room import render_default_room

    png = STATIC / 'newstyle' / 'rooms' / '_oneirodex.png'
    _raster(render_default_room(), png, 1920, 1080, 'png')
    Image.open(png).convert('RGB').save(STATIC / 'newstyle' / 'rooms' / 'oneirodex.webp', 'WEBP', quality=82, method=6)
    png.unlink()
    del BytesIO


def write_app_icons() -> None:
    icon = placeholders.render_app_icon('default', 512)
    _write(STATIC / 'icons' / 'oneirodex-mark.svg', icon)
    for name, size in (('oneirodex-512.png', 512), ('oneirodex-256.png', 256), ('icon-192.png', 192),
                       ('apple-touch-icon.png', 180), ('favicon-48.png', 48), ('favicon-32.png', 32),
                       ('favicon.png', 64)):
        _raster(icon, STATIC / 'icons' / name, size, size, 'png')
    from PIL import Image

    png = Image.open(STATIC / 'icons' / 'favicon-48.png')
    png.save(STATIC / 'icons' / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])


def _raster(svg: str, out: Path, width: int, height: int, fmt: str) -> None:
    from playwright.sync_api import sync_playwright

    out.parent.mkdir(parents=True, exist_ok=True)
    sized = svg.replace('<svg ', f'<svg width="{width}" height="{height}" ', 1)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.set_content(f'<html><body style="margin:0;background:transparent">{sized}</body></html>')
        options = {'path': str(out), 'clip': {'x': 0, 'y': 0, 'width': width, 'height': height}}
        if fmt == 'jpeg':
            options.update(type='jpeg', quality=90)
        else:
            options.update(type='png', omit_background=True)
        page.screenshot(**options)
        browser.close()


def main() -> int:
    write_icon_packs()
    write_previews_css()
    write_avatars()
    write_placeholders()
    write_default_room()
    write_app_icons()
    print('Theme art written.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
