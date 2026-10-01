"""Community anti-cheat compatibility source (INSP-35, v11 cycle H1e).

A kernel-anti-cheat title is one where modding, injection or a Linux seat
risks a ban, and the product should say so where it knows. This module reads
the community-maintained compatibility list (the *areweanticheatyet* class:
one public JSON file, no account, no key) and answers one question per game:
*what do the community reports say about this title's anti-cheat?*

Design rules, in order of importance:

* **Reports, not a guarantee.** Every answer carries the reporting count and
  the source page so the badge can read *"Denied (community reports)"* and
  never *"will ban you"*. Status is one of :data:`STATUSES`.
* **One fetch a day, into the library volume.** :func:`refresh_if_stale`
  downloads the feed through :func:`~oneirodex.utils.http_safe.safe_request`
  and writes it atomically under ``static/library/anticheat/``; a failed
  fetch keeps the previous file. Lookups only ever read that cache -- a
  details page never waits on the network.
* **No data, never a silent miss.** No cache, unparseable cache, a title the
  list does not know: :func:`lookup` returns ``None`` and the UI shows
  nothing. An empty list is not "no anti-cheat".
* **Off under pytest** for the fetch unless a test says otherwise, like the
  other keyless sources; the parser and lookup run against a fixture file.
* **Read-only.** Nothing here writes to a game row; ``game_card_flags``
  derives ``anticheat`` on the way out.

This is also gate (2) for the cheats policy's Option B -- the source has to
exist before that question is askable; nothing here asks it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from flask import current_app, has_app_context

from oneirodex.utils.http_safe import safe_request
from oneirodex.utils.security import validate_user_outbound_http_url
from oneirodex.utils.library_paths import library_dir

logger = logging.getLogger(__name__)

SOURCE_ID = 'anticheat_compat'
DEFAULT_FEED_URL = 'https://raw.githubusercontent.com/AreWeAntiCheatYet/AreWeAntiCheatYet/HEAD/games.json'
DEFAULT_PAGE_URL = 'https://areweanticheatyet.com'
# The community vocabulary, lower-cased. Anything else reads as ``unknown``.
STATUSES = ('supported', 'running', 'planned', 'broken', 'denied', 'unknown')
CACHE_TTL_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 20
# Anti-cheat is a PC story; the name fallback never fires for console shelves.
PC_PLATFORMS = frozenset({'PCWIN', 'PCDOS', 'MAC', 'LINUX', 'OTHER'})

_LOCK = threading.Lock()
_INDEX: dict[str, Any] | None = None
_INDEX_MTIME: float | None = None
_INDEX_CHECKED_AT: float = 0.0
_RECHECK_SECONDS = 60.0


def _truthy(raw: str | None, default: bool) -> bool:
    text = (raw or '').strip().lower()
    if not text:
        return default
    return text in ('1', 'true', 'yes', 'on')


def _testing() -> bool:
    try:
        return bool(has_app_context() and current_app.config.get('TESTING'))
    except Exception:  # noqa: BLE001
        return False


def is_enabled() -> bool:
    """On by default; ``ENABLE_ANTICHEAT_COMPAT=false`` turns the whole source off."""
    return _truthy(os.environ.get('ENABLE_ANTICHEAT_COMPAT'), True)


def fetch_allowed() -> bool:
    """The network half: enabled, and not under pytest unless the test opts in."""
    if not is_enabled():
        return False
    if _testing() and not _truthy(os.environ.get('ANTICHEAT_COMPAT_IN_TESTS'), False):
        return False
    return True


def feed_url() -> str:
    return (os.environ.get('ANTICHEAT_FEED_URL') or DEFAULT_FEED_URL).strip()


def cache_path() -> str:
    """``ANTICHEAT_CACHE_PATH`` or ``<library>/anticheat/games.json``
    (the RW library volume in Docker, so the file survives a rebuild)."""
    explicit = (os.environ.get('ANTICHEAT_CACHE_PATH') or '').strip()
    if explicit:
        return explicit
    return os.path.join(library_dir(), 'anticheat', 'games.json')


# --- parsing -----------------------------------------------------------------

_NON_ALNUM = re.compile(r'[^a-z0-9]+')


def normalize_name(name: str | None) -> str:
    text = (name or '').lower()
    text = text.replace('&', ' and ')
    return _NON_ALNUM.sub(' ', text).strip()


def normalize_status(raw: Any) -> str:
    text = str(raw or '').strip().lower()
    return text if text in STATUSES else 'unknown'


def _steam_id_of(entry: dict[str, Any]) -> str | None:
    stores = entry.get('storeIds') or entry.get('store_ids') or {}
    candidates = (
        stores.get('steam') if isinstance(stores, dict) else None,
        entry.get('steamId'),
        entry.get('steam_id'),
        entry.get('steam_app_id'),
    )
    for value in candidates:
        if value is None or value == '':
            continue
        digits = re.sub(r'\D', '', str(value))
        if digits:
            return digits
    return None


def _source_url_of(entry: dict[str, Any]) -> str | None:
    slug = str(entry.get('slug') or '').strip()
    if slug:
        return f'{DEFAULT_PAGE_URL}/game/{slug}'
    ref = str(entry.get('reference') or '').strip()
    return ref or None


def _row_of(entry: dict[str, Any]) -> dict[str, Any] | None:
    name = str(entry.get('name') or '').strip()
    if not name:
        return None
    anticheats = entry.get('anticheats') or []
    if not isinstance(anticheats, list):
        anticheats = []
    updates = entry.get('updates') or []
    reports = len(updates) if isinstance(updates, list) else 0
    updated = None
    if isinstance(updates, list):
        dates = [str(u.get('date') or '') for u in updates if isinstance(u, dict)]
        dates = [d for d in dates if d]
        if dates:
            updated = max(dates)
    return {
        'name': name,
        'status': normalize_status(entry.get('status')),
        'anticheats': [str(a).strip() for a in anticheats if str(a).strip()],
        'reports': reports,
        'source_url': _source_url_of(entry),
        'updated': updated,
    }


def parse_feed(raw: str | bytes) -> dict[str, Any]:
    """Turn the feed body into ``{'by_steam': {...}, 'by_name': {...}, 'count': n}``.

    Raises ``ValueError`` when the body is not a JSON list of game objects --
    the caller decides whether that means "keep the old cache".
    """
    data = json.loads(raw)
    if isinstance(data, dict) and isinstance(data.get('games'), list):
        data = data['games']
    if not isinstance(data, list):
        raise ValueError('anti-cheat feed is not a list')
    by_steam: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    count = 0
    for entry in data:
        if not isinstance(entry, dict):
            continue
        row = _row_of(entry)
        if row is None:
            continue
        count += 1
        steam_id = _steam_id_of(entry)
        if steam_id:
            by_steam.setdefault(steam_id, row)
        key = normalize_name(row['name'])
        if key:
            by_name.setdefault(key, row)
    if count == 0:
        raise ValueError('anti-cheat feed has no game rows')
    return {'by_steam': by_steam, 'by_name': by_name, 'count': count}


# --- cache -------------------------------------------------------------------

def _read_cache(path: str) -> dict[str, Any] | None:
    try:
        with open(path, 'rb') as fh:
            index = parse_feed(fh.read())
    except (OSError, ValueError) as exc:
        logger.warning('[ANTICHEAT] cache unreadable at %s: %s', path, exc)
        return None
    index['fetched_at'] = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
    return index


def load_index(*, force: bool = False) -> dict[str, Any] | None:
    """The parsed cache, re-read when the file changed (checked at most once a
    minute so a browse page of 200 cards costs one ``stat``)."""
    global _INDEX, _INDEX_MTIME, _INDEX_CHECKED_AT
    if not is_enabled():
        return None
    now = time.monotonic()
    with _LOCK:
        if not force and _INDEX is not None and now - _INDEX_CHECKED_AT < _RECHECK_SECONDS:
            return _INDEX
        _INDEX_CHECKED_AT = now
        path = cache_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            _INDEX, _INDEX_MTIME = None, None
            return None
        if not force and _INDEX is not None and mtime == _INDEX_MTIME:
            return _INDEX
        _INDEX = _read_cache(path)
        _INDEX_MTIME = mtime if _INDEX is not None else None
        return _INDEX


def cache_is_stale() -> bool:
    try:
        age = time.time() - os.path.getmtime(cache_path())
    except OSError:
        return True
    return age >= CACHE_TTL_SECONDS


def refresh_if_stale(*, force: bool = False) -> bool:
    """Fetch the feed when the cache is missing or a day old. True when a new
    file was written; False on skip or any failure (the old file stays)."""
    if not fetch_allowed():
        return False
    if not force and not cache_is_stale():
        return False
    url = feed_url()
    try:
        resp = safe_request('GET', url, validator=validate_user_outbound_http_url, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.warning('[ANTICHEAT] feed returned HTTP %s', resp.status_code)
            return False
        body = resp.content
        parsed = parse_feed(body)
    except Exception as exc:  # noqa: BLE001 -- offline / blocked / schema drift is a miss, not a crash
        logger.warning('[ANTICHEAT] feed refresh failed: %s', exc)
        return False
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f'{path}.tmp'
        with open(tmp, 'wb') as fh:
            fh.write(body)
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning('[ANTICHEAT] could not write cache at %s: %s', path, exc)
        return False
    logger.info('[ANTICHEAT] feed refreshed: %s titles', parsed['count'])
    load_index(force=True)
    return True


# --- lookups -----------------------------------------------------------------

def lookup(*, steam_app_id: int | str | None = None, name: str | None = None) -> dict[str, Any] | None:
    """The community row for a title, by Steam app id first, then exact
    normalised name. ``None`` when the source is off, uncached or silent."""
    index = load_index()
    if not index:
        return None
    if steam_app_id not in (None, ''):
        row = index['by_steam'].get(re.sub(r'\D', '', str(steam_app_id)))
        if row:
            return dict(row)
    key = normalize_name(name)
    if key:
        row = index['by_name'].get(key)
        if row:
            return dict(row)
    return None


def game_anticheat(game) -> dict[str, Any] | None:
    """``anticheat`` field for card / details payloads. Steam id when the game
    has one; the name fallback only on PC shelves."""
    if game is None or not is_enabled():
        return None
    steam_app_id = getattr(game, 'steam_app_id', None)
    library = getattr(game, 'library', None)
    platform = getattr(getattr(library, 'platform', None), 'name', None)
    name = getattr(game, 'name', None) if (platform is None or str(platform).upper() in PC_PLATFORMS) else None
    if steam_app_id is None and not name:
        return None
    try:
        return lookup(steam_app_id=steam_app_id, name=name)
    except Exception as exc:  # noqa: BLE001
        logger.debug('[ANTICHEAT] lookup failed: %s', exc)
        return None


def status_summary() -> dict[str, Any]:
    """For the plugin registry and the Integrations inventory."""
    index = load_index() if is_enabled() else None
    return {
        'enabled': is_enabled(),
        'configured': bool(index),
        'count': int(index['count']) if index else 0,
        'cached_at': index.get('fetched_at') if index else None,
        'feed_url': feed_url(),
    }
