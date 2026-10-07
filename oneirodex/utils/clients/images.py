"""Outbound image download client (IGDB / stored Image rows).

Bodies moved verbatim from ``oneirodex/utils/functions.py`` in wave A2.3.
"""
import os
import requests
from sqlalchemy import select
from oneirodex import db
from oneirodex.models import Game
from oneirodex.utils.cover_quality import qualify_downloaded_image
from oneirodex.utils.http_safe import (
    MAX_OUTBOUND_IMAGE_BYTES,
    read_response_limited,
    safe_get,
)
from oneirodex.utils.security import validate_user_outbound_http_url

__all__ = ["cover_title_for_uuid", "download_image", "download_stored_image"]


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
        error = f"Blocked outbound URL: {result}"
        print(f"download_image blocked: {result}")
        return False, error
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
                    print(f"Failed to download the image. Status Code: {response.status_code}")
                    return False, error
                image_bytes = read_response_limited(response, MAX_OUTBOUND_IMAGE_BYTES)
            finally:
                response.close()

        if image_bytes:
            directory = os.path.dirname(save_path)

            if not os.path.exists(directory):
                print(f"'{directory}' does not exist. Attempting to create it.")
                try:
                    os.makedirs(directory, exist_ok=True)
                    print(f"Successfully created the directory '{directory}'.")
                except Exception as e:
                    error = f"Failed to create directory '{directory}': {e}"
                    print(error)
                    return False, error

            if os.access(directory, os.W_OK):
                with open(save_path, 'wb') as f:
                    f.write(image_bytes)
                return qualify_downloaded_image(
                    save_path, image_type=image_type, title=title,
                )
            else:
                error = f"Directory '{directory}' is not writable by the Oneirodex process."
                print(f"Error: {error}")
                return False, error
        else:
            error = 'Downloaded image response was empty.'
            return False, error
    except requests.exceptions.RequestException as e:
        error = f"Network error: {e}"
        print(f"Error downloading image from {url}: {e}")
        return False, error
    except OSError as e:
        error = f"Disk error writing to '{save_path}': {e}"
        print(f"An error occurred while saving the image to {save_path}: {e}")
        return False, error
    except Exception as e:
        error = f"Unexpected error: {e}"
        print(f"An error occurred while saving the image to {save_path}: {e}")
        return False, error


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
