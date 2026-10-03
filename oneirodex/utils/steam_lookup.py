"""Steam Store helpers for App ID → title / type resolution."""

from __future__ import annotations

import logging
import time

import requests

logger = logging.getLogger(__name__)

#: Steam's store API rate-limits (HTTP 429) and sometimes answers 403 to a bare
#: client; both used to read as "this app has no data" and the game stayed blank.
_STEAM_HEADERS = {'User-Agent': 'Oneirodex/1.0 (+https://github.com/chrisjrovira/oneirodex)'}
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def _get_with_retry(url: str, *, timeout: float, attempts: int = 3):
    """GET with a short backoff on rate limits / transient errors."""
    resp = None
    for attempt in range(attempts):
        resp = requests.get(url, timeout=timeout, headers=_STEAM_HEADERS)
        if resp.status_code not in _RETRY_STATUSES or attempt == attempts - 1:
            return resp
        try:
            wait = min(float(resp.headers.get('Retry-After', '')), 5.0)
        except (TypeError, ValueError):
            wait = 1.5 * (attempt + 1)
        time.sleep(wait)
    return resp


def fetch_steam_app_details(app_id: int, *, timeout: float = 10.0) -> dict | None:
    """
    Resolve a Steam App ID to store details (name, type, …).
    Returns None on any failure (network, missing app, unexpected payload).
    """
    if not app_id or not isinstance(app_id, int) or app_id <= 0:
        return None

    url = f'https://store.steampowered.com/api/appdetails?appids={app_id}&l=english'
    try:
        resp = _get_with_retry(url, timeout=timeout)
        if resp.status_code != 200:
            logger.warning('Steam appdetails for %s answered HTTP %s', app_id, resp.status_code)
            return None
        payload = resp.json()
        entry = payload.get(str(app_id)) or {}
        if not entry.get('success'):
            logger.info('Steam appdetails for %s: no data (success=false; delisted or region-locked?)', app_id)
            return None
        data = entry.get('data') or {}
        name = data.get('name')
        if not isinstance(name, str) or not name.strip():
            return None
        steam_type = data.get('type')
        # Carry the full content payload, not just identity: Stage D used to keep
        # only name/type/image/description, so a Steam-identified game landed with
        # no genres, developer, publisher or release date — none of the boxes filled.
        genres = [
            g.get('description', '').strip()
            for g in (data.get('genres') or [])
            if isinstance(g, dict) and (g.get('description') or '').strip()
        ]
        categories = [
            c.get('description', '').strip()
            for c in (data.get('categories') or [])
            if isinstance(c, dict) and (c.get('description') or '').strip()
        ]
        developers = [d for d in (data.get('developers') or []) if isinstance(d, str) and d.strip()]
        publishers = [p for p in (data.get('publishers') or []) if isinstance(p, str) and p.strip()]
        release = data.get('release_date') or {}
        return {
            'steam_app_id': app_id,
            'name': name.strip(),
            'steam_type': (steam_type.strip().lower() if isinstance(steam_type, str) else None),
            'header_image': data.get('header_image'),
            'short_description': data.get('short_description'),
            'genres': genres,
            'categories': categories,
            'developers': developers,
            'publishers': publishers,
            'release_date': (release.get('date') if isinstance(release, dict) else None),
            'coming_soon': bool(release.get('coming_soon')) if isinstance(release, dict) else False,
            'metacritic': ((data.get('metacritic') or {}).get('score')
                           if isinstance(data.get('metacritic'), dict) else None),
            'pc_requirements': data.get('pc_requirements'),
            'mac_requirements': data.get('mac_requirements'),
            'linux_requirements': data.get('linux_requirements'),
            'supported_languages': data.get('supported_languages'),
        }
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        logger.warning('Steam appdetails for %s failed: %s', app_id, type(exc).__name__)
        return None


def fetch_steam_title_by_app_id(app_id: int, *, timeout: float = 5.0) -> str | None:
    """
    Resolve a Steam App ID to its store title.
    Returns None on any failure (network, missing app, unexpected payload).
    """
    details = fetch_steam_app_details(app_id, timeout=timeout)
    return details.get('name') if details else None
