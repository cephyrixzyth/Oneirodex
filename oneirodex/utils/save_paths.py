"""Where a PC game keeps its saves (INSP-1, PC half; v11 cycle H4e).

Wraps the community save-location manifest (the Ludusavi-class YAML: one
entry per game, ``files`` keyed by a templated path such as
``<winDocuments>/My Games/<Title>/Saves``, each with ``tags`` and ``when``
constraints) rather than rebuilding it. One keyless fetch a day into the
library volume; the poller then writes a **compact JSON index** beside it so
a details request never parses fifteen megabytes of YAML.

What this gives the product:

* ``save_paths_for(game)`` -> ``[{'path', 'os', 'store', 'tags'}]`` for the
  matched entry -- Steam app id first, exact normalised name second -- or
  ``None`` when the manifest is silent. Paths keep their placeholders; the
  desktop companion expands them for *its* machine when asked to open one.
* Nothing is synced, copied or watched. The multi-device save story is
  sized in H-I; this is the row that says where the folder is.
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

SOURCE_ID = 'save_paths'
DEFAULT_MANIFEST_URL = 'https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml'
CACHE_TTL_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 60
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
SAVE_TAGS = frozenset({'save'})
PC_PLATFORMS = frozenset({'PCWIN', 'PCDOS', 'MAC', 'LINUX', 'OTHER'})

_LOCK = threading.Lock()
_INDEX: dict[str, Any] | None = None
_INDEX_MTIME: float | None = None
_INDEX_CHECKED_AT = 0.0
_RECHECK_SECONDS = 60.0
_NON_ALNUM = re.compile(r'[^a-z0-9]+')


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
    return _truthy(os.environ.get('ENABLE_SAVE_PATHS'), True)


def fetch_allowed() -> bool:
    if not is_enabled():
        return False
    if _testing() and not _truthy(os.environ.get('SAVE_PATHS_IN_TESTS'), False):
        return False
    return True


def manifest_url() -> str:
    return (os.environ.get('SAVE_PATHS_MANIFEST_URL') or DEFAULT_MANIFEST_URL).strip()


def cache_dir() -> str:
    explicit = (os.environ.get('SAVE_PATHS_CACHE_DIR') or '').strip()
    if explicit:
        return explicit
    return os.path.join(library_dir(), 'save_paths')


def manifest_path() -> str:
    return os.path.join(cache_dir(), 'manifest.yaml')


def index_path() -> str:
    return os.path.join(cache_dir(), 'manifest.index.json')


def normalize_name(name: str | None) -> str:
    text = (name or '').lower().replace('&', ' and ')
    return _NON_ALNUM.sub(' ', text).strip()


# --- building the compact index ---------------------------------------------

def _when_rows(when: Any) -> list[dict[str, str | None]]:
    rows = when if isinstance(when, list) else ([when] if isinstance(when, dict) else [])
    out: list[dict[str, str | None]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append({'os': str(row.get('os') or '').strip().lower() or None, 'store': str(row.get('store') or '').strip().lower() or None})
    return out or [{'os': None, 'store': None}]


def build_index(manifest: dict[str, Any]) -> dict[str, Any]:
    """Keep only what a details row needs: save-tagged file templates with
    their os/store constraint, the Steam id, and the name.

    Raises ``ValueError`` on a body that is not a mapping of games.
    """
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError('save-path manifest is not a mapping of games')
    by_name: dict[str, dict[str, Any]] = {}
    by_steam: dict[str, str] = {}
    count = 0
    for title, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        files = entry.get('files') if isinstance(entry.get('files'), dict) else {}
        paths: list[dict[str, Any]] = []
        for template, meta in files.items():
            tags = {str(t).lower() for t in ((meta or {}).get('tags') or [])} if isinstance(meta, dict) else set()
            if not tags & SAVE_TAGS:
                continue
            for when in _when_rows((meta or {}).get('when') if isinstance(meta, dict) else None):
                paths.append({'path': str(template), 'os': when['os'], 'store': when['store']})
        if not paths:
            continue
        count += 1
        key = normalize_name(str(title))
        steam = entry.get('steam') if isinstance(entry.get('steam'), dict) else {}
        steam_id = str(steam.get('id') or '').strip()
        row = {'name': str(title), 'paths': paths[:24], 'steam_id': steam_id or None}
        if key:
            by_name.setdefault(key, row)
        if steam_id:
            by_steam.setdefault(steam_id, key)
    if count == 0:
        raise ValueError('save-path manifest has no save-tagged entries')
    return {'v': 1, 'count': count, 'by_name': by_name, 'by_steam': by_steam}


def parse_manifest_yaml(raw: bytes) -> dict[str, Any]:
    import yaml

    loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
    return yaml.load(raw, Loader=loader)  # noqa: S506 -- SafeLoader variant


# --- cache -------------------------------------------------------------------

def load_index(*, force: bool = False) -> dict[str, Any] | None:
    global _INDEX, _INDEX_MTIME, _INDEX_CHECKED_AT
    if not is_enabled():
        return None
    now = time.monotonic()
    with _LOCK:
        if not force and _INDEX is not None and now - _INDEX_CHECKED_AT < _RECHECK_SECONDS:
            return _INDEX
        _INDEX_CHECKED_AT = now
        path = index_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            _INDEX, _INDEX_MTIME = None, None
            return None
        if not force and _INDEX is not None and mtime == _INDEX_MTIME:
            return _INDEX
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or 'by_name' not in data:
                raise ValueError('index shape')
            data['fetched_at'] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            _INDEX, _INDEX_MTIME = data, mtime
        except (OSError, ValueError) as exc:
            logger.warning('[SAVE PATHS] index unreadable at %s: %s', path, exc)
            _INDEX, _INDEX_MTIME = None, None
        return _INDEX


def cache_is_stale() -> bool:
    try:
        return time.time() - os.path.getmtime(index_path()) >= CACHE_TTL_SECONDS
    except OSError:
        return True


def refresh_if_stale(*, force: bool = False) -> bool:
    """Fetch the manifest and rebuild the compact index when the index is
    missing or a day old. False on skip or any failure (the old index stays)."""
    if not fetch_allowed():
        return False
    if not force and not cache_is_stale():
        return False
    try:
        resp = safe_request('GET', manifest_url(), validator=validate_user_outbound_http_url, timeout=TIMEOUT_SECONDS)
        if resp.status_code != 200:
            logger.warning('[SAVE PATHS] manifest returned HTTP %s', resp.status_code)
            return False
        body = resp.content
        if not body or len(body) > MAX_MANIFEST_BYTES:
            logger.warning('[SAVE PATHS] manifest body empty or over %s bytes', MAX_MANIFEST_BYTES)
            return False
        index = build_index(parse_manifest_yaml(body))
    except Exception as exc:  # noqa: BLE001 -- offline / schema drift is a miss, not a crash
        logger.warning('[SAVE PATHS] manifest refresh failed: %s', type(exc).__name__)
        return False
    try:
        os.makedirs(cache_dir(), exist_ok=True)
        tmp = index_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(index, fh, separators=(',', ':'))
        os.replace(tmp, index_path())
        with open(manifest_path() + '.tmp', 'wb') as fh:
            fh.write(body)
        os.replace(manifest_path() + '.tmp', manifest_path())
    except OSError as exc:
        logger.warning('[SAVE PATHS] could not write cache: %s', exc)
        return False
    logger.info('[SAVE PATHS] manifest refreshed: %s titles with save paths', index['count'])
    load_index(force=True)
    return True


# --- lookups -----------------------------------------------------------------

def lookup(*, steam_app_id: int | str | None = None, name: str | None = None) -> dict[str, Any] | None:
    index = load_index()
    if not index:
        return None
    key = None
    if steam_app_id not in (None, ''):
        key = index['by_steam'].get(re.sub(r'\D', '', str(steam_app_id)))
    if not key:
        key = normalize_name(name)
    row = index['by_name'].get(key) if key else None
    return dict(row) if row else None


def save_paths_for(game) -> list[dict[str, Any]] | None:
    """``save_paths`` for the details payload: PC shelves only; ``None`` when
    the manifest is off, uncached or silent."""
    if game is None or not is_enabled():
        return None
    library = getattr(game, 'library', None)
    platform = getattr(getattr(library, 'platform', None), 'name', None)
    if platform is not None and str(platform).upper() not in PC_PLATFORMS:
        return None
    try:
        row = lookup(steam_app_id=getattr(game, 'steam_app_id', None), name=getattr(game, 'name', None))
    except Exception as exc:  # noqa: BLE001
        logger.debug('[SAVE PATHS] lookup failed: %s', exc)
        return None
    return row['paths'] if row else None


def status_summary() -> dict[str, Any]:
    index = load_index() if is_enabled() else None
    return {
        'enabled': is_enabled(),
        'configured': bool(index),
        'count': int(index['count']) if index else 0,
        'cached_at': index.get('fetched_at') if index else None,
        'manifest_url': manifest_url(),
    }
