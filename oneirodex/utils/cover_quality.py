"""Reject downloaded covers that would render as a blank tile.

A cover that HTTP-200s and writes to disk can still be empty to a person:
IGDB (and other CDNs) sometimes serve a 1×1, a tiny stub, or a near-solid
wash. Browse then prefers that local file over the branded placeholder, so
the library shows a hole where the title should be.

Inspect after a successful download. Near-uniform luma or a canvas smaller
than a tile is degenerate; replace the bytes with ``render_cover_art`` —
the same titled fallback ``cover_url`` already draws when nothing local
exists. Screenshots and other kinds are left alone: a dark loading screen
is real content.
"""

from __future__ import annotations

import logging
import os

from PIL import Image as PILImage
from PIL import ImageStat
from PIL.Image import DecompressionBombError

from oneirodex.utils.cover_art_studio import render_cover_art
from oneirodex.utils.image_upload_limits import (
    GAME_IMAGE_MAX_PIXELS,
    ImageWorkBusy,
    image_decode_work_slot,
)

logger = logging.getLogger(__name__)

#: Shortest edge, in pixels, that can still read as a cover at library size.
MIN_EDGE_PX = 48

#: Luma std-dev below this (0–255) is a wash, not artwork. Photos and
#: generated studio covers sit well above; a solid IGDB stub sits at ~0.
LUMA_STDEV_MIN = 10.0

#: Downsample before measuring so a 4K wash costs the same as a 200px one.
_SAMPLE_EDGE = 48

_COVER_KIND = 'cover'


def inspect_cover_file(path: str) -> str | None:
    """Return a short reason when ``path`` is not a usable cover, else ``None``."""
    if not path or not os.path.isfile(path):
        return 'cover file missing'
    try:
        if os.path.getsize(path) < 32:
            return 'cover file empty'
    except OSError as exc:
        return f'cover unreadable: {exc}'

    try:
        with image_decode_work_slot():
            with PILImage.open(path) as im:
                width, height = im.size
                if width <= 0 or height <= 0 or width * height > GAME_IMAGE_MAX_PIXELS:
                    return 'cover pixel count too large'
                if min(width, height) < MIN_EDGE_PX:
                    return 'cover too small'
                im.load()
                sample = im.convert('L').resize(
                    (_SAMPLE_EDGE, _SAMPLE_EDGE),
                    PILImage.Resampling.BOX,
                )
                stdev = ImageStat.Stat(sample).stddev[0]
    except ImageWorkBusy:
        return 'image processing busy'
    except DecompressionBombError:
        return 'cover pixel count too large'
    except OSError as exc:
        return f'cover unreadable: {exc}'

    if stdev < LUMA_STDEV_MIN:
        return 'cover is near-uniform'
    return None


def replace_cover_if_degenerate(path: str, title: str | None) -> tuple[bool, str | None]:
    """Keep a usable cover; swap a blank one for titled studio art.

    Returns the same ``(success, error)`` pair as ``download_image``. A
    successful replacement is still success — the tile has a cover, just not
    the bytes the CDN sent.
    """
    reason = inspect_cover_file(path)
    if reason is None:
        return True, None
    if reason == 'image processing busy':
        return False, 'Image processing is busy. Try again shortly.'

    logger.info('Replacing degenerate cover %s (%s)', path, reason)
    try:
        img = render_cover_art(600, 900, title=title or '', variant='tile')
        ext = os.path.splitext(path)[1].lower()
        fmt = 'PNG' if ext == '.png' else 'JPEG'
        img.convert('RGB').save(path, format=fmt, quality=88, optimize=True)
        return True, None
    except OSError as exc:
        logger.warning('Generated cover replacement failed for %s: %s', path, exc)
        try:
            os.remove(path)
        except OSError:
            pass
        return False, f'{reason}; generated replacement failed'


def qualify_downloaded_image(
    path: str,
    *,
    image_type: str | None = None,
    title: str | None = None,
) -> tuple[bool, str | None]:
    """No-op for non-covers; inspect-and-replace for ``cover``."""
    if image_type != _COVER_KIND:
        return True, None
    return replace_cover_if_degenerate(path, title)
