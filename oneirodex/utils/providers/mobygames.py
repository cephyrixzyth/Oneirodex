"""MobyGames Class D metadata search (API key optional — empty when unset)."""

from __future__ import annotations

import os
import re

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.providers.base import mask_api_key

_HTML_TAG_RE = re.compile(r'<[^>]+>')


def get_mobygames_api_key() -> str | None:
    """Resolve MobyGames API key from env, then GlobalSettings.

    Key is optional: callers must treat missing key as honest empty results,
    never as a hard 500. Obtain a key from https://www.mobygames.com/info/api/
    (hobbyist / non-commercial tiers).
    """
    env = (os.getenv('MOBYGAMES_API_KEY') or '').strip()
    if env:
        return env
    try:
        settings = db.session.execute(
            select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
        ).scalars().first()
    except Exception:
        return None
    key = getattr(settings, 'mobygames_api_key', None) if settings else None
    return (key or '').strip() or None


def mobygames_config_hint() -> str:
    key = get_mobygames_api_key()
    if key:
        return f'API key configured ({mask_api_key(key)})'
    return (
        'Set MOBYGAMES_API_KEY (env) or GlobalSettings.mobygames_api_key — '
        'optional; search returns [] when unset. See https://www.mobygames.com/info/api/'
    )


def strip_moby_html(text: str | None) -> str | None:
    """Collapse MobyGames HTML descriptions to plain text for identify UI."""
    if not text:
        return None
    cleaned = _HTML_TAG_RE.sub(' ', str(text))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned or None
