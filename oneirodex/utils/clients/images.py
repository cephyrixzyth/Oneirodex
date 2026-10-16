"""Outbound image download client (IGDB / stored Image rows).

Bodies moved verbatim from ``oneirodex/utils/functions.py`` in wave A2.3.
"""
import logging
import os
import requests
from sqlalchemy import select
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game
from oneirodex.utils.cover_quality import qualify_downloaded_image
from oneirodex.utils.http_safe import (
    MAX_OUTBOUND_IMAGE_BYTES,
    ResponseTooLarge,
    read_response_limited,
    safe_get,
)
from oneirodex.utils.security import validate_user_outbound_http_url

__all__ = ["cover_title_for_uuid", "download_image", "download_stored_image"]

_logger = logging.getLogger(__name__)


def cover_title_for_uuid(game_uuid: str | None) -> str | None:
    """Game name for titled studio-art replacement of a blank cover."""
    if not game_uuid:
        return None
    game = db.session.execute(
        select(Game).filter_by(uuid=game_uuid)
    ).scalars().first()
    return game.name if game else None


def download_image(url, save_path, *, image_type=None, title=None):
    """Download an image from a URL and save it to the specified path.

    Returns (success, error_message). ``error_message`` is ``None`` on
    success so callers (image queue, art studio, batch downloaders) can
    surface *why* a download failed instead of silently marking it done.

    When ``image_type`` is ``cover``, a 200 that is still a 1×1, a stub, or a
    near-solid wash is replaced with titled studio art so the library tile
    is not an empty hole.
    """
    if not url.startswith(('http://', 'https://')):
        url = 'https:' + url

    url = url.replace('/t_thumb/', '/t_original/')

    ok, result = validate_user_outbound_http_url(url)
    if not ok:
        _logger.warning('Rejected outbound image download by URL policy')
        return False, 'Image source was rejected by outbound security policy.'
    url = result

    try:
        # safe_get, not requests.get: the validation above covers the URL we
        # asked for, and a 302 from a valid host to 169.254.169.254 used to be
        # followed without any further check. Every hop is revalidated now.
        with requests.Session() as session:
            response = safe_get(
                url,
                validator=validate_user_outbound_http_url,
                timeout=30,
                session=session,
                stream=True,
            )
            try:
                if response.status_code != 200:
                    error = f"HTTP {response.status_code} downloading image."
                    _logger.warning('Image download returned HTTP status %s', response.status_code)
                    return False, error
                image_bytes = read_response_limited(response, MAX_OUTBOUND_IMAGE_BYTES)
            finally:
                response.close()

        if image_bytes:
            directory = os.path.dirname(save_path)

            if not os.path.exists(directory):
                try:
                    os.makedirs(directory, exist_ok=True)
                except OSError as exc:
                    _logger.warning(
                        'Could not create image storage directory (%s)', type(exc).__name__,
                    )
                    return False, 'Could not create the image storage directory.'

            if os.access(directory, os.W_OK):
                with open(save_path, 'wb') as f:
                    f.write(image_bytes)
                return qualify_downloaded_image(
                    save_path, image_type=image_type, title=title,
                )
            else:
                _logger.warning('Image storage directory is not writable')
                return False, 'The image storage directory is not writable.'
        else:
            error = 'Downloaded image response was empty.'
            return False, error
    except ResponseTooLarge:
        return False, f'Downloaded image exceeds {MAX_OUTBOUND_IMAGE_BYTES} bytes.'
    except requests.exceptions.RequestException as exc:
        _logger.warning('Image download request failed (%s)', type(exc).__name__)
        return False, 'Network error while downloading the image.'
    except OSError as exc:
        _logger.warning('Image storage operation failed (%s)', type(exc).__name__)
        return False, 'Could not save the downloaded image.'
    except Exception as exc:
        _logger.warning('Unexpected image download failure (%s)', type(exc).__name__)
        return False, 'Unexpected error while downloading the image.'


def download_stored_image(image, save_path, *, title=None):
    """Download an ``Image`` row, qualifying covers with the game title."""
    if title is None:
        title = cover_title_for_uuid(image.game_uuid)
    return download_image(
        image.download_url,
        save_path,
        image_type=image.image_type,
        title=title,
    )
