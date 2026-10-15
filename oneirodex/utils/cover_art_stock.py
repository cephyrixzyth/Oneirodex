"""Stock + platform image packs for Art Studio (Pillow-only, selectable by operators).

Extends ``cover_art_studio`` — does not fork a second renderer. Packs land under
``static/library/stock/{pack_id}/`` with the same size matrix as generated packs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Library
from oneirodex.utils.static_urls import static_asset_url
from oneirodex.utils.cover_art_studio import (
    SIZE_MATRIX,
    SYSTEM_TEMPLATES,
    ERA_ART,
    SystemPalette,
    _filename_for,
    _image_to_bytes,
    _pick_library_file,
    render_cover_art,
    resolve_pack_dir,
    resolve_system_template,
    safe_stock_dir,
    stock_root,
)
from oneirodex.utils.play_rooms import room_id_for_platform

# Motif key → (label, palette). Original geometry only — never scraped box art.
StockPalette = SystemPalette  # (top, bottom, accent, glyph_unused)

STOCK_MOTIFS: dict[str, dict[str, Any]] = {
    'controller': {
        'id': 'stock-controller',
        'label': 'Controller silhouette',
        'palette': ((18, 28, 40), (8, 12, 18), (47, 214, 123), 'mark'),
    },
    'cartridge': {
        'id': 'stock-cartridge',
        'label': 'Cartridge geometry',
        'palette': ((48, 16, 20), (18, 8, 10), (220, 72, 72), 'cart'),
    },
    'disc_ring': {
        'id': 'stock-disc-ring',
        'label': 'Disc ring',
        'palette': ((16, 24, 48), (8, 10, 22), (100, 140, 255), 'disc'),
    },
    'crt_grid': {
        'id': 'stock-crt-grid',
        'label': 'CRT grid',
        'palette': ((12, 28, 16), (6, 12, 8), (80, 220, 120), 'pc'),
    },
    'neon_court': {
        'id': 'stock-neon-court',
        'label': 'Neon court',
        'palette': ((24, 12, 40), (10, 6, 18), (200, 80, 220), 'mark'),
    },
    'dpad': {
        'id': 'stock-dpad',
        'label': 'D-pad lattice',
        'palette': ((28, 20, 12), (12, 8, 6), (232, 168, 56), 'cart'),
    },
    'circuit': {
        'id': 'stock-circuit',
        'label': 'Circuit traces',
        'palette': ((10, 24, 28), (6, 10, 12), (64, 200, 180), 'pc'),
    },
    'pixel_burst': {
        'id': 'stock-pixel-burst',
        'label': 'Pixel burst',
        'palette': ((32, 12, 28), (14, 6, 12), (255, 100, 140), 'mark'),
    },
    'joystick': {
        'id': 'stock-joystick',
        'label': 'Arcade stick',
        'palette': ((40, 8, 16), (16, 4, 8), (255, 60, 80), 'cabinet'),
    },
    'hex_lattice': {
        'id': 'stock-hex-lattice',
        'label': 'Hex lattice',
        'palette': ((12, 32, 36), (6, 14, 16), (60, 200, 200), 'pc'),
    },
    'waveform': {
        'id': 'stock-waveform',
        'label': 'Signal waveform',
        'palette': ((20, 16, 40), (8, 8, 18), (140, 120, 255), 'mark'),
    },
    'vault_mark': {
        'id': 'stock-vault-mark',
        'label': 'Vault mark',
        'palette': ((20, 24, 32), (11, 13, 16), (47, 214, 123), 'mark'),
    },
}

# Decade-room backup packs — same setting language as UI themes / play rooms.
ERA_STOCK_PACKS: list[dict[str, str]] = [
    {
        'id': 'era-80s-den',
        'era': 'wood_den_80s',
        'label': '1980s wood den',
        'motif': 'crt_grid',
    },
    {
        'id': 'era-90s-bedroom',
        'era': 'teen_bedroom_90s',
        'label': '1990s teen bedroom',
        'motif': 'cartridge',
    },
    {
        'id': 'era-late90s-den',
        'era': 'carpet_den_late_90s',
        'label': 'Late-90s carpet den',
        'motif': 'disc_ring',
    },
    {
        'id': 'era-00s-media',
        'era': 'media_center_00s',
        'label': '2000s media centre',
        'motif': 'controller',
    },
    {
        'id': 'era-arcade-floor',
        'era': 'arcade_cabinet',
        'label': 'Arcade floor',
        'motif': 'joystick',
    },
    {
        'id': 'era-computer-desk',
        'era': 'desk',
        'label': 'Computer desk',
        'motif': 'circuit',
    },
]

# Major LibraryPlatform / Art Studio system keys → selectable platform packs.
MAJOR_PLATFORM_PACKS: list[dict[str, str]] = [
    {'id': 'platform-nes', 'key': 'nes', 'label': 'NES'},
    {'id': 'platform-snes', 'key': 'snes', 'label': 'SNES'},
    {'id': 'platform-n64', 'key': 'n64', 'label': 'Nintendo 64'},
    {'id': 'platform-gba', 'key': 'gba', 'label': 'Game Boy Advance'},
    {'id': 'platform-gb', 'key': 'gb', 'label': 'Game Boy'},
    {'id': 'platform-gbc', 'key': 'gbc', 'label': 'Game Boy Color'},
    {'id': 'platform-nds', 'key': 'nds', 'label': 'Nintendo DS'},
    {'id': 'platform-ngc', 'key': 'ngc', 'label': 'GameCube'},
    {'id': 'platform-wii', 'key': 'wii', 'label': 'Wii'},
    {'id': 'platform-switch', 'key': 'switch', 'label': 'Switch'},
    {'id': 'platform-psx', 'key': 'psx', 'label': 'PlayStation'},
    {'id': 'platform-ps2', 'key': 'ps2', 'label': 'PS2'},
    {'id': 'platform-ps3', 'key': 'ps3', 'label': 'PS3'},
    {'id': 'platform-psp', 'key': 'psp', 'label': 'PSP'},
    {'id': 'platform-sega-md', 'key': 'sega_md', 'label': 'Mega Drive / Genesis'},
    {'id': 'platform-sega-saturn', 'key': 'sega_saturn', 'label': 'Saturn'},
    {'id': 'platform-sega-dc', 'key': 'sega_dc', 'label': 'Dreamcast'},
    {'id': 'platform-pcwin', 'key': 'pcwin', 'label': 'PC Windows'},
    {'id': 'platform-pcdos', 'key': 'pcdos', 'label': 'PC DOS'},
    {'id': 'platform-arcade', 'key': 'arcade', 'label': 'Arcade'},
    {'id': 'platform-xbox', 'key': 'xbox', 'label': 'Xbox'},
    {'id': 'platform-x360', 'key': 'x360', 'label': 'Xbox 360'},
]


def _stock_static_path(pack_id: str, filename: str) -> str:
    """Static URL path for a stock pack file (works outside request context)."""
    return f'/static/library/stock/{pack_id}/{filename}'


def _stock_static_url(pack_id: str, filename: str) -> str:
    try:
        return static_asset_url(f'library/stock/{pack_id}/{filename}')
    except RuntimeError:
        return _stock_static_path(pack_id, filename)


def _pack_generated(pack_dir: Path) -> bool:
    return pack_dir.is_dir() and (pack_dir / 'tile_400x600.webp').is_file()


def _catalog_entry(
    *,
    pack_id: str,
    label: str,
    kind: str,
    platform: str | None,
    package_root: str | Path | None,
) -> dict[str, Any]:
    pack_dir = safe_stock_dir(pack_id, package_root)
    generated = _pack_generated(pack_dir)
    return {
        'id': pack_id,
        'label': label,
        'kind': kind,
        'platform': platform,
        'pack_id': pack_id,
        'path': f'library/stock/{pack_id}',
        'urls': {
            'tile': _stock_static_url(pack_id, 'tile_400x600.webp'),
            'wide': _stock_static_url(pack_id, 'wide_960x540.webp'),
            'hero': _stock_static_url(pack_id, 'hero_1280x720.webp'),
        },
        'generated': generated,
    }


def list_stock_catalog(package_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Return platform + stock motif catalog entries (urls always present)."""
    items: list[dict[str, Any]] = []
    for pack in MAJOR_PLATFORM_PACKS:
        items.append(
            _catalog_entry(
                pack_id=pack['id'],
                label=pack['label'],
                kind='platform',
                platform=pack['key'],
                package_root=package_root,
            )
        )
    for motif_key, meta in STOCK_MOTIFS.items():
        items.append(
            _catalog_entry(
                pack_id=meta['id'],
                label=meta['label'],
                kind='stock',
                platform=None,
                package_root=package_root,
            )
        )
    for pack in ERA_STOCK_PACKS:
        items.append(
            _catalog_entry(
                pack_id=pack['id'],
                label=pack['label'],
                kind='era',
                platform=None,
                package_root=package_root,
            )
        )
    return items


def _motif_key_for_pack_id(pack_id: str) -> str | None:
    for key, meta in STOCK_MOTIFS.items():
        if meta['id'] == pack_id:
            return key
    return None


def _platform_key_for_pack_id(pack_id: str) -> str | None:
    for pack in MAJOR_PLATFORM_PACKS:
        if pack['id'] == pack_id:
            return pack['key']
    return None


def _era_key_for_pack_id(pack_id: str) -> str | None:
    for pack in ERA_STOCK_PACKS:
        if pack['id'] == pack_id:
            return pack['era']
    return None


def _all_pack_ids() -> list[str]:
    return (
        [p['id'] for p in MAJOR_PLATFORM_PACKS]
        + [m['id'] for m in STOCK_MOTIFS.values()]
        + [p['id'] for p in ERA_STOCK_PACKS]
    )


def generate_size_matrix_stock(
    *,
    title: str,
    system: str | None = None,
    motif: str | None = None,
    palette: SystemPalette | None = None,
    era: str | None = None,
    fmt: str = 'webp',
) -> dict[str, bytes]:
    fmt = (fmt or 'webp').lower()
    if fmt not in ('webp', 'png'):
        fmt = 'webp'
    out: dict[str, bytes] = {}
    for prefix, w, h in SIZE_MATRIX:
        img = render_cover_art(
            w,
            h,
            title=title,
            system=system,
            variant=prefix,
            artistic=True,
            motif=motif,
            palette_override=palette,
            era=era,
        )
        name = _filename_for(prefix, w, h, fmt)
        out[name] = _image_to_bytes(img, fmt)
    return out


def save_stock_pack(
    pack_id: str,
    *,
    package_root: str | Path | None = None,
    fmt: str = 'webp',
) -> dict[str, Any]:
    """Idempotent write of one platform or stock pack under library/stock/."""
    motif_key = _motif_key_for_pack_id(pack_id)
    platform_key = _platform_key_for_pack_id(pack_id)
    era_key = _era_key_for_pack_id(pack_id)
    if motif_key is None and platform_key is None and era_key is None:
        raise ValueError(f'Unknown stock/platform pack id: {pack_id}')

    pack_dir = safe_stock_dir(pack_id, package_root)
    pack_dir.mkdir(parents=True, exist_ok=True)

    era_used = ''
    if era_key is not None:
        pack_meta = next(p for p in ERA_STOCK_PACKS if p['id'] == pack_id)
        title = pack_meta['label']
        art = ERA_ART[era_key]
        palette: SystemPalette = (art['top'], art['bottom'], art['accent'], art['glyph'])
        files = generate_size_matrix_stock(
            title=title,
            motif=pack_meta['motif'],
            palette=palette,
            era=era_key,
            fmt=fmt,
        )
        kind = 'era'
        system = ''
        motif_key = pack_meta['motif']
        era_used = era_key
    elif motif_key is not None:
        meta = STOCK_MOTIFS[motif_key]
        title = meta['label']
        palette = meta['palette']
        files = generate_size_matrix_stock(
            title=title,
            motif=motif_key,
            palette=palette,
            fmt=fmt,
        )
        kind = 'stock'
        system = ''
    else:
        assert platform_key is not None
        pack_meta = next(p for p in MAJOR_PLATFORM_PACKS if p['id'] == pack_id)
        title = pack_meta['label']
        system = platform_key
        # Ensure template exists
        if platform_key not in SYSTEM_TEMPLATES and platform_key.replace('_', ' ') not in SYSTEM_TEMPLATES:
            resolve_system_template(platform_key)
        era_used = room_id_for_platform(platform_key)
        files = generate_size_matrix_stock(
            title=title,
            system=platform_key,
            era=era_used,
            fmt=fmt,
        )
        kind = 'platform'

    written: list[str] = []
    for name, data in files.items():
        (pack_dir / name).write_bytes(data)
        written.append(name)

    manifest = {
        'pack_id': pack_id,
        'title': title,
        'system': system,
        'kind': kind,
        'motif': motif_key or '',
        'era': era_used,
        'format': fmt,
        'files': written,
    }
    (pack_dir / 'manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n',
        encoding='utf-8',
    )
    return manifest


def generate_stock_packs(
    ids: list[str] | None = None,
    *,
    package_root: str | Path | None = None,
    fmt: str = 'webp',
) -> dict[str, Any]:
    """Generate (or regenerate) stock/platform packs. Idempotent overwrite."""
    stock_root(package_root).mkdir(parents=True, exist_ok=True)
    target_ids = ids if ids else _all_pack_ids()
    unknown = [i for i in target_ids if i not in _all_pack_ids()]
    if unknown:
        raise ValueError(f'Unknown pack ids: {", ".join(unknown)}')
    results = []
    for pack_id in target_ids:
        results.append(save_stock_pack(pack_id, package_root=package_root, fmt=fmt))
    return {'generated': results, 'count': len(results)}


def apply_pack_to_library(
    pack_id: str,
    library_uuid: str,
    *,
    package_root: str | Path | None = None,
    static_url_path: str | None = None,
) -> dict[str, Any]:
    """Set Library.image_url to the pack's wide/hero static path."""
    library = db.session.execute(
        select(Library).filter_by(uuid=library_uuid)
    ).scalars().first()
    if not library:
        raise LookupError('Library not found')
    pack_dir = resolve_pack_dir(pack_id, package_root)
    if not pack_dir.is_dir() or not any(pack_dir.glob('tile_*')):
        raise FileNotFoundError('Pack not found — generate stock packs first')
    fmt = 'webp'
    manifest_path = pack_dir / 'manifest.json'
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        fmt = (manifest.get('format') or 'webp').lower()
    src = _pick_library_file(pack_dir, fmt)
    rel_parent = 'library/stock' if pack_dir.parent.name == 'stock' else 'library/generated'
    if static_url_path is None:
        image_url = static_asset_url(f'{rel_parent}/{pack_id}/{src.name}')
    else:
        image_url = (
            f"{static_url_path.rstrip('/')}/{rel_parent}/{pack_id}/{src.name}"
        )
    library.image_url = image_url
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {
        'library_uuid': library_uuid,
        'pack_id': pack_id,
        'image_url': image_url,
        'filename': src.name,
    }
