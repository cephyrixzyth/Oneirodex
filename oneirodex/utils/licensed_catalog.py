"""IGDB licensed-title cache — regional release_dates, not Wikipedia counts."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, IgdbPlatformRelease, Library
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.helpers.platforms import igdb_platform_id_for
from oneirodex.utils.library_acl import apply_game_access_filters
from oneirodex.utils.set_completion import (
    REGION_LABELS,
    REGION_PREF_ORDER,
    is_dat_hash_identify_platform,
    validate_library_platform,
)

# IGDB release_date.region integers. FRA/DEU/ESP/GBR are DAT-only SKUs and
# never appear here. Asia (7) and New Zealand (4) map to OTHER — do not invent.
IGDB_REGION_TO_CODE = {
    1: 'EUR',
    2: 'USA',
    3: 'AUS',
    4: 'OTHER',
    5: 'JPN',
    6: 'CHN',
    7: 'OTHER',
    8: 'WORLD',
    9: 'KOR',
    10: 'BRA',
}

DAT_ONLY_REGIONS = frozenset({'FRA', 'DEU', 'ESP', 'GBR'})

# IGDB category 0 = main game. DLC, mods, and episodes are excluded.
IGDB_MAIN_GAME_CATEGORY = 0
IGDB_PAGE_SIZE = 500
IGDB_MAX_PAGES = 40
IGDB_PAGE_DELAY_S = 0.3

EMPTY_CACHE_NOTE = (
    'No licensed-catalog cache for this platform yet. Counts are IGDB main '
    'games (category 0) with a release_dates.region for this system — not '
    'Wikipedia. An empty cache is not “zero games ever made.” An admin can '
    'refresh from ROM reference sets.'
)

CACHE_HONESTY_NOTE = (
    'Titles are IGDB main games (category 0) that list a release_dates.region '
    'on this platform. DLC and mods are excluded. France / Germany / Spain / '
    'UK rows are DAT regions only — they do not come from IGDB. Native PC '
    'libraries (Windows / DOS / Mac) are not in this report.'
)


def igdb_region_to_code(raw: Any) -> str | None:
    try:
        key = int(raw)
    except (TypeError, ValueError):
        return None
    return IGDB_REGION_TO_CODE.get(key)


def _igdb_platform_id(library_platform: str) -> int:
    igdb_id = igdb_platform_id_for(library_platform)
    if igdb_id is None:
        raise ValueError(f'No IGDB platform id for {library_platform}')
    return igdb_id


def _require_catalog_platform(library_platform: str) -> str:
    key = validate_library_platform(library_platform)
    if not is_dat_hash_identify_platform(key):
        raise ValueError(
            'Licensed catalog is for console and computer ROM libraries, '
            'not Windows/Steam/Mac.'
        )
    _igdb_platform_id(key)
    return key


def _unix_to_dt(raw: Any) -> datetime | None:
    try:
        stamp = int(raw)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc)


def _release_platform_id(entry: dict[str, Any]) -> int | None:
    platform = entry.get('platform')
    if isinstance(platform, dict):
        platform = platform.get('id')
    try:
        return int(platform)
    except (TypeError, ValueError):
        return None


def parse_release_date_rows(
    game_data: dict[str, Any],
    *,
    igdb_platform_id: int | None = None,
) -> list[dict[str, Any]]:
    """Collapse nested IGDB release_dates to one row per region (earliest date)."""
    try:
        igdb_game_id = int(game_data.get('id'))
    except (TypeError, ValueError):
        return []
    name = (game_data.get('name') or '')[:512]
    by_region: dict[str, dict[str, Any]] = {}
    dates = game_data.get('release_dates') or []
    if not isinstance(dates, list):
        return []
    for entry in dates:
        if not isinstance(entry, dict):
            continue
        code = igdb_region_to_code(entry.get('region'))
        if not code:
            continue
        plat = _release_platform_id(entry)
        if igdb_platform_id is not None and plat is not None and plat != igdb_platform_id:
            continue
        released_at = _unix_to_dt(entry.get('date'))
        existing = by_region.get(code)
        if existing is None or (
            released_at is not None
            and (existing['released_at'] is None or released_at < existing['released_at'])
        ):
            by_region[code] = {
                'igdb_game_id': igdb_game_id,
                'region_code': code,
                'igdb_region': int(entry['region']) if entry.get('region') is not None else None,
                'igdb_platform_id': plat if plat is not None else igdb_platform_id,
                'name': name,
                'released_at': released_at,
            }
    return list(by_region.values())


def upsert_releases_from_igdb_payload(
    library_platform: str,
    game_data: dict[str, Any],
    *,
    fetched_at: datetime | None = None,
) -> int:
    """Write cache rows for one identified game. Does not commit."""
    try:
        platform = _require_catalog_platform(library_platform)
    except ValueError:
        return 0
    igdb_platform_id = _igdb_platform_id(platform)
    rows = parse_release_date_rows(game_data, igdb_platform_id=igdb_platform_id)
    if not rows:
        return 0
    now = fetched_at or datetime.now(timezone.utc)
    written = 0
    for row in rows:
        existing = db.session.execute(
            select(IgdbPlatformRelease).filter_by(
                library_platform=platform,
                igdb_game_id=row['igdb_game_id'],
                region_code=row['region_code'],
            )
        ).scalars().first()
        if existing is None:
            existing = IgdbPlatformRelease(
                library_platform=platform,
                igdb_game_id=row['igdb_game_id'],
                region_code=row['region_code'],
            )
            db.session.add(existing)
        existing.igdb_platform_id = row.get('igdb_platform_id')
        existing.igdb_region = row.get('igdb_region')
        existing.name = row['name']
        existing.released_at = row.get('released_at')
        existing.fetched_at = now
        written += 1
    db.session.flush()
    return written


def _igdb_endpoint() -> str:
    try:
        from flask import current_app

        return current_app.config.get(
            'IGDB_API_ENDPOINT',
            'https://api.igdb.com/v4/games',
        )
    except (ImportError, RuntimeError):
        pass
    return 'https://api.igdb.com/v4/games'


def _page_query(igdb_platform_id: int, offset: int) -> str:
    return (
        'fields id, name, first_release_date, release_dates.date, '
        'release_dates.region, release_dates.platform; '
        f'where platforms = ({igdb_platform_id}) & category = ({IGDB_MAIN_GAME_CATEGORY}); '
        f'limit {IGDB_PAGE_SIZE}; offset {offset};'
    )


def refresh_platform_catalog(
    library_platform: str,
    *,
    delay_s: float = IGDB_PAGE_DELAY_S,
    max_pages: int = IGDB_MAX_PAGES,
    request_fn=None,
) -> dict[str, Any]:
    """Replace the cache for one platform. One platform per call."""
    platform = _require_catalog_platform(library_platform)
    igdb_platform_id = _igdb_platform_id(platform)
    if request_fn is None:
        from oneirodex.utils.igdb_api import make_igdb_api_request

        fetch = make_igdb_api_request
    else:
        fetch = request_fn
    endpoint = _igdb_endpoint()
    now = datetime.now(timezone.utc)
    collected: dict[tuple[int, str], dict[str, Any]] = {}
    pages = 0
    fetched_games = 0

    for page in range(max_pages):
        offset = page * IGDB_PAGE_SIZE
        response = fetch(endpoint, _page_query(igdb_platform_id, offset))
        if isinstance(response, dict) and response.get('error'):
            raise RuntimeError(str(response.get('error')))
        if not isinstance(response, list) or not response:
            break
        pages += 1
        fetched_games += len(response)
        for game in response:
            if not isinstance(game, dict):
                continue
            for row in parse_release_date_rows(game, igdb_platform_id=igdb_platform_id):
                key = (row['igdb_game_id'], row['region_code'])
                existing = collected.get(key)
                if existing is None or (
                    row.get('released_at') is not None
                    and (
                        existing.get('released_at') is None
                        or row['released_at'] < existing['released_at']
                    )
                ):
                    collected[key] = row
        if len(response) < IGDB_PAGE_SIZE:
            break
        if delay_s > 0 and page + 1 < max_pages:
            time.sleep(delay_s)

    db.session.execute(
        delete(IgdbPlatformRelease).where(IgdbPlatformRelease.library_platform == platform)
    )
    for row in collected.values():
        db.session.add(
            IgdbPlatformRelease(
                library_platform=platform,
                igdb_game_id=row['igdb_game_id'],
                igdb_platform_id=row.get('igdb_platform_id') or igdb_platform_id,
                region_code=row['region_code'],
                igdb_region=row.get('igdb_region'),
                name=row['name'],
                released_at=row.get('released_at'),
                fetched_at=now,
            )
        )
    db.session.commit()
    unique_titles = len({row['igdb_game_id'] for row in collected.values()})
    return {
        'library_platform': platform,
        'pages': pages,
        'fetched_games': fetched_games,
        'cached_rows': len(collected),
        'unique_titles': unique_titles,
        'fetched_at': now.isoformat(),
        'truncated': pages >= max_pages,
    }


def _owned_igdb_ids(library_platform: str, user) -> set[int]:
    platform = LibraryPlatform[library_platform]
    query = (
        select(Game.igdb_id)
        .join(Library, Game.library_uuid == Library.uuid)
        .filter(Library.platform == platform)
        .filter(Game.igdb_id.isnot(None))
    )
    query = apply_game_access_filters(query, user)
    return {int(row[0]) for row in db.session.execute(query).all() if row[0] is not None}


def licensed_catalog_report(library_platform: str, user) -> dict[str, Any]:
    platform = _require_catalog_platform(library_platform)
    rows = db.session.execute(
        select(IgdbPlatformRelease).filter_by(library_platform=platform)
    ).scalars().all()
    unique_ids = {row.igdb_game_id for row in rows}
    by_region_ids: dict[str, set[int]] = {}
    fetched_at = None
    for row in rows:
        by_region_ids.setdefault(row.region_code, set()).add(row.igdb_game_id)
        if fetched_at is None or (row.fetched_at and row.fetched_at > fetched_at):
            fetched_at = row.fetched_at

    owned = _owned_igdb_ids(platform, user) if unique_ids else set()
    by_region = []
    for code in REGION_PREF_ORDER:
        dat_only = code in DAT_ONLY_REGIONS
        titles_ids = by_region_ids.get(code, set())
        by_region.append(
            {
                'region_code': code,
                'label': REGION_LABELS.get(code, code),
                'titles': len(titles_ids),
                'owned': len(titles_ids & owned),
                'source': 'dat_only' if dat_only else 'igdb',
            }
        )

    empty = not unique_ids
    return {
        'library_platform': platform,
        'unique_titles': len(unique_ids),
        'owned_titles': len(unique_ids & owned) if unique_ids else 0,
        'fetched_at': fetched_at.isoformat() if fetched_at else None,
        'empty': empty,
        'by_region': by_region,
        'note': EMPTY_CACHE_NOTE if empty else CACHE_HONESTY_NOTE,
        'dat_only_regions': sorted(DAT_ONLY_REGIONS),
        'regions': list(REGION_PREF_ORDER),
    }


def cache_age_summary(library_platform: str) -> dict[str, Any]:
    """Lightweight admin chip: row count + newest fetch."""
    platform = validate_library_platform(library_platform)
    count = db.session.execute(
        select(func.count()).select_from(IgdbPlatformRelease).filter_by(
            library_platform=platform
        )
    ).scalar_one()
    latest = db.session.execute(
        select(func.max(IgdbPlatformRelease.fetched_at)).filter_by(
            library_platform=platform
        )
    ).scalar_one()
    return {
        'library_platform': platform,
        'cached_rows': int(count or 0),
        'fetched_at': latest.isoformat() if latest else None,
    }
