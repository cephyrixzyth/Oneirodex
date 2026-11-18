"""Game image files on the library volume: safe names, durable writes, safe cleanup."""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def game_filename_key(game_uuid: str) -> str:
    """A fixed, filesystem-safe name component for a game.

    ``game_uuid`` arrives as a route parameter; it never becomes a path
    component directly, so encoded separators or Windows traversal syntax
    cannot escape the image folder.
    """
    return hashlib.sha256(str(game_uuid).encode('utf-8')).hexdigest()[:16]


def publish_image_bytes(save_dir: Path, filename: str, content: bytes) -> Path:
    """Durably write a new, immutable image file before any row points at it."""
    save_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix='.oneirodex-image-', suffix='.tmp', dir=save_dir)
    temporary_path = Path(temporary_name)
    destination = save_dir / filename
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
        if os.name != 'nt' and hasattr(os, 'O_DIRECTORY'):
            directory_fd = os.open(save_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return destination
    finally:
        temporary_path.unlink(missing_ok=True)


def remove_if_unreferenced(session, path: Path, url: str) -> None:
    """Delete an image file only when no image row still points at it.

    Called after the replacing row is committed. Another game may share the
    same file; a failed cleanup leaves a harmless orphan rather than turning a
    completed upload into an error.
    """
    from sqlalchemy import select

    from oneirodex.models import Image

    if session.execute(select(Image.id).where(Image.url == url).limit(1)).first() is not None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning('Obsolete game image cleanup failed after replacement')
