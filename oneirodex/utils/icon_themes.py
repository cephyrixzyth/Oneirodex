"""Icon / image packs — orthogonal to color CSS themes.

Packs live under ``static/library/icon-themes/{id}/`` with ``manifest.json`` +
``pack.css``. CSS uses ``currentColor`` so packs work with any ``--od-*`` theme.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from flask import current_app, url_for
from oneirodex.utils.library_paths import library_dir

# Semantic keys mirrored from icons.html / icons.tsx (subset for image overrides).
CORE_ICON_KEYS = (
    'discover', 'library', 'download', 'favorites', 'settings', 'systems',
    'user', 'menu', 'more', 'play', 'collections', 'news', 'wishlist',
    'updates', 'playtime', 'calendar', 'ownership',
)

# Packs that ship their own SVG drawings (outline keeps the inline stroke glyphs).
DRAWING_PACKS = ('filled', 'duotone', 'pixel', 'soft', 'mono')
# Preferences chip preview set (keep small — chips are dense).
PACK_GLYPH_KEYS = ('library', 'discover', 'systems', 'download', 'favorites')
# Every key that ships a pack SVG + mask CSS. ``download`` also masks ``downloads``.
PACK_DRAWING_KEYS = PACK_GLYPH_KEYS + (
    'settings',
    'collections',
    'wishlist',
    'updates',
    'ownership',
    'calendar',
    'news',
    'playtime',
    'user',
    'menu',
    'more',
    'play',
)

BUILTIN_PACKS: list[dict[str, Any]] = [
    {
        'id': 'outline',
        'name': 'Outline',
        'description': 'Default 2px stroke icons (matches Oneirodex chrome).',
        'style': 'stroke',
    },
    {
        'id': 'filled',
        'name': 'Filled',
        'description': 'Solid glyphs with lighter stroke — bold on dark glass.',
        'style': 'fill',
    },
    {
        'id': 'duotone',
        'name': 'Duotone',
        'description': 'Soft fill + stroke for depth without changing color theme.',
        'style': 'duotone',
    },
    {
        'id': 'pixel',
        'name': 'Pixel',
        'description': 'Chunky stroke + crisp edges — retro-friendly.',
        'style': 'pixel',
    },
    {
        'id': 'soft',
        'name': 'Soft',
        'description': 'Thinner stroke and softer corners for dense UIs.',
        'style': 'soft',
    },
    {
        'id': 'mono',
        'name': 'Mono block',
        'description': 'Heavy filled marks for high-contrast accessibility.',
        'style': 'mono',
    },
]


def icon_themes_root(package_root: str | Path | None = None) -> Path:
    return Path(library_dir(package_root)) / 'icon-themes'


def setup_icon_themes_source(package_root: str | Path | None = None) -> Path:
    if package_root is not None:
        return Path(package_root) / 'setup' / 'icon_themes'
    return Path(current_app.root_path) / 'setup' / 'icon_themes'


def list_icon_packs() -> list[dict[str, Any]]:
    """Installed packs (filesystem) merged with builtin metadata."""
    root = icon_themes_root()
    by_id = {p['id']: dict(p) for p in BUILTIN_PACKS}
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            manifest_path = child / 'manifest.json'
            meta: dict[str, Any] = {'id': child.name, 'name': child.name.title()}
            if manifest_path.is_file():
                try:
                    meta.update(json.loads(manifest_path.read_text(encoding='utf-8')))
                except (OSError, json.JSONDecodeError):
                    pass
            existing = by_id.get(child.name, {})
            by_id[child.name] = {**existing, **meta, 'id': child.name, 'installed': True}
    out = []
    for pack in BUILTIN_PACKS:
        row = by_id.pop(pack['id'], dict(pack))
        row.setdefault('installed', (icon_themes_root() / pack['id']).is_dir())
        out.append(row)
    for leftover in by_id.values():
        leftover.setdefault('installed', True)
        out.append(leftover)
    return out


def get_icon_pack(pack_id: str | None) -> dict[str, Any]:
    pack_id = (pack_id or 'outline').strip() or 'outline'
    for row in list_icon_packs():
        if row['id'] == pack_id:
            return row
    return {'id': 'outline', 'name': 'Outline', 'installed': True}


def icon_pack_css_url(pack_id: str | None) -> str:
    pack_id = (pack_id or 'outline').strip() or 'outline'
    root = icon_themes_root()
    css = root / pack_id / 'pack.css'
    if css.is_file():
        return url_for('static', filename=f'library/icon-themes/{pack_id}/pack.css')
    fallback = root / 'outline' / 'pack.css'
    if fallback.is_file():
        return url_for('static', filename='library/icon-themes/outline/pack.css')
    return url_for('static', filename='library/icon-themes/outline/pack.css')


def icon_pack_previews_css_url() -> str | None:
    """Always-on sheet so Preferences chips show each pack's drawing without swapping html[data-icon-pack]."""
    path = icon_themes_root() / 'previews.css'
    if path.is_file():
        return url_for('static', filename='library/icon-themes/previews.css')
    return None


def icon_pack_image_url(pack_id: str | None, key: str) -> str | None:
    """Optional branded image override (logo, default_cover)."""
    pack = get_icon_pack(pack_id)
    images = pack.get('images') if isinstance(pack.get('images'), dict) else {}
    rel = images.get(key)
    if not rel:
        return None
    path = icon_themes_root() / pack['id'] / rel
    if path.is_file():
        return url_for('static', filename=f"library/icon-themes/{pack['id']}/{rel}")
    return None


def _pack_glyph_data_icons(key: str) -> tuple[str, ...]:
    """data-icon values that use this pack SVG (rail aliases included)."""
    if key == 'download':
        return ('download', 'downloads')
    return (key,)


def pack_glyph_override_css(pack_id: str, *, url_prefix: str | None = None) -> str:
    """Mask the inline glyph with a pack SVG so packs are drawings, not stroke tints.

    Default URLs are root-absolute under ``/static/library/icon-themes/`` so masks
    still resolve when the pack sheet is swapped at runtime (relative ``icons/``
    URLs were resolving against the document and 404ing).
    """
    if pack_id not in DRAWING_PACKS:
        return ''
    if url_prefix is None:
        url_prefix = f'/static/library/icon-themes/{pack_id}/icons/'
    blocks = []
    for key in PACK_DRAWING_KEYS:
        url = f'{url_prefix}{key}.svg'
        for data_icon in _pack_glyph_data_icons(key):
            blocks.append(
                f'html[data-icon-pack="{pack_id}"] .od-icon[data-icon="{data_icon}"] {{\n'
                f'  background-color: currentColor;\n'
                f'  -webkit-mask: url("{url}") center / contain no-repeat;\n'
                f'  mask: url("{url}") center / contain no-repeat;\n'
                f'}}\n'
                f'html[data-icon-pack="{pack_id}"] .od-icon[data-icon="{data_icon}"] > * {{\n'
                f'  opacity: 0;\n'
                f'}}'
            )
    return '\n'.join(blocks)


def icon_pack_previews_css() -> str:
    """Chip-scoped masks; urls are relative to ``icon-themes/previews.css``."""
    chunks = [
        '/* Chip previews — always loaded so unselected packs still show their drawing. */'
    ]
    for pack_id in DRAWING_PACKS:
        for key in PACK_GLYPH_KEYS:
            url = f'{pack_id}/icons/{key}.svg'
            for data_icon in _pack_glyph_data_icons(key):
                chunks.append(
                    f'.icon-pack-chip[data-icon-pack="{pack_id}"] .od-icon[data-icon="{data_icon}"] {{\n'
                    f'  background-color: currentColor;\n'
                    f'  -webkit-mask: url("{url}") center / contain no-repeat;\n'
                    f'  mask: url("{url}") center / contain no-repeat;\n'
                    f'}}\n'
                    f'.icon-pack-chip[data-icon-pack="{pack_id}"] .od-icon[data-icon="{data_icon}"] > * {{\n'
                    f'  opacity: 0;\n'
                    f'}}'
                )
    return '\n'.join(chunks) + '\n'


def _sync_pack_drawings(src: Path, dest: Path) -> None:
    """Refresh shipped SVGs and pack.css without wiping a customized pack folder."""
    src_icons = src / 'icons'
    if src_icons.is_dir():
        dest_icons = dest / 'icons'
        dest_icons.mkdir(exist_ok=True)
        for svg in src_icons.glob('*.svg'):
            shutil.copy2(svg, dest_icons / svg.name)
    src_css = src / 'pack.css'
    if src_css.is_file():
        shutil.copy2(src_css, dest / 'pack.css')
    src_manifest = src / 'manifest.json'
    if src_manifest.is_file():
        shutil.copy2(src_manifest, dest / 'manifest.json')
    src_preview = src / 'preview.png'
    if src_preview.is_file():
        shutil.copy2(src_preview, dest / 'preview.png')


def _write_pack(dest: Path, meta: dict[str, Any], css: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {
        'id': meta['id'],
        'name': meta['name'],
        'description': meta.get('description') or '',
        'version': '1.0.0',
        'style': meta.get('style') or 'stroke',
        'icons': {k: f'icons/{k}.svg' for k in CORE_ICON_KEYS},
        'images': {},
    }
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (dest / 'pack.css').write_text(css.strip() + '\n', encoding='utf-8')
    (dest / 'icons').mkdir(exist_ok=True)


PACK_CSS: dict[str, str] = {
    'outline': """
/* Outline — default Oneirodex stroke icons; works with any --od-* color theme */
html[data-icon-pack="outline"] .od-icon {
  stroke-width: 2;
  fill: none;
}
""",
    'filled': """
html[data-icon-pack="filled"] .od-icon {
  stroke-width: 1.25;
  fill: currentColor;
  fill-opacity: 0.92;
  stroke-opacity: 0.35;
}
html[data-icon-pack="filled"] .od-icon [fill="currentColor"] {
  fill-opacity: 1;
}
""",
    'duotone': """
html[data-icon-pack="duotone"] .od-icon {
  stroke-width: 1.75;
  fill: currentColor;
  fill-opacity: 0.22;
}
html[data-icon-pack="duotone"] .od-icon [fill="currentColor"] {
  fill-opacity: 0.55;
}
""",
    'pixel': """
html[data-icon-pack="pixel"] .od-icon {
  stroke-width: 2.75;
  stroke-linecap: square;
  stroke-linejoin: miter;
  shape-rendering: crispEdges;
  fill: none;
}
""",
    'soft': """
html[data-icon-pack="soft"] .od-icon {
  stroke-width: 1.35;
  stroke-linecap: round;
  stroke-linejoin: round;
  fill: none;
  opacity: 0.92;
}
""",
    'mono': """
html[data-icon-pack="mono"] .od-icon {
  stroke-width: 0.5;
  fill: currentColor;
  fill-opacity: 1;
  stroke: currentColor;
  stroke-opacity: 0.15;
}
html[data-icon-pack="mono"] .od-icon [fill="none"] {
  fill: currentColor;
}
""",
}

PACK_CSS = {
    pack_id: (
        css.strip()
        + ('\n' + pack_glyph_override_css(pack_id) if pack_id in DRAWING_PACKS else '')
        + '\n'
    )
    for pack_id, css in PACK_CSS.items()
}


def install_icon_themes(*, force: bool = False, package_root: str | Path | None = None) -> list[str]:
    """Install builtin icon packs into static/library/icon-themes."""
    root = icon_themes_root(package_root)
    root.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    source = setup_icon_themes_source(package_root)
    if source.is_dir():
        src_previews = source / 'previews.css'
        if src_previews.is_file():
            shutil.copy2(src_previews, root / 'previews.css')
        for child in source.iterdir():
            if not child.is_dir():
                continue
            dest = root / child.name
            if dest.exists() and not force:
                _sync_pack_drawings(child, dest)
                installed.append(child.name)
                continue
            if dest.exists() and force:
                shutil.rmtree(dest)
            shutil.copytree(child, dest)
            installed.append(child.name)
    for meta in BUILTIN_PACKS:
        dest = root / meta['id']
        if dest.exists() and not force and (dest / 'pack.css').is_file():
            if meta['id'] not in installed:
                installed.append(meta['id'])
            continue
        _write_pack(dest, meta, PACK_CSS.get(meta['id'], PACK_CSS['outline']))
        if meta['id'] not in installed:
            installed.append(meta['id'])
    return installed
