"""Title search on the Meta Quest store, for games no other catalogue lists.

Quest-only games ("Golden Gloves", in a folder named "Golden Gloves Boxing VR")
are missing from IGDB, Steam, GOG and Epic, so the scan has to ask Meta itself.
Two backends, tried in order:

1. **Meta's own store search.** meta.com's search page asks its GraphQL endpoint
   (``/api/graphql/``, query ``MDCUnifiedSearchResultsRootQuery``) for
   ``OCULUS_APP`` results. It needs no account: the page hands every visitor a
   short-lived ``LSD`` token, which we read from the public store page. Meta does
   not document this endpoint, so it can change without notice. When it fails
   the scan carries on with the fallback. ``META_STORE_SEARCH_DOC_ID`` overrides
   the query id if Meta rotates it, and ``META_STORE_SITE_SEARCH=0`` turns this
   backend off.
2. **Brave Search API** (``BRAVE_SEARCH_API_KEY``): a ``site:meta.com/experiences``
   web search. Official and stable; each hit's store page is then read for the
   real title (see :mod:`oneirodex.utils.meta_store`).

A hit is ``{id, meta_quest_id, name, url, cover_url?, rating?, rating_count?}``,
plus ``details`` (the parsed store page) when the backend already read it.
Search only: deciding whether a hit *is* the folder's game is
``software_identify.match_meta_store_hits``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

from oneirodex.utils.meta_store import (
    STORE_PAGE_URL,
    _USER_AGENT,
    fetch_meta_store_app,
    parse_meta_app_id,
)

logger = logging.getLogger(__name__)

SEARCH_HOST = 'https://www.meta.com'
TOKEN_PAGE_URL = f'{SEARCH_HOST}/experiences/'
GRAPHQL_URL = f'{SEARCH_HOST}/api/graphql/'
DEFAULT_SEARCH_DOC_ID = '38719684590956126'
SEARCH_FRIENDLY_NAME = 'MDCUnifiedSearchResultsRootQuery'
BRAVE_SEARCH_URL = 'https://api.search.brave.com/res/v1/web/search'

_LSD_RE = re.compile(r'"LSD",\[\],\{"token":"([^"]+)"')
_LSD_TTL_SEC = 20 * 60
_RESPONSE_PREFIX = 'for (;;);'
_BRAVE_PAGES_TO_READ = 3

_token_lock = threading.Lock()
_token: dict = {'value': None, 'at': 0.0}


def _env_flag(name: str, default: bool = True) -> bool:
    raw = (os.getenv(name) or '').strip().lower()
    if not raw:
        return default
    return raw not in ('0', 'false', 'no', 'off')


def meta_site_search_enabled() -> bool:
    return _env_flag('META_STORE_SITE_SEARCH', True)


def brave_search_api_key() -> str | None:
    return (os.getenv('BRAVE_SEARCH_API_KEY') or '').strip() or None


def _browser_headers(**extra) -> dict:
    headers = {
        'User-Agent': _USER_AGENT,
        'Accept-Language': 'en-US,en;q=0.8',
    }
    headers.update(extra)
    return headers


def _site_token(*, refresh: bool = False) -> str | None:
    """The anonymous LSD token the public store page hands every visitor."""
    with _token_lock:
        fresh = _token['value'] and (time.monotonic() - _token['at']) < _LSD_TTL_SEC
        if fresh and not refresh:
            return _token['value']
    from oneirodex.utils.http_retry import request_with_backoff

    resp = request_with_backoff(
        TOKEN_PAGE_URL,
        host_key='meta_store',
        timeout=15,
        max_retries=2,
        headers=_browser_headers(Accept='text/html'),
    )
    if resp is None:
        return None
    match = _LSD_RE.search(resp.text or '')
    if not match:
        logger.warning('Meta store search: no LSD token on the store page')
        return None
    with _token_lock:
        _token['value'] = match.group(1)
        _token['at'] = time.monotonic()
    return match.group(1)


def parse_site_search_response(text: str | None) -> list[dict] | None:
    """App hits from a ``MDCUnifiedSearchResultsRootQuery`` response, None if unreadable."""
    body = (text or '').strip()
    if body.startswith(_RESPONSE_PREFIX):
        body = body[len(_RESPONSE_PREFIX):]
    # The endpoint can stream several JSON documents; the first holds the results.
    try:
        payload, _end = json.JSONDecoder().raw_decode(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        nodes = payload['data']['response']['search_results']['nodes']
    except (KeyError, TypeError):
        return None
    if not isinstance(nodes, list):
        return None
    hits: list[dict] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get('type') or '').upper() != 'OCULUS_APP':
            continue
        app_id = parse_meta_app_id(str(node.get('id') or node.get('search_result_id') or ''))
        name = str(node.get('title') or '').strip()
        if not app_id or not name:
            continue
        image = node.get('image_transcoded') or node.get('image_fallback') or {}
        hit = {
            'source': 'meta_quest',
            'id': app_id,
            'meta_quest_id': app_id,
            'name': name,
            'url': str(node.get('uri') or '').strip() or STORE_PAGE_URL.format(app_id=app_id),
            'cover_url': image.get('uri') if isinstance(image, dict) else None,
        }
        try:
            if node.get('quality_rating_aggregate') is not None:
                hit['rating'] = round(float(node['quality_rating_aggregate']) / 5 * 100, 1)
                hit['rating_count'] = int(node.get('quality_rating_count') or 0)
        except (TypeError, ValueError):
            pass
        hits.append(hit)
    return hits


def _post_site_search(query: str, limit: int, token: str) -> list[dict] | None:
    from oneirodex.utils.http_retry import throttle
    from oneirodex.utils.http_safe import BlockedOutboundUrl, safe_request
    from oneirodex.utils.security import validate_user_outbound_http_url

    doc_id = (os.getenv('META_STORE_SEARCH_DOC_ID') or '').strip() or DEFAULT_SEARCH_DOC_ID
    form = {
        'av': '0',
        '__user': '0',
        '__a': '1',
        'lsd': token,
        'fb_api_caller_class': 'RelayModern',
        'fb_api_req_friendly_name': SEARCH_FRIENDLY_NAME,
        'server_timestamps': 'true',
        'variables': json.dumps(
            {'query': query, 'maxEntries': int(limit), 'types': ['OCULUS_APP']},
            separators=(',', ':'),
        ),
        'doc_id': doc_id,
    }
    throttle('meta_store')
    try:
        resp = safe_request(
            'POST',
            GRAPHQL_URL,
            validator=validate_user_outbound_http_url,
            data=form,
            timeout=15,
            headers=_browser_headers(**{
                'Accept': '*/*',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': SEARCH_HOST,
                'Referer': f'{SEARCH_HOST}/search/?type=oculus_app',
                'X-FB-LSD': token,
                'X-FB-Friendly-Name': SEARCH_FRIENDLY_NAME,
            }),
        )
    except BlockedOutboundUrl:
        return None
    except Exception as exc:  # noqa: BLE001 — a search miss must not break a scan
        logger.warning('Meta store search request failed: %s', type(exc).__name__)
        return None
    if resp.status_code != 200:
        logger.warning('Meta store search answered HTTP %s', resp.status_code)
        return None
    return parse_site_search_response(resp.text)


def search_meta_site(query: str, limit: int = 10) -> list[dict] | None:
    """Meta's own store search. None when it could not be asked or read."""
    if not meta_site_search_enabled():
        return None
    token = _site_token()
    if not token:
        return None
    hits = _post_site_search(query, limit, token)
    if hits is None:
        # A stale token is the usual cause: fetch a fresh one and try once more.
        token = _site_token(refresh=True)
        if token:
            hits = _post_site_search(query, limit, token)
    if hits is None:
        logger.warning('Meta store search unavailable; falling back if a web search key is set')
    return hits


def parse_brave_results(payload: dict | None) -> list[str]:
    """Distinct Meta store app ids from a Brave web search response, in rank order."""
    ids: list[str] = []
    try:
        results = (payload or {}).get('web', {}).get('results') or []
    except AttributeError:
        return ids
    for row in results:
        if not isinstance(row, dict):
            continue
        app_id = parse_meta_app_id(str(row.get('url') or ''))
        if app_id and app_id not in ids:
            ids.append(app_id)
    return ids


def search_meta_via_brave(query: str, limit: int = 10) -> list[dict] | None:
    """``site:meta.com/experiences`` web search, then each top page's real title."""
    api_key = brave_search_api_key()
    if not api_key:
        return None
    from oneirodex.utils.http_retry import request_with_backoff

    resp = request_with_backoff(
        BRAVE_SEARCH_URL,
        host_key='brave_search',
        params={'q': f'site:meta.com/experiences {query}', 'count': min(int(limit), 20)},
        timeout=10,
        max_retries=2,
        headers={'Accept': 'application/json', 'X-Subscription-Token': api_key},
    )
    if resp is None:
        return None
    try:
        payload = resp.json()
    except ValueError:
        return None
    hits: list[dict] = []
    for app_id in parse_brave_results(payload)[:_BRAVE_PAGES_TO_READ]:
        details = fetch_meta_store_app(app_id)
        if not details:
            continue
        hits.append({
            'source': 'meta_quest',
            'id': app_id,
            'meta_quest_id': app_id,
            'name': details['name'],
            'url': details.get('url') or STORE_PAGE_URL.format(app_id=app_id),
            'cover_url': details.get('cover_url'),
            'details': details,
        })
    return hits


def _live_search_allowed() -> bool:
    """No live store search under pytest (tests patch the backends)."""
    if os.getenv('PYTEST_CURRENT_TEST'):
        return False
    from oneirodex.utils.software_identify import _catalog_http_allowed

    return _catalog_http_allowed()


def search_meta_store(query: str | None, limit: int = 10) -> list[dict]:
    """Meta Quest store apps for a title: Meta's search first, then Brave."""
    text = (query or '').strip()
    if not text:
        return []
    if not _live_search_allowed():
        return []
    hits = search_meta_site(text, limit)
    if hits:
        return hits
    fallback = search_meta_via_brave(text, limit)
    if fallback is not None:
        return fallback
    return hits or []


def search_backends_configured() -> bool:
    """Whether any search backend can run (for logs and settings hints)."""
    return meta_site_search_enabled() or bool(brave_search_api_key())
