"""Meta Quest store product pages as a metadata source.

Many Quest games are on no other storefront and missing from IGDB, Steam, GOG
and Epic ("Golden Gloves", the game in a folder named "Golden Gloves Boxing VR").
The Meta store has no keyless search API, but every product page
(``https://www.meta.com/experiences/<slug>/<app id>/``) is public and carries a
schema.org ``SoftwareApplication`` block with the title, description, images,
developer and genres. This module reads that block for a known app id.

Where the app id comes from:

* a store link pasted into manual identify (Meta Quest search accepts a URL or a
  bare id), or
* the folder itself: a tag in the folder name (``Golden Gloves Boxing VR [meta
  5682829115084320]``) or an Internet shortcut / text file inside the folder that
  links to the store page (``.url``, ``.webloc``, ``.txt``) — see
  :func:`meta_app_id_from_folder`.

Metadata only: this never downloads anything but the public page and never
touches entitlements or installs.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

STORE_PAGE_URL = 'https://www.meta.com/experiences/{app_id}/'

# Store app ids are 15-17 digit numbers ("5682829115084320").
_APP_ID = r'(\d{14,19})'
_STORE_URL_RE = re.compile(
    r'(?:https?://)?(?:www\.)?(?:meta|oculus)\.com/(?:[a-z]{2}-[a-z]{2}/)?experiences/'
    r'(?:(?:quest|rift|go|app|pcvr|[a-z0-9-]+)/)*' + _APP_ID,
    re.IGNORECASE,
)
_BARE_ID_RE = re.compile(r'^\s*' + _APP_ID + r'\s*$')
# "[meta 5682829115084320]", "(oculus 5682…)", "(quest:5682…)", "[metaid 5682…]".
_LABEL_TAG_RE = re.compile(
    r'\s*[\(\[]\s*(?:meta|oculus|quest)(?:[\s_-]*(?:app|store))?(?:[\s_-]*id)?\s*[:#]?\s*'
    + _APP_ID + r'\s*[\)\]]',
    re.IGNORECASE,
)
_LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_TITLE_TAIL_RE = re.compile(r'\s+on Meta Quest\b.*$', re.IGNORECASE)

# Files a person may drop next to a game to say where it came from.
_HINT_FILE_SUFFIXES = ('.url', '.webloc', '.txt', '.desktop')
_HINT_FILE_MAX_BYTES = 64 * 1024
_HINT_DIR_MAX_ENTRIES = 200

_USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0 Safari/537.36 Oneirodex/1.0'
)


def parse_meta_app_id(text: str | None) -> str | None:
    """App id from a Meta/Oculus store link, or from a bare id."""
    value = (text or '').strip()
    if not value:
        return None
    match = _STORE_URL_RE.search(value)
    if match:
        return match.group(1)
    match = _BARE_ID_RE.match(value)
    if match:
        return match.group(1)
    return None


def meta_app_id_from_label(label: str | None) -> str | None:
    """App id from a ``[meta <id>]`` style tag in a folder name."""
    match = _LABEL_TAG_RE.search(label or '')
    return match.group(1) if match else None


def strip_meta_label_tag(label: str | None) -> str:
    """The folder name without its ``[meta <id>]`` tag."""
    return _LABEL_TAG_RE.sub('', label or '').strip()


def meta_app_id_from_folder(full_disk_path: str | None) -> str | None:
    """App id from the folder name tag, or a store link file inside the folder.

    Only the folder's own top level is read, only small link/text files, and
    the first store link found wins.
    """
    if not full_disk_path:
        return None
    base = os.path.basename(str(full_disk_path).replace('\\', '/').rstrip('/'))
    from_label = meta_app_id_from_label(base)
    if from_label:
        return from_label
    try:
        if not os.path.isdir(full_disk_path):
            return None
        with os.scandir(full_disk_path) as entries:
            names = []
            for index, entry in enumerate(entries):
                if index >= _HINT_DIR_MAX_ENTRIES:
                    break
                if entry.name.lower().endswith(_HINT_FILE_SUFFIXES) and entry.is_file(follow_symlinks=False):
                    names.append(entry.name)
    except OSError:
        return None
    for name in sorted(names):
        path = os.path.join(full_disk_path, name)
        try:
            if os.path.getsize(path) > _HINT_FILE_MAX_BYTES:
                continue
            with open(path, 'r', encoding='utf-8', errors='ignore') as handle:
                text = handle.read(_HINT_FILE_MAX_BYTES)
        except OSError:
            continue
        match = _STORE_URL_RE.search(text)
        if match:
            return match.group(1)
    return None


def _graph_nodes(blob) -> list[dict]:
    if isinstance(blob, list):
        nodes = []
        for item in blob:
            nodes.extend(_graph_nodes(item))
        return nodes
    if not isinstance(blob, dict):
        return []
    if isinstance(blob.get('@graph'), list):
        return [node for node in blob['@graph'] if isinstance(node, dict)]
    return [blob]


def _types(node: dict) -> set[str]:
    value = node.get('@type')
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _ref_name(ref, nodes_by_id: dict) -> str | None:
    if isinstance(ref, list):
        ref = ref[0] if ref else None
    if isinstance(ref, dict):
        if ref.get('name'):
            return str(ref['name']).strip() or None
        node = nodes_by_id.get(ref.get('@id'))
        if node and node.get('name'):
            return str(node['name']).strip() or None
    if isinstance(ref, str):
        return ref.strip() or None
    return None


def _image_url(ref, nodes_by_id: dict) -> str | None:
    if isinstance(ref, list):
        ref = ref[0] if ref else None
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        url = ref.get('url') or ref.get('contentUrl') or ref.get('@id')
        node = nodes_by_id.get(ref.get('@id'))
        if node:
            url = node.get('contentUrl') or node.get('url') or url
        return str(url) if url else None
    return None


def parse_meta_store_page(page_html: str, *, app_id: str | None = None) -> dict | None:
    """Metadata dict from a store product page's schema.org block, else None."""
    if not page_html:
        return None
    nodes: list[dict] = []
    for raw in _LD_JSON_RE.findall(page_html):
        try:
            nodes.extend(_graph_nodes(json.loads(html.unescape(raw.strip()))))
        except (ValueError, TypeError):
            continue
    nodes_by_id = {node.get('@id'): node for node in nodes if node.get('@id')}
    app = None
    for node in nodes:
        if 'SoftwareApplication' in _types(node) or 'VideoGame' in _types(node):
            if app_id and str(node.get('sku') or '') not in ('', str(app_id)):
                continue
            app = node
            break
    if app is None:
        return None
    name = _TITLE_TAIL_RE.sub('', str(app.get('name') or '')).strip()
    if not name:
        return None
    sku = str(app.get('sku') or app_id or '').strip() or None
    url = str(app.get('url') or '').strip() or (STORE_PAGE_URL.format(app_id=sku) if sku else None)
    genres = [str(g).strip() for g in (app.get('applicationSubCategory') or []) if str(g).strip()]
    category = str(app.get('applicationCategory') or '').strip() or None
    devices = [str(d).strip() for d in (app.get('availableOnDevice') or []) if str(d).strip()]
    rating = app.get('aggregateRating') if isinstance(app.get('aggregateRating'), dict) else {}
    out = {
        'source': 'meta_quest',
        'meta_quest_id': sku,
        'id': sku,
        'name': name,
        'summary': str(app.get('description') or '').strip() or None,
        'cover_url': _image_url(app.get('image'), nodes_by_id),
        'url': url,
        'developer': _ref_name(app.get('creator') or app.get('author'), nodes_by_id),
        'publisher': _ref_name(app.get('publisher'), nodes_by_id),
        'genres': genres,
        'application_category': category,
        'platforms': devices,
        'is_vr': True,
        'ownership_only': True,
    }
    try:
        if rating.get('ratingValue') is not None:
            best = float(rating.get('bestRating') or 5) or 5.0
            out['rating'] = round(float(rating['ratingValue']) / best * 100, 1)
            out['rating_count'] = int(rating.get('ratingCount') or 0)
    except (TypeError, ValueError):
        pass
    if app.get('datePublished'):
        out['release_date'] = str(app['datePublished'])
    return out


def fetch_meta_store_app(app_id: str | int | None) -> dict | None:
    """Fetch and parse one store product page. None on any miss or error."""
    key = parse_meta_app_id(str(app_id or ''))
    if not key:
        return None
    from oneirodex.utils.http_retry import request_with_backoff

    try:
        resp = request_with_backoff(
            STORE_PAGE_URL.format(app_id=key),
            host_key='meta_store',
            timeout=15,
            max_retries=2,
            headers={'User-Agent': _USER_AGENT, 'Accept-Language': 'en-US,en;q=0.8'},
        )
    except Exception as exc:  # noqa: BLE001 — a metadata miss must not break a scan
        logger.warning('Meta store page fetch failed for %s: %s', key, type(exc).__name__)
        return None
    if resp is None:
        return None
    try:
        return parse_meta_store_page(resp.text, app_id=key)
    except Exception as exc:  # noqa: BLE001
        logger.warning('Meta store page parse failed for %s: %s', key, type(exc).__name__)
        return None
