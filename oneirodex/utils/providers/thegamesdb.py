"""TheGamesDB Class D metadata search (API key optional — empty when unset)."""

from __future__ import annotations

import os

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.providers.base import mask_api_key

# Official catalog API — metadata / covers only (never binaries).
TGDB_API_BASE = 'https://api.thegamesdb.net'
TGDB_GAME_PAGE = 'https://thegamesdb.net/game.php?id={id}'
# Key signup: https://thegamesdb.net/api/register.php or https://api.thegamesdb.net/key.php
TGDB_KEY_SIGNUP = 'https://thegamesdb.net/api/register.php'


def get_thegamesdb_api_key() -> str | None:
    """Resolve TheGamesDB API key from env, then GlobalSettings.

    Key is optional: callers must treat missing key as honest empty results,
    never as a hard 500. Obtain a key from TheGamesDB API registration.
    """
    env = (os.getenv('THEGAMESDB_API_KEY') or '').strip()
    if env:
        return env
    try:
        settings = db.session.execute(
            select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
        ).scalars().first()
    except Exception:
        return None
    key = getattr(settings, 'thegamesdb_api_key', None) if settings else None
    return (key or '').strip() or None


def thegamesdb_config_hint() -> str:
    key = get_thegamesdb_api_key()
    if key:
        return f'API key configured ({mask_api_key(key)})'
    return (
        'Set THEGAMESDB_API_KEY (env) or GlobalSettings.thegamesdb_api_key — '
        f'optional; search returns [] when unset. See {TGDB_KEY_SIGNUP}'
    )


def tgdb_game_url(game_id) -> str | None:
    if game_id is None or game_id == '':
        return None
    return TGDB_GAME_PAGE.format(id=game_id)


def pick_tgdb_cover_url(game_id, include_boxart: dict | None) -> str | None:
    """Build a front-boxart CDN URL from Games/ByGameName ``include.boxart``."""
    if not isinstance(include_boxart, dict):
        return None
    base_urls = include_boxart.get('base_url') or {}
    if not isinstance(base_urls, dict):
        return None
    base = (
        base_urls.get('large')
        or base_urls.get('medium')
        or base_urls.get('original')
        or base_urls.get('small')
        or ''
    )
    if not base:
        return None
    data = include_boxart.get('data') or {}
    if not isinstance(data, dict):
        return None
    entries = data.get(str(game_id)) or data.get(game_id) or []
    if not isinstance(entries, list):
        return None
    front = None
    any_box = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get('type') and entry.get('type') != 'boxart':
            continue
        filename = entry.get('filename')
        if not filename:
            continue
        if entry.get('side') == 'front':
            front = filename
            break
        if any_box is None:
            any_box = filename
    filename = front or any_box
    if not filename:
        return None
    return f'{base.rstrip("/")}/{filename.lstrip("/")}'


def resolve_tgdb_platform_name(platform_id, include_platform: dict | None) -> str | None:
    if platform_id is None or not isinstance(include_platform, dict):
        return None
    data = include_platform.get('data') or {}
    if not isinstance(data, dict):
        return None
    plat = data.get(str(platform_id)) or data.get(platform_id)
    if isinstance(plat, dict):
        return plat.get('name') or plat.get('alias')
    return None
