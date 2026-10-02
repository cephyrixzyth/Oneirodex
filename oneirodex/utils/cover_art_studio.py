"""Procedural cover art for Oneirodex — aurora tokens, Pillow templates (no cloud AI).

This module is the public face: ``render_cover_art``, the size matrix, pack
storage and applying packs to games. The v11 cycle (H-D.4) moved the tokens
to ``cover_art_tokens``, the painters to ``cover_art_paint`` and the title
typography to ``cover_art_title`` as pure moves; every name callers imported
from here still resolves here.
"""

from __future__ import annotations

import io
import os
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from flask import current_app, url_for
from sqlalchemy import select
from werkzeug.utils import secure_filename

from oneirodex import db
from oneirodex.models import Game, Image as GameImage
from oneirodex.utils.cover_art_paint import (
    pick_art_direction,
    _draw_bezel_frame,
    _draw_stock_geometry,
    _draw_system_glyph,
    _lerp_color,
    _maybe_scanlines,
    _mix_rgb,
    _paint_art_direction,
    _paint_artistic_backdrop,
    _paint_era_scenery,
    _title_secondary_accent,
    _title_seed,
    _vertical_gradient,
)
from oneirodex.utils.cover_art_title import (
    _draw_title_block,
    _draw_title_motif,
)
from oneirodex.utils.cover_art_tokens import (
    DEFAULT_TITLE_SCALE,
    ERA_ART,
    resolve_system_template,
    SIZE_MATRIX,
    SystemPalette,
)

# Re-exports (H-D.4 split): callers and tests import these from this module.
from oneirodex.utils.cover_art_tokens import (  # noqa: F401
    OD_ACCENT,
    OD_BG,
    OD_SURFACE,
    OD_SURFACE_2,
    OD_TEXT,
    OD_TEXT_MUTED,
    SYSTEM_TEMPLATES,
    TITLE_SCALE_MAX,
    TITLE_SCALE_MIN,
    clamp_title_scale,
)
from oneirodex.utils.cover_art_paint import ART_DIRECTIONS  # noqa: F401
from oneirodex.utils.cover_art_title import _fit_title_font  # noqa: F401
from oneirodex.utils.library_paths import library_dir, static_write_dir


SAFE_PACK_ID = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


def _filename_for(prefix: str, width: int, height: int, ext: str) -> str:
    if width == height:
        return f'{prefix}_{width}.{ext}'
    return f'{prefix}_{width}x{height}.{ext}'


KNOWN_FILENAMES = frozenset(
    _filename_for(prefix, w, h, 'webp')
    for prefix, w, h in SIZE_MATRIX
) | frozenset(
    _filename_for(prefix, w, h, 'png')
    for prefix, w, h in SIZE_MATRIX
)


def generated_root(package_root: str | Path | None = None) -> Path:
    return Path(library_dir(package_root)) / 'generated'


def stock_root(package_root: str | Path | None = None) -> Path:
    """Operator-selectable platform / stock packs (stable ids under library/stock/)."""
    return Path(library_dir(package_root)) / 'stock'


def newstyle_root(package_root: str | Path | None = None) -> Path:
    """Where fallback covers are written; served at /static/newstyle/."""
    return static_write_dir('newstyle', package_root=package_root)


def render_cover_art(
    width: int,
    height: int,
    *,
    title: str | None = None,
    system: str | None = None,
    variant: str = 'tile',
    artistic: bool = True,
    motif: str | None = None,
    palette_override: SystemPalette | None = None,
    headline_override: str | None = None,
    subtitle_override: str | None = None,
    title_scale: float = DEFAULT_TITLE_SCALE,
    era: str | None = None,
) -> Image.Image:
    """Render a branded placeholder/cover at the given size with per-system templates.

    When ``title`` is set and ``artistic`` is True (default), composition reflects
    the title via letterform watermark, seed-derived motif, and secondary accent.
    Empty titles still get intentional Oneirodex branding (not an empty box).

    ``motif`` selects an optional stock geometry overlay (controller, crt_grid, …).
    ``palette_override`` bypasses system template lookup (used by stock packs).
    ``era`` paints decade-room scenery (wood den, teen bedroom, …) so backup art
    follows the active UI theme rather than a generic green slab.
    """
    title = (title or '').strip()
    system = (system or '').strip()
    variant = (variant or 'tile').strip().lower()
    motif = (motif or '').strip().lower() or None
    era_key = (era or '').strip()
    if era_key and era_key not in ERA_ART:
        era_key = ''
    if variant not in ('tile', 'wide', 'square', 'hero'):
        if width == height:
            variant = 'square'
        elif width >= height and width / max(height, 1) >= 1.5:
            variant = 'wide'
        else:
            variant = 'tile'

    is_wide = variant in ('wide', 'hero') or (width >= height and width / max(height, 1) >= 1.5)
    is_square = variant == 'square' or width == height

    if palette_override is not None:
        top, bottom, accent, glyph = palette_override
    elif era_key and not system:
        meta = ERA_ART[era_key]
        top, bottom, accent, glyph = meta['top'], meta['bottom'], meta['accent'], meta['glyph']
    else:
        top, bottom, accent, glyph = resolve_system_template(system)
        if era_key:
            meta = ERA_ART[era_key]
            top = _mix_rgb(top, meta['top'], 0.45)
            bottom = _mix_rgb(bottom, meta['bottom'], 0.45)
    seed_key = title if title else f'oneirodex::{system or motif or "default"}::{variant}'
    seed = _title_seed(seed_key)
    secondary = _title_secondary_accent(seed, accent) if artistic else accent

    img = _vertical_gradient(width, height, top=top, bottom=bottom)
    draw = ImageDraw.Draw(img)

    if artistic:
        _paint_artistic_backdrop(
            img,
            top=top,
            bottom=bottom,
            accent=accent,
            secondary=secondary,
            seed=seed,
            variant=variant if not is_wide else ('hero' if variant == 'hero' else 'wide'),
        )
        # Gaming composition, chosen by title seed (GT-B28). This is what makes
        # two covers structurally different rather than the same picture in a
        # different palette.
        direction = pick_art_direction(seed)
        _paint_art_direction(
            img,
            direction=direction,
            accent=accent,
            secondary=secondary,
            top=top,
            bottom=bottom,
            seed=seed,
        )
        draw = ImageDraw.Draw(img)
        if era_key:
            _paint_era_scenery(img, era=era_key, accent=accent, seed=seed)
            draw = ImageDraw.Draw(img)
        if motif:
            _draw_stock_geometry(
                draw,
                width,
                height,
                motif=motif,
                accent=accent,
                secondary=secondary,
                seed=seed,
                variant=variant if not is_wide else ('hero' if variant == 'hero' else 'wide'),
            )
        _draw_title_motif(
            draw,
            width,
            height,
            title=title or 'Oneirodex',
            seed=seed,
            accent=accent,
            secondary=secondary,
            variant=variant if not is_wide else ('hero' if variant == 'hero' else 'wide'),
        )
        frame_variant = (
            'hero' if variant == 'hero'
            else 'wide' if is_wide
            else 'square' if is_square
            else 'tile'
        )
        # A bezel on every cover was half of why they all looked alike. The
        # directions that already own their edges — a CRT tube, a retail box
        # spine, an arcade marquee — draw their own frame, so adding another
        # only doubles it.
        if direction not in ('crt', 'boxart', 'marquee'):
            _draw_bezel_frame(
                draw,
                width,
                height,
                accent,
                secondary,
                variant=frame_variant,
                seed=seed,
            )
        # Scanlines belong to tube-era directions, not to flat or pixel ones.
        if direction in ('crt', 'marquee', 'neon'):
            _maybe_scanlines(img, glyph if not motif else 'cart', seed)
        draw = ImageDraw.Draw(img)
    else:
        accent_h = max(4, height // 64)
        draw.rectangle([0, 0, width, accent_h], fill=accent)
        draw.rectangle([0, height - accent_h, width, height], fill=accent)
        inset = max(8, min(width, height) // 16)
        draw.rectangle(
            [inset, inset + accent_h, width - inset, height - inset - accent_h],
            outline=_lerp_color(accent, (255, 255, 255), 0.35),
            width=max(1, min(width, height) // 200),
        )

    # System glyph — corner/side for titled art so it doesn't fight the monogram
    mark_scale = min(width, height) / (320 if artistic and title else 280)
    if artistic and title:
        if is_wide:
            gx, gy = int(width * 0.88), int(height * 0.22)
        elif is_square:
            gx, gy = width // 2, int(height * 0.42)
        else:
            gx, gy = int(width * 0.82), int(height * 0.22)
    else:
        gx = width // 2
        gy = int(height * (0.26 if not is_wide else 0.32))
    if not motif:
        _draw_system_glyph(draw, gx, gy, mark_scale, glyph, accent)

    if not title:
        headline = 'Oneirodex'
        if is_wide:
            subtitle = system or 'Library'
        else:
            subtitle = system or 'Vault cover'
    else:
        headline = title
        subtitle = system or ('Stock' if motif else 'Oneirodex')

    # FEAT-D4: the operator can override the derived text. An explicit empty
    # subtitle means "no subtitle", which is different from "not supplied" —
    # hence the `is not None` check rather than a truthiness test.
    if headline_override is not None and str(headline_override).strip():
        headline = str(headline_override).strip()
    if subtitle_override is not None:
        subtitle = str(subtitle_override).strip()

    _draw_title_block(
        draw,
        width,
        height,
        headline=headline,
        subtitle=subtitle,
        title_scale=title_scale,
        accent=accent,
        secondary=secondary,
        variant=variant,
        is_wide=is_wide,
        is_square=is_square,
    )

    if is_wide:
        rail = max(3, height // 72)
        bar_w = int(width * 0.35)
        draw.rectangle([0, height - rail * 2, bar_w, height], fill=_mix_rgb(top, accent, 0.4))

    return img


def _image_to_bytes(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    if fmt == 'jpg':
        rgb = img.convert('RGB')
        rgb.save(buf, format='JPEG', quality=90, optimize=True)
    elif fmt == 'webp':
        img.save(buf, format='WEBP', quality=88, method=4)
    else:
        img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def generate_size_matrix(
    title: str,
    *,
    system: str | None = None,
    fmt: str = 'webp',
    headline_override: str | None = None,
    subtitle_override: str | None = None,
    title_scale: float = DEFAULT_TITLE_SCALE,
) -> dict[str, bytes]:
    """Generate all UI sizes for one title.

    Takes the same text overrides as :func:`render_cover_art`. Without them the
    preview could show operator-set text and the generated pack would quietly
    render the derived text instead — a preview that lies about its output is
    worse than no preview.
    """
    fmt = (fmt or 'webp').lower()
    if fmt not in ('webp', 'png'):
        fmt = 'webp'
    out: dict[str, bytes] = {}
    for prefix, w, h in SIZE_MATRIX:
        variant = prefix
        img = render_cover_art(
            w, h, title=title, system=system, variant=variant,
            headline_override=headline_override,
            subtitle_override=subtitle_override,
            title_scale=title_scale,
        )
        name = _filename_for(prefix, w, h, fmt)
        out[name] = _image_to_bytes(img, fmt)
    return out


def safe_pack_dir(pack_id: str, package_root: str | Path | None = None) -> Path:
    if not pack_id or not SAFE_PACK_ID.match(pack_id):
        raise ValueError('Invalid pack id')
    root = generated_root(package_root).resolve()
    target = (root / pack_id).resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise ValueError('Path traversal blocked')
    return target


def safe_stock_dir(pack_id: str, package_root: str | Path | None = None) -> Path:
    if not pack_id or not SAFE_PACK_ID.match(pack_id):
        raise ValueError('Invalid pack id')
    root = stock_root(package_root).resolve()
    target = (root / pack_id).resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        raise ValueError('Path traversal blocked')
    return target


def resolve_pack_dir(pack_id: str, package_root: str | Path | None = None) -> Path:
    """Resolve a pack under stock/ (preferred for stock-/platform- ids) or generated/."""
    if not pack_id or not SAFE_PACK_ID.match(pack_id):
        raise ValueError('Invalid pack id')
    stock = safe_stock_dir(pack_id, package_root)
    generated = safe_pack_dir(pack_id, package_root)
    stock_ready = stock.is_dir() and any(stock.glob('tile_*'))
    gen_ready = generated.is_dir() and any(generated.glob('tile_*'))
    if pack_id.startswith(('stock-', 'platform-')):
        if stock_ready:
            return stock
        if gen_ready:
            return generated
        return stock
    if gen_ready:
        return generated
    if stock_ready:
        return stock
    return generated


def safe_pack_file(pack_id: str, filename: str, package_root: str | Path | None = None) -> Path:
    if filename not in KNOWN_FILENAMES:
        raise ValueError('Unknown art filename')
    pack_dir = resolve_pack_dir(pack_id, package_root)
    path = (pack_dir / secure_filename(filename)).resolve()
    if os.path.commonpath([str(pack_dir.resolve()), str(path)]) != str(pack_dir.resolve()):
        raise ValueError('Path traversal blocked')
    return path


def save_pack(
    title: str,
    *,
    system: str | None = None,
    fmt: str = 'webp',
    pack_id: str | None = None,
    package_root: str | Path | None = None,
    headline_override: str | None = None,
    subtitle_override: str | None = None,
    title_scale: float = DEFAULT_TITLE_SCALE,
) -> dict[str, Any]:
    pack_id = pack_id or uuid.uuid4().hex[:12]
    pack_dir = safe_pack_dir(pack_id, package_root)
    pack_dir.mkdir(parents=True, exist_ok=True)
    files = generate_size_matrix(
        title, system=system, fmt=fmt,
        headline_override=headline_override,
        subtitle_override=subtitle_override,
        title_scale=title_scale,
    )
    written: list[str] = []
    for name, data in files.items():
        dest = pack_dir / name
        dest.write_bytes(data)
        written.append(name)
    manifest = {
        'pack_id': pack_id,
        'title': title,
        'system': system or '',
        'format': fmt,
        'files': written,
    }
    (pack_dir / 'manifest.json').write_text(
        __import__('json').dumps(manifest, indent=2) + '\n',
        encoding='utf-8',
    )
    return manifest


def pack_preview_url(pack_id: str, filename: str = 'tile_400x600.webp') -> str:
    return url_for('static', filename=f'library/generated/{pack_id}/{filename}')


def build_zip_bytes(pack_id: str, package_root: str | Path | None = None) -> bytes:
    pack_dir = resolve_pack_dir(pack_id, package_root)
    if not pack_dir.is_dir():
        raise FileNotFoundError('Pack not found')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(pack_dir.iterdir()):
            if path.is_file():
                zf.write(path, arcname=f'{pack_id}/{path.name}')
    return buf.getvalue()


def _pick_cover_file(pack_dir: Path, fmt: str) -> Path:
    for name in (f'tile_600x900.{fmt}', f'tile_400x600.{fmt}', f'tile_200x300.{fmt}'):
        candidate = pack_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('No tile art in pack')


def _pick_library_file(pack_dir: Path, fmt: str) -> Path:
    for name in (f'wide_1920x1080.{fmt}', f'hero_1280x720.{fmt}', f'wide_960x540.{fmt}'):
        candidate = pack_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('No wide art in pack')


def apply_pack_to_game(
    pack_id: str,
    game_uuid: str,
    *,
    filename: str | None = None,
    package_root: str | Path | None = None,
) -> dict[str, Any]:
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        raise LookupError('Game not found')
    pack_dir = resolve_pack_dir(pack_id, package_root)
    if not pack_dir.is_dir() or not any(pack_dir.glob('tile_*')):
        raise FileNotFoundError('Pack not found')
    if filename:
        src = safe_pack_file(pack_id, filename, package_root)
    else:
        fmt = 'webp'
        manifest_path = pack_dir / 'manifest.json'
        if manifest_path.is_file():
            import json

            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            fmt = (manifest.get('format') or 'webp').lower()
        src = _pick_cover_file(pack_dir, fmt)
    ext = src.suffix.lower() or '.webp'
    file_name = secure_filename(f'{game_uuid}_cover_studio_{uuid.uuid4().hex[:10]}{ext}')
    save_dir = current_app.config['IMAGE_SAVE_PATH']
    os.makedirs(save_dir, exist_ok=True)
    dest = os.path.join(save_dir, file_name)
    dest_path = Path(dest).resolve()
    save_root = Path(save_dir).resolve()
    if os.path.commonpath([str(save_root), str(dest_path)]) != str(save_root):
        raise ValueError('Path traversal blocked')
    dest_path.write_bytes(src.read_bytes())

    existing = db.session.execute(
        select(GameImage).filter_by(game_uuid=game_uuid, image_type='cover')
    ).scalars().all()
    for row in existing:
        db.session.delete(row)

    image = GameImage(
        game_uuid=game_uuid,
        image_type='cover',
        url=file_name,
        download_url='',
        is_downloaded=True,
    )
    db.session.add(image)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        # The file already landed on disk; remove it so we don't leak an
        # orphaned image with no matching database row.
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return {
        'game_uuid': game_uuid,
        'pack_id': pack_id,
        'filename': file_name,
        'cover_url': url_for('static', filename=f'library/images/{file_name}'),
    }


def apply_pack_as_fallback(
    pack_id: str,
    *,
    package_root: str | Path | None = None,
) -> dict[str, str]:
    pack_dir = resolve_pack_dir(pack_id, package_root)
    if not pack_dir.is_dir() or not any(pack_dir.glob('tile_*')):
        raise FileNotFoundError('Pack not found')
    fmt = 'webp'
    manifest_path = pack_dir / 'manifest.json'
    if manifest_path.is_file():
        import json

        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        fmt = (manifest.get('format') or 'webp').lower()
    cover_src = _pick_cover_file(pack_dir, fmt)
    library_src = _pick_library_file(pack_dir, fmt)
    ns_root = newstyle_root(package_root)
    ns_root.mkdir(parents=True, exist_ok=True)
    cover_img = Image.open(cover_src).convert('RGB')
    library_img = Image.open(library_src).convert('RGB')
    cover_dest = ns_root / 'default_cover.jpg'
    library_dest = ns_root / 'default_library.jpg'
    cover_img.save(cover_dest, format='JPEG', quality=90, optimize=True)
    library_img.save(library_dest, format='JPEG', quality=90, optimize=True)
    return {
        'default_cover': str(cover_dest),
        'default_library': str(library_dest),
        'pack_id': pack_id,
    }


def bake_default_fallbacks(package_root: str | Path | None = None) -> dict[str, str]:
    """Write branded default_cover.jpg / default_library.jpg (artistic empty-title pack).

    Blanks use intentional Oneirodex composition (mark, geometric frame, aurora
    field) — regenerable via Admin Art Studio "Set as fallback pack" as well.
    """
    ns_root = newstyle_root(package_root)
    ns_root.mkdir(parents=True, exist_ok=True)
    cover = render_cover_art(600, 900, title='', system='', variant='tile', artistic=True)
    library = render_cover_art(1920, 1080, title='', system='', variant='wide', artistic=True)
    large = render_cover_art(1920, 1080, title='', system='', variant='hero', artistic=True)
    cover_path = ns_root / 'default_cover.jpg'
    library_path = ns_root / 'default_library.jpg'
    large_path = ns_root / 'default_library_large.jpg'
    cover.save(cover_path, format='JPEG', quality=90, optimize=True)
    library.save(library_path, format='JPEG', quality=90, optimize=True)
    large.save(large_path, format='JPEG', quality=90, optimize=True)
    return {
        'default_cover': str(cover_path),
        'default_library': str(library_path),
        'default_library_large': str(large_path),
    }
