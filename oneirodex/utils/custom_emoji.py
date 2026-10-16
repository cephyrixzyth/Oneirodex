"""Household custom chat emoji (Wave 17b) — admin upload, capped."""

from __future__ import annotations

import os
import re
from io import BytesIO
from uuid import uuid4

from oneirodex.utils.runtime_config import get_runtime_config
from PIL import Image
from sqlalchemy import func, select
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import CustomEmoji, User

SLUG_RE = re.compile(r'^[a-z0-9_-]{2,24}$')
MAX_CUSTOM_EMOJI = 20
MAX_UPLOAD_BYTES = 256 * 1024
MAX_EDGE_PX = 128
ALLOWED_EXT = frozenset({'png', 'webp', 'jpg', 'jpeg'})
ALLOWED_REACTIONS = frozenset({'👍', '❤️', '😂', '🎉', '👀'})


def emoji_dir(upload_folder: str | None = None) -> str:
    root = upload_folder if upload_folder is not None else get_runtime_config().get('UPLOAD_FOLDER') or ''
    path = os.path.join(root, 'chat-emoji')
    os.makedirs(path, exist_ok=True)
    return path


def normalize_slug(raw: str) -> str:
    slug = (raw or '').strip().lower().lstrip(':').rstrip(':')
    if not SLUG_RE.match(slug):
        raise ValueError('Slug must be 2–24 chars: a-z, 0-9, _ or -')
    return slug


def list_custom_emoji() -> list[dict]:
    rows = db.session.execute(
        select(CustomEmoji).order_by(CustomEmoji.slug.asc())
    ).scalars().all()
    return [row.to_dict() for row in rows]


def custom_reaction_keys() -> set[str]:
    return {row.reaction_key() for row in db.session.execute(select(CustomEmoji)).scalars().all()}


def get_by_slug(slug: str) -> CustomEmoji | None:
    try:
        slug = normalize_slug(slug)
    except ValueError:
        return None
    return db.session.execute(
        select(CustomEmoji).where(CustomEmoji.slug == slug)
    ).scalars().first()


def count_custom_emoji() -> int:
    return int(
        db.session.execute(select(func.count()).select_from(CustomEmoji)).scalar() or 0
    )


def upload_custom_emoji(
    *,
    slug: str,
    label: str,
    file: FileStorage,
    uploader: User | None,
    upload_folder: str | None = None,
) -> CustomEmoji:
    if count_custom_emoji() >= MAX_CUSTOM_EMOJI:
        raise ValueError(f'Custom emoji limit reached ({MAX_CUSTOM_EMOJI})')

    slug = normalize_slug(slug)
    if get_by_slug(slug):
        raise ValueError('Slug already exists')

    label = (label or slug).strip()[:64] or slug
    if not file or not getattr(file, 'filename', None):
        raise ValueError('Image file required')

    filename = secure_filename(file.filename or '')
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXT:
        raise ValueError('Only PNG, WebP, or JPEG allowed')

    raw = file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f'File too large (max {MAX_UPLOAD_BYTES // 1024}KB)')
    if not raw:
        raise ValueError('Empty file')

    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:
        raise ValueError(f'Invalid image: {exc}') from exc

    if img.mode not in ('RGB', 'RGBA'):
        img = img.convert('RGBA')
    img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)

    out_name = f'{uuid4().hex}.webp'
    out_path = os.path.join(emoji_dir(upload_folder), out_name)
    img.save(out_path, format='WEBP', quality=85)

    row = CustomEmoji(
        slug=slug,
        label=label,
        file_name=out_name,
        uploaded_by_user_id=getattr(uploader, 'id', None),
    )
    db.session.add(row)
    db.session.commit()
    return row


def delete_custom_emoji(slug: str, *, upload_folder: str | None = None) -> bool:
    row = get_by_slug(slug)
    if row is None:
        return False
    path = os.path.join(emoji_dir(upload_folder), row.file_name)
    db.session.delete(row)
    db.session.commit()
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
    return True
