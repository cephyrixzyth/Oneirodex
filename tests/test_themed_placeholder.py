"""The generated "no cover" art must keep the title readable on small tiles."""
from PIL import Image, ImageDraw, ImageFont

from oneirodex.utils import cover_art_paint
from oneirodex.utils import themed_placeholder as tp

LONG = 'Final Fantasy XIV Online: Complete Edition Dawntrail Collector\'s Bundle Deluxe'


def _draw():
    return ImageDraw.Draw(Image.new('RGB', (600, 900)))


def test_font_uses_bundled_face_when_the_host_has_none(monkeypatch):
    # The Docker image ships no system fonts; the title must not fall back to
    # Pillow's thin default face.
    monkeypatch.setattr(cover_art_paint, '_FONT_CANDIDATES', ())
    font = tp._font('default', 80)
    assert isinstance(font, ImageFont.FreeTypeFont)
    assert font.path.endswith(tp.FALLBACK_FACE)
    assert font.size == 80


def test_short_title_is_set_large():
    _font, size, lines = tp._layout(_draw(), 'Celeste', 'default', 480, 400, 600)
    assert lines == ['Celeste']
    assert size >= int(600 * 0.15)


def test_long_title_wraps_and_never_drops_below_the_floor():
    floor = int(600 * tp._MIN_SIZE)
    for slug in ('default', 'afterglow', 'tape-deck', 'deep-space'):
        draw = _draw()
        font, size, lines = tp._layout(draw, LONG, slug, 480, 400, 600)
        assert size >= floor
        assert 1 < len(lines) <= tp._MAX_LINES
        assert all(draw.textlength(line, font=font) <= 480 for line in lines)


def test_wide_theme_face_gives_way_to_the_plain_face_for_long_titles():
    font, _size, _lines = tp._layout(_draw(), LONG, 'afterglow', 480, 400, 600)
    assert font.path.endswith(tp.FALLBACK_FACE)


def test_unbroken_word_is_split_rather_than_overflowing():
    draw = _draw()
    word = 'Supercalifragilisticexpialidociousandthensomemoreletters'
    font, _size, lines = tp._layout(draw, word, 'default', 480, 400, 600)
    assert len(lines) > 1
    assert all(draw.textlength(line, font=font) <= 480 for line in lines)


def test_render_returns_full_size_cover():
    img = tp.render_themed_title_cover(LONG, 'signal')
    assert img is not None and img.size == (600, 900)
