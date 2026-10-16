"""Apply external artwork URLs into the local Image pipeline."""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from werkzeug.utils import secure_filename

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Image
from oneirodex.utils.image_kinds import (
    IMAGE_KINDS,
    SINGULAR_IMAGE_KINDS,
    image_kinds_error_message,
    parse_image_kind,
)
from oneirodex.utils.providers import get_provider
from oneirodex.utils.runtime_config import get_runtime_config

# Back-compat alias — full locked taxonomy (BE-DET-10).
VALID_IMAGE_TYPES = IMAGE_KINDS


def _extension_from_url_or_type(url: str, content_type: str | None) -> str:
    path = urlparse(url).path.lower()
    for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif'):
        if path.endswith(ext):
            return '.jpg' if ext == '.jpeg' else ext
    if content_type:
        lowered = content_type.split(';')[0].strip().lower()
        if lowered in ('image/png',):
            return '.png'
        if lowered in ('image/webp',):
            return '.webp'
        if lowered in ('image/gif',):
            return '.gif'
    return '.jpg'


def apply_cover_from_url(
    game_uuid: str,
    image_url: str,
    *,
    provider_id: str = 'steamgriddb',
    image_type: str = 'cover',
    config=None,
) -> dict:
    """
    Download an absolute image URL and store it as game artwork.

    Artwork only — never downloads game binaries.
    image_type / kind: cover | screenshot | box | cart | disc | logo | hero | fanart
    """
    try:
        image_type = parse_image_kind(image_type, default='cover')
    except ValueError as exc:
        raise ValueError(image_kinds_error_message()) from exc

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        raise LookupError('Game not found')

    if not image_url or not image_url.startswith(('http://', 'https://')):
        raise ValueError('url must be an absolute http(s) image URL')

    provider = get_provider(provider_id)
    if not provider.is_enabled():
        raise RuntimeError(f'{provider_id} is not configured')

    data, content_type = provider.fetch_image(image_url)
    if not data:
        raise RuntimeError('Downloaded image was empty')

    ext = _extension_from_url_or_type(image_url, content_type)
    file_name = secure_filename(
        f'{game_uuid}_{image_type}_{provider_id}_{uuid.uuid4().hex[:10]}{ext}'
    )
    runtime_config = config if config is not None else get_runtime_config()
    save_dir = runtime_config['IMAGE_SAVE_PATH']
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, file_name)
    with open(save_path, 'wb') as handle:
        handle.write(data)

    # Singular kinds: keep one primary row; screenshots may accumulate.
    if image_type in SINGULAR_IMAGE_KINDS:
        existing = db.session.execute(
            select(Image).filter_by(game_uuid=game_uuid, image_type=image_type)
        ).scalars().all()
        for row in existing:
            db.session.delete(row)

    image = Image(
        game_uuid=game_uuid,
        image_type=image_type,
        url=file_name,
        download_url=image_url,
        is_downloaded=True,
    )
    db.session.add(image)
    db.session.commit()

    static_url_path = (runtime_config.get('STATIC_URL_PATH') or '/static').rstrip('/')
    image_url = f'{static_url_path}/library/images/{file_name}'

    return {
        'game_uuid': game_uuid,
        'image_id': image.id,
        'image_type': image_type,
        'kind': image_type,
        'filename': file_name,
        'cover_url': image_url,
        'url': image_url,
        'provider': provider_id,
    }
