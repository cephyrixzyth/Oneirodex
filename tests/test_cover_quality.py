"""Blank downloaded covers become titled studio art instead of empty tiles."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image as PILImage

from oneirodex.utils.cover_quality import (
    inspect_cover_file,
    qualify_downloaded_image,
    replace_cover_if_degenerate,
)
from oneirodex.utils.functions import download_image


def _save(path: Path, image: PILImage.Image, fmt='JPEG') -> Path:
    image.convert('RGB').save(path, format=fmt, quality=90)
    return path


def test_solid_wash_is_degenerate(tmp_path):
    path = _save(tmp_path / 'wash.jpg', PILImage.new('RGB', (200, 300), (12, 12, 12)))
    assert inspect_cover_file(str(path)) == 'cover is near-uniform'


def test_tiny_stub_is_degenerate(tmp_path):
    path = _save(tmp_path / 'stub.jpg', PILImage.new('RGB', (8, 8), (40, 180, 90)))
    assert inspect_cover_file(str(path)) == 'cover too small'


def test_empty_file_is_degenerate(tmp_path):
    path = tmp_path / 'empty.jpg'
    path.write_bytes(b'')
    assert inspect_cover_file(str(path)) == 'cover file empty'


def test_varied_artwork_is_kept(tmp_path):
    img = PILImage.new('RGB', (200, 300), (20, 20, 20))
    pixels = img.load()
    for x in range(200):
        for y in range(300):
            pixels[x, y] = (x, y % 256, (x + y) % 256)
    path = _save(tmp_path / 'art.jpg', img)
    assert inspect_cover_file(str(path)) is None


def test_unreadable_bytes_are_degenerate(tmp_path):
    path = tmp_path / 'junk.jpg'
    path.write_bytes(b'not an image at all, but long enough to pass the size gate' * 4)
    reason = inspect_cover_file(str(path))
    assert reason is not None
    assert reason.startswith('cover unreadable')


def test_degenerate_cover_is_replaced_with_titled_art(tmp_path):
    path = _save(tmp_path / 'blank.jpg', PILImage.new('RGB', (200, 300), (0, 0, 0)))
    ok, error = replace_cover_if_degenerate(str(path), 'Portal 2')
    assert ok is True
    assert error is None
    assert inspect_cover_file(str(path)) is None
    # The wash is gone — studio art has structure, not a single colour.
    with PILImage.open(path) as im:
        colours = im.convert('RGB').getcolors(maxcolors=256)
        assert colours is None or len(colours) > 8


def test_screenshots_skip_the_cover_inspect(tmp_path):
    path = _save(tmp_path / 'shot.jpg', PILImage.new('RGB', (200, 300), (0, 0, 0)))
    ok, error = qualify_downloaded_image(str(path), image_type='screenshot', title='Portal 2')
    assert ok is True
    assert error is None
    assert inspect_cover_file(str(path)) == 'cover is near-uniform'


def test_qualify_replaces_only_covers(tmp_path):
    path = _save(tmp_path / 'cover.jpg', PILImage.new('RGB', (200, 300), (8, 8, 8)))
    ok, error = qualify_downloaded_image(str(path), image_type='cover', title='Hades')
    assert ok is True
    assert error is None
    assert inspect_cover_file(str(path)) is None


def _jpeg_bytes(image: PILImage.Image) -> bytes:
    buf = BytesIO()
    image.convert('RGB').save(buf, format='JPEG', quality=90)
    return buf.getvalue()


def test_download_image_replaces_wash_cover(tmp_path, monkeypatch):
    dest = tmp_path / 'cover.jpg'
    response = MagicMock()
    response.status_code = 200
    response.content = _jpeg_bytes(PILImage.new('RGB', (200, 300), (8, 8, 8)))
    response.headers = {}
    response.iter_content.return_value = [response.content]
    monkeypatch.setattr(
        'oneirodex.utils.clients.images.validate_user_outbound_http_url',
        lambda url: (True, url),
    )
    monkeypatch.setattr('oneirodex.utils.clients.images.safe_get', lambda *a, **k: response)

    ok, error = download_image(
        'https://example.com/c.jpg',
        str(dest),
        image_type='cover',
        title='Hades',
    )
    assert ok is True
    assert error is None
    assert dest.is_file()
    assert inspect_cover_file(str(dest)) is None


def test_download_image_leaves_screenshot_wash(tmp_path, monkeypatch):
    dest = tmp_path / 'shot.jpg'
    response = MagicMock()
    response.status_code = 200
    response.content = _jpeg_bytes(PILImage.new('RGB', (200, 300), (0, 0, 0)))
    response.headers = {}
    response.iter_content.return_value = [response.content]
    monkeypatch.setattr(
        'oneirodex.utils.clients.images.validate_user_outbound_http_url',
        lambda url: (True, url),
    )
    monkeypatch.setattr('oneirodex.utils.clients.images.safe_get', lambda *a, **k: response)

    ok, error = download_image(
        'https://example.com/s.jpg',
        str(dest),
        image_type='screenshot',
        title='Hades',
    )
    assert ok is True
    assert error is None
    assert inspect_cover_file(str(dest)) == 'cover is near-uniform'
