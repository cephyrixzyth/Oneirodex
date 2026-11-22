"""Per-game "no cover" art in the active theme's own design.

The background is the theme's title-less cover (static/newstyle/covers/<theme>.jpg,
drawn by scripts/generate_theme_art.py); this sets the game's title on it in the
theme's lettering. Returns None when the theme art is not installed, so the
caller can fall back to the generic renderer.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from oneirodex.utils.cover_art_paint import _load_font
from oneirodex.utils.cover_art_title import _wrap_title

_PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COVERS_DIR = os.path.join(_PACKAGE, 'static', 'newstyle', 'covers')
FONTS_DIR = os.path.join(_PACKAGE, 'setup', 'fonts')
# Bump when the drawing changes so cached placeholders are re-rendered.
PLACEHOLDER_STYLE_VERSION = 't2'


@lru_cache(maxsize=1)
def _meta() -> tuple[dict, dict]:
    def load(name):
        try:
            with open(os.path.join(COVERS_DIR, name), encoding='utf-8') as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    return load('fonts.json'), load('colors.json')


# Faces whose glyphs sit small for their nominal size.
_FONT_SCALE = {'VT323-Regular.ttf': 1.45}


def _font(theme: str, size: int):
    fonts, _colors = _meta()
    name = fonts.get(theme)
    if name:
        try:
            return ImageFont.truetype(os.path.join(FONTS_DIR, name), int(size * _FONT_SCALE.get(name, 1)))
        except OSError:
            pass
    font = _load_font(size)
    # Pillow >= 10.1 hands back its default as a FreeTypeFont fixed at 10px, so
    # the type alone does not prove a usable face: the size must match too.
    if isinstance(font, ImageFont.FreeTypeFont) and getattr(font, 'size', None) == size:
        return font
    # No system face in the image: Pillow's bundled scalable sans, never the
    # 10px bitmap fallback.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return font


def _hex(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    try:
        value = value.lstrip('#')
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (AttributeError, ValueError):
        return fallback


def background_path(theme: str) -> str | None:
    for slug in (theme, 'default'):
        path = os.path.join(COVERS_DIR, f'{slug}.jpg')
        if os.path.isfile(path):
            return path
    return None


def render_themed_title_cover(title: str, theme: str) -> Image.Image | None:
    path = background_path(theme)
    if not path:
        return None
    slug = os.path.splitext(os.path.basename(path))[0]
    _fonts, colors = _meta()
    palette = colors.get(slug, {})
    text_colour = _hex(palette.get('text', ''), (240, 245, 250))
    muted_colour = _hex(palette.get('muted', ''), (170, 180, 190))

    img = Image.open(path).convert('RGB')
    width, height = img.size
    draw = ImageDraw.Draw(img)
    max_width = int(width * 0.78)

    # Largest size that fits in at most three lines.
    size = int(width * 0.11)
    lines: list[str] = []
    font = _font(slug, size)
    while size > 18:
        font = _font(slug, size)
        lines = _wrap_title(title, font, max_width)
        too_wide = any(draw.textlength(line, font=font) > max_width for line in lines)
        if len(lines) <= 3 and not too_wide:
            break
        size -= 3
    line_height = int(size * 1.22)
    top = int(height * 0.6) - (len(lines) * line_height) // 2
    for i, line in enumerate(lines):
        x = (width - draw.textlength(line, font=font)) / 2
        y = top + i * line_height
        draw.text((x + 2, y + 3), line, font=font, fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=text_colour)
    small = _font(slug, max(14, int(width * 0.035)))
    note = 'No cover art'
    draw.text(((width - draw.textlength(note, font=small)) / 2, top + len(lines) * line_height + int(size * 0.35)),
              note, font=small, fill=muted_colour)
    return img
