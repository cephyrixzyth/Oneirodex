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

_PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COVERS_DIR = os.path.join(_PACKAGE, 'static', 'newstyle', 'covers')
FONTS_DIR = os.path.join(_PACKAGE, 'setup', 'fonts')
# Bump when the drawing changes so cached placeholders are re-rendered.
PLACEHOLDER_STYLE_VERSION = 't3'


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
# Bundled so the title never depends on what fonts the host (or the Docker
# image, which ships none) happens to have.
FALLBACK_FACE = 'Inter-Bold.otf'

# Title box, as fractions of the cover. The theme art keeps its mark in the
# top third, so the title owns the band below it.
_BOX_LEFT = 0.10
_BOX_TOP = 0.40
_BOX_BOTTOM = 0.91
# Tiles run from 120px wide up; at 120px a cover is drawn at 1/5 scale, so a
# 55px title on the 600px cover is still ~11px on screen.
_MAX_SIZE = 0.18
_MIN_SIZE = 0.085
_MAX_LINES = 5


def _face(name: str, size: int):
    try:
        font = ImageFont.truetype(os.path.join(FONTS_DIR, name), int(size * _FONT_SCALE.get(name, 1)))
    except OSError:
        return None
    try:
        # Orbitron ships as a variable face that defaults to its thinnest weight.
        font.set_variation_by_name('Bold')
    except (OSError, ValueError, AttributeError):
        pass
    return font


def _font(theme: str, size: int):
    fonts, _colors = _meta()
    for name in (fonts.get(theme), FALLBACK_FACE):
        if name:
            font = _face(name, size)
            if font is not None:
                return font
    font = _load_font(size)
    # Pillow >= 10.1 hands back its default as a FreeTypeFont fixed at 10px, so
    # the type alone does not prove a usable face: the size must match too.
    if isinstance(font, ImageFont.FreeTypeFont) and getattr(font, 'size', None) == size:
        return font
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


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _legible(rgb: tuple[int, int, int], floor: float = 0.62) -> tuple[int, int, int]:
    """Lighten a theme colour toward white until it reads on a dark scrim."""
    colour = rgb
    t = 0.0
    while _luminance(colour) < floor and t < 1:
        t += 0.1
        colour = tuple(int(c + (255 - c) * t) for c in rgb)
    return colour


def background_path(theme: str) -> str | None:
    for slug in (theme, 'default'):
        path = os.path.join(COVERS_DIR, f'{slug}.jpg')
        if os.path.isfile(path):
            return path
    return None


def _width(draw, text, font) -> float:
    return draw.textlength(text, font=font)


def _break_word(draw, word: str, font, max_width: int) -> list[str]:
    """Split one word too wide for the box across lines, by characters."""
    parts: list[str] = []
    current = ''
    for ch in word:
        if current and _width(draw, current + ch + '-', font) > max_width:
            parts.append(current + '-')
            current = ch
        else:
            current += ch
    parts.append(current)
    return parts


def _wrap(draw, title: str, font, max_width: int, split_words: bool) -> list[str]:
    lines: list[str] = []
    current = ''
    for word in title.split():
        if _width(draw, word, font) > max_width:
            if not split_words:
                return []
            if current:
                lines.append(current)
            *head, current = _break_word(draw, word, font, max_width)
            lines.extend(head)
            continue
        trial = f'{current} {word}' if current else word
        if _width(draw, trial, font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _line_height(font, size: int) -> int:
    try:
        ascent, descent = font.getmetrics()
        # Pixel faces report tight metrics; keep some air between lines.
        return max(int((ascent + descent) * 1.04), int(size * 1.18))
    except AttributeError:
        return int(size * 1.2)


def _ellipsize(draw, lines: list[str], font, max_width: int) -> list[str]:
    kept = lines[:_MAX_LINES]
    last = kept[-1]
    while last and _width(draw, last + '\u2026', font) > max_width:
        last = last[:-1].rstrip()
    kept[-1] = last + '\u2026'
    return kept


def _layout(draw, title: str, slug: str, max_width: int, max_height: int, width: int):
    """Largest title that fits the box, trying the theme face then the plain one.

    A wide display face (Press Start 2P) can only fit a long title by
    shrinking it below what a small tile can show, so below the floor the
    title switches to the bundled sans instead of shrinking further.
    """
    fonts, _colors = _meta()
    floor = int(width * _MIN_SIZE)
    faces = [slug] if fonts.get(slug) else []
    faces.append('')
    for i, face in enumerate(faces):
        last_face = i == len(faces) - 1
        size = int(width * _MAX_SIZE)
        while size >= floor:
            font = _font(face, size)
            lines = _wrap(draw, title, font, max_width, split_words=last_face and size == floor)
            if lines and len(lines) <= _MAX_LINES and len(lines) * _line_height(font, size) <= max_height:
                return font, size, lines
            size -= 2
    font = _font('', floor)
    lines = _wrap(draw, title, font, max_width, split_words=True)
    if len(lines) > _MAX_LINES:
        lines = _ellipsize(draw, lines, font, max_width)
    return font, floor, lines


def _scrim(img: Image.Image, top: int) -> Image.Image:
    """Darken the title band so the type never sits on busy art."""
    width, height = img.size
    mask = Image.new('L', (1, height), 0)
    fade = max(1, int(height * 0.08))
    for y in range(height):
        if y >= top:
            mask.putpixel((0, y), 150)
        elif y >= top - fade:
            mask.putpixel((0, y), int(150 * (y - (top - fade)) / fade))
    mask = mask.resize((width, height))
    return Image.composite(Image.new('RGB', img.size, (6, 8, 12)), img, mask)


def render_themed_title_cover(title: str, theme: str) -> Image.Image | None:
    path = background_path(theme)
    if not path:
        return None
    slug = os.path.splitext(os.path.basename(path))[0]
    _fonts, colors = _meta()
    palette = colors.get(slug, {})
    text_colour = _legible(_hex(palette.get('text', ''), (240, 245, 250)), 0.75)
    muted_colour = _legible(_hex(palette.get('muted', ''), (170, 180, 190)), 0.4)

    img = Image.open(path).convert('RGB')
    width, height = img.size
    left = int(width * _BOX_LEFT)
    max_width = width - 2 * left
    box_top = int(height * _BOX_TOP)
    box_bottom = int(height * _BOX_BOTTOM)

    note = 'NO COVER ART'
    note_font = _font('', max(14, int(width * 0.05)))
    note_gap = int(width * 0.04)
    note_height = _line_height(note_font, int(width * 0.05))

    draw = ImageDraw.Draw(img)
    font, size, lines = _layout(
        draw, title.strip() or 'Untitled', slug, max_width,
        box_bottom - box_top - note_gap - note_height, width,
    )
    line_height = _line_height(font, size)
    block = len(lines) * line_height + note_gap + note_height
    top = box_top + (box_bottom - box_top - block) // 2

    img = _scrim(img, max(0, top - int(height * 0.03)))
    draw = ImageDraw.Draw(img)
    stroke = max(2, size // 16)
    shadow = max(2, size // 20)
    for i, line in enumerate(lines):
        x = (width - _width(draw, line, font)) / 2
        y = top + i * line_height
        draw.text((x + shadow, y + shadow), line, font=font, fill=(0, 0, 0),
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        draw.text((x, y), line, font=font, fill=text_colour,
                  stroke_width=stroke, stroke_fill=(8, 10, 14))
    note_y = top + len(lines) * line_height + note_gap
    draw.text(((width - _width(draw, note, note_font)) / 2, note_y), note,
              font=note_font, fill=muted_colour, stroke_width=2, stroke_fill=(8, 10, 14))
    return img
