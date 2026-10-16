"""Shared helpers for custom (admin-curated) Discover shelves.

Named for what it makes: **one shelf**, built from a manual pick list or a
simple filter. It was `discovery_zones.py` until 2026-09-06 and called the same
thing a "custom zone", one letter away from `discover_zones.py`, where a zone is
a *page* of shelves that a custom shelf from here can appear on (UID-059). Two
defensible names, unusable together; this module gave the word up because the
other meaning is the one a member sees in the product.

`section_type='custom'` is unchanged — the rename is names, not stored data.

A DiscoverySection with section_type='custom' stores its game selection in
its JSON `config` column, either a manual UUID pick list or a simple
library/platform/genre filter. This module is the single place that
validates that config and resolves it into `Game` rows so the admin CRUD
routes (oneirodex/routes_admin_ext/system.py) and the member Discover feed
(oneirodex/routes_discover.py) stay in sync.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Genre, Library
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.library_acl import apply_game_access_filters

MAX_MANUAL_GAMES = 60
FILTER_TYPES = ('library', 'platform', 'genre')


def normalize_manual_uuids(raw: Any) -> list[str]:
    """Clean a manual game UUID list from a textarea string or JSON array."""
    if isinstance(raw, str):
        raw_items: list[str] = raw.replace(',', '\n').splitlines()
    elif isinstance(raw, (list, tuple)):
        raw_items = list(raw)
    else:
        raw_items = []

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw_items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
        if len(cleaned) >= MAX_MANUAL_GAMES:
            break
    return cleaned


def validate_shelf_config(
    mode: str,
    *,
    game_uuids: Any = None,
    filter_type: Optional[str] = None,
    filter_value: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Validate + normalize a custom shelf config payload.

    Returns (config, error). config is None when error is set.
    """
    mode = (mode or '').strip().lower()
    if mode == 'manual':
        uuids = normalize_manual_uuids(game_uuids)
        if not uuids:
            return None, 'Manual mode needs at least one game UUID'
        known = set(
            db.session.execute(
                select(Game.uuid).where(Game.uuid.in_(uuids))
            ).scalars().all()
        )
        matched = [u for u in uuids if u in known]
        if not matched:
            return None, 'None of the provided game UUIDs were found'
        return {'mode': 'manual', 'game_uuids': matched}, None

    if mode == 'filter':
        filter_type = (filter_type or '').strip().lower()
        filter_value = (filter_value or '').strip()
        if filter_type not in FILTER_TYPES:
            return None, 'filter_type must be one of: library, platform, genre'
        if not filter_value:
            return None, 'filter_value is required'
        if filter_type == 'platform' and filter_value not in LibraryPlatform.__members__:
            return None, f'Unknown platform "{filter_value}"'
        if filter_type == 'library':
            exists = db.session.execute(
                select(Library.uuid).filter_by(uuid=filter_value)
            ).scalar_one_or_none()
            if not exists:
                return None, f'Unknown library "{filter_value}"'
        if filter_type == 'genre':
            exists = db.session.execute(
                select(Genre.id).filter_by(name=filter_value)
            ).scalar_one_or_none()
            if not exists:
                return None, f'Unknown genre "{filter_value}"'
        return {'mode': 'filter', 'filter_type': filter_type, 'filter_value': filter_value}, None

    return None, 'mode must be "manual" or "filter"'


def _filter_shelf_query(config: dict):
    """Base (unfiltered by ACL, unlimited) select for a filter-mode shelf."""
    filter_type = config.get('filter_type')
    filter_value = config.get('filter_value')
    query = select(Game).order_by(Game.date_created.desc())

    if filter_type == 'library':
        return query.where(Game.library_uuid == filter_value)
    if filter_type == 'platform':
        platform_enum = LibraryPlatform.__members__.get(filter_value)
        if platform_enum is None:
            return None
        return query.join(Library, Game.library_uuid == Library.uuid).where(
            Library.platform == platform_enum
        )
    if filter_type == 'genre':
        return query.where(Game.genres.any(Genre.name == filter_value))
    return None


def resolve_custom_shelf_games(config: Optional[dict], user, limit: int = 8) -> list:
    """Resolve a custom shelf's `config` into member-visible `Game` rows (ACL-applied)."""
    if not config:
        return []
    mode = config.get('mode')

    if mode == 'manual':
        uuids = config.get('game_uuids') or []
        if not uuids:
            return []
        rows = db.session.execute(
            apply_game_access_filters(select(Game).where(Game.uuid.in_(uuids)), user)
        ).scalars().all()
        by_uuid = {game.uuid: game for game in rows}
        ordered = [by_uuid[u] for u in uuids if u in by_uuid]
        return ordered[:limit] if limit else ordered

    if mode == 'filter':
        query = _filter_shelf_query(config)
        if query is None:
            return []
        query = apply_game_access_filters(query, user)
        if limit:
            query = query.limit(limit)
        return db.session.execute(query).scalars().all()

    return []


def count_custom_shelf_games(config: Optional[dict]) -> int:
    """Raw (non-ACL) item count for the admin management list."""
    if not config:
        return 0
    mode = config.get('mode')

    if mode == 'manual':
        uuids = config.get('game_uuids') or []
        if not uuids:
            return 0
        return db.session.execute(
            select(func.count(Game.uuid)).where(Game.uuid.in_(uuids))
        ).scalar() or 0

    if mode == 'filter':
        query = _filter_shelf_query(config)
        if query is None:
            return 0
        return db.session.execute(
            select(func.count()).select_from(query.subquery())
        ).scalar() or 0

    return 0


def describe_shelf_config(config: Optional[dict]) -> str:
    """Human-readable one-liner for the admin shelf list."""
    if not config:
        return 'Custom shelf'
    mode = config.get('mode')
    if mode == 'manual':
        count = len(config.get('game_uuids') or [])
        return f"Manual pick \u2014 {count} game{'s' if count != 1 else ''}"
    if mode == 'filter':
        filter_type = config.get('filter_type', '?')
        filter_value = config.get('filter_value', '?')
        return f"Filter \u2014 {filter_type}: {filter_value}"
    return 'Custom shelf'
