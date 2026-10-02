"""Resolve game cover URLs for browse/favorites/discover JSON payloads."""

import hashlib
import logging
import os

from flask import current_app, url_for

from oneirodex.utils.cover_art_studio import generated_root, render_cover_art
from oneirodex.utils.library_paths import library_dir
from oneirodex.utils.preset_themes import DEFAULT_ERA, era_for_theme

logger = logging.getLogger(__name__)

DEFAULT_COVER_STATIC = 'newstyle/default_cover.jpg'

# Per-title placeholders are cached under static/library/generated/covers so
# repeat requests for the same untitled game reuse the rendered file.
_PLACEHOLDER_COVER_SUBDIR = 'covers'


def _default_cover_url():
    return url_for('static', filename=DEFAULT_COVER_STATIC)


def _placeholder_slug(title):
    return hashlib.sha1(title.strip().lower().encode('utf-8')).hexdigest()[:20]


def _current_theme_era() -> tuple[str, str]:
    """Active theme slug + era room for placeholder art.

    Unauthenticated / no preference falls back to the default wood den so
    untitled tiles still get room scenery rather than a flat green slab.
    """
    slug = 'default'
    try:
        from flask_login import current_user

        if (
            getattr(current_user, 'is_authenticated', False)
            and getattr(current_user, 'preferences', None)
        ):
            slug = current_user.preferences.theme or 'default'
    except Exception:
        slug = 'default'
    return slug, era_for_theme(slug)


def _placeholder_cover_filename(title):
    """Render (or reuse a cached) branded placeholder cover for ``title``.

    Returns a ``static``-relative filename, or ``None`` when rendering isn't
    possible (missing app context, disk error, etc.) so callers fall back to
    the generic default cover instead of erroring the page.
    """
    title = (title or '').strip()
    if not title:
        return None
    try:
        theme_slug, era = _current_theme_era()
        covers_dir = generated_root() / _PLACEHOLDER_COVER_SUBDIR
        filename = f'{_placeholder_slug(title)}_{theme_slug}.jpg'
        dest = covers_dir / filename
        if not dest.is_file():
            covers_dir.mkdir(parents=True, exist_ok=True)
            img = render_cover_art(
                600, 900, title=title, variant='tile', era=era or DEFAULT_ERA,
            )
            img.convert('RGB').save(dest, format='JPEG', quality=88, optimize=True)
        return f'library/generated/{_PLACEHOLDER_COVER_SUBDIR}/{filename}'
    except Exception as exc:
        logger.debug('Cover placeholder render failed for %r: %s', title, exc)
        return None


def _fallback_cover_url(title=None):
    """Prefer a per-title branded placeholder over the boring static default."""
    filename = _placeholder_cover_filename(title)
    if filename:
        return url_for('static', filename=filename)
    return _default_cover_url()


def _normalize_remote_url(url):
    """Turn IGDB protocol-relative URLs into absolute https URLs."""
    if not url:
        return ''
    url = url.strip()
    if url.startswith('//'):
        return f'https:{url}'
    return url


def _local_cover_path(filename):
    return os.path.join(library_dir(), 'images', filename.lstrip('/\\'))


def _local_cover_exists(filename):
    if not filename:
        return False
    try:
        return os.path.isfile(_local_cover_path(filename))
    except OSError:
        return False


def _resolve_from_parts(url, download_url, is_downloaded, title=None):
    """Resolve a browser-usable URL from primary + remote fallback parts."""
    default = _fallback_cover_url(title)
    url = _normalize_remote_url(url)
    download_url = _normalize_remote_url(download_url)

    if not url and not download_url:
        return default

    if url.startswith(('http://', 'https://')):
        return url

    if url.startswith('/static/'):
        # Already an app-static path — only trust it if the file exists when
        # it points at library images; otherwise fall back.
        if '/library/images/' in url:
            filename = url.split('/library/images/', 1)[-1]
            if _local_cover_exists(filename):
                return url
            if download_url.startswith(('http://', 'https://')):
                return download_url
            return default
        return url

    # Local library filename (normal Image.url shape)
    if url and is_downloaded and _local_cover_exists(url):
        return url_for('static', filename=f"library/images/{url.lstrip('/')}")

    if download_url.startswith(('http://', 'https://')):
        return download_url

    # Bare IGDB-ish host path without scheme
    if url.startswith('images.igdb.com/') or url.startswith('www.igdb.com/'):
        return f'https://{url}'

    return default


def resolve_cover_url(cover_image, title=None):
    """Return a browser-usable cover URL for an Image row, string path, or default.

    Prefer a local static file when it is downloaded *and present on disk*.
    Otherwise prefer the remote download_url / http url. Never point at a
    missing local path (that yields blank tiles with no recoverable image).

    Also accepts a plain string (legacy ``Game.cover`` column / absolute URL).
    Empty ``Image.url`` with a remote ``download_url`` still resolves remotely.
    When no cover is resolvable, a per-title branded placeholder is used
    instead of the generic static default when ``title`` is given.
    """
    if isinstance(cover_image, str):
        return _resolve_from_parts(cover_image, '', False, title=title)

    if not cover_image:
        return _fallback_cover_url(title)

    url = getattr(cover_image, 'url', None) or ''
    download_url = getattr(cover_image, 'download_url', None) or ''
    is_downloaded = bool(getattr(cover_image, 'is_downloaded', False))
    return _resolve_from_parts(url, download_url, is_downloaded, title=title)


def resolve_game_cover_url(game, cover_image=None):
    """Resolve cover for a game, falling back to legacy ``Game.cover`` string.

    Falls back to a titled placeholder (Pillow-rendered, cached on disk)
    rather than the static ``default_cover.jpg`` when the game has a name.
    """
    title = getattr(game, 'name', None) if game is not None else None
    primary = resolve_cover_url(cover_image, title=title)
    default = _fallback_cover_url(title)
    if primary != default:
        return primary
    legacy = getattr(game, 'cover', None) if game is not None else None
    if legacy:
        return resolve_cover_url(legacy, title=title)
    return default
