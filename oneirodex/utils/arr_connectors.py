"""Optional *arr connectors: native Torznab/Newznab + Prowlarr/Jackett + download clients."""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from flask import current_app
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import GlobalSettings
from oneirodex.utils.challenge_solver import fetch_with_challenge_retry
from oneirodex.utils.indexer_registry import (
    indexer_status_summary,
    ready_native_indexers,
)
from oneirodex.utils.http_safe import safe_request
from oneirodex.utils.security import validate_connector_http_url, validate_outbound_http_url

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20

_CONNECTOR_URL_KEYS = (
    'prowlarr_url',
    'jackett_url',
    'qbittorrent_url',
    'transmission_url',
    'deluge_url',
    'sabnzbd_url',
    'nzbget_url',
)

_HUB_KEYS = (
    'prowlarr_url', 'prowlarr_api_key',
    'jackett_url', 'jackett_api_key',
    'qbittorrent_url', 'qbittorrent_username', 'qbittorrent_password',
    'transmission_url', 'transmission_username', 'transmission_password',
    'deluge_url', 'deluge_password',
    'sabnzbd_url', 'sabnzbd_api_key',
    'nzbget_url', 'nzbget_username', 'nzbget_password',
)


# Query-string credentials as *arr indexers and Jackett take them (``?apikey=``).
_SECRET_PARAM_RE = re.compile(r'(?i)\b(apikey|api_key|token|password|passwd|secret)=[^&\s\'")]+')


def _url_for_log(url: str | None) -> str:
    """``scheme://host:port/path`` -- no userinfo, no query, no fragment."""
    try:
        parsed = urlparse(str(url or ''))
        host = parsed.hostname or ''
        if ':' in host:
            host = f'[{host}]'
        port = f':{parsed.port}' if parsed.port else ''
        return f'{parsed.scheme}://{host}{port}{parsed.path}' if host else ''
    except ValueError:
        return ''


def _exc_for_log(exc: BaseException) -> str:
    """What is safe to write to the log about a failed connector call.

    ``requests`` exceptions carry the full request URL in their text, and
    Jackett / Torznab take the API key as ``?apikey=...``, so ``%s`` of the
    exception wrote the key to the log. Name the exception type and the URL
    with its query stripped instead; for anything else, scrub credential
    parameters out of the message.
    """
    if isinstance(exc, requests.RequestException):
        where = _url_for_log(getattr(getattr(exc, 'request', None), 'url', None))
        return f'{type(exc).__name__} ({where})' if where else type(exc).__name__
    return _SECRET_PARAM_RE.sub(lambda m: f'{m.group(1)}=***', str(exc))


@dataclass
class ArrHit:
    title: str
    indexer: str | None = None
    size: int | None = None
    seeders: int | None = None
    download_url: str | None = None
    info_url: str | None = None
    protocol: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _settings() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def get_arr_config() -> dict[str, Any]:
    row = _settings()
    cfg = getattr(row, 'arr_settings', None) if row else None
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        'prowlarr_url': (cfg.get('prowlarr_url') or current_app.config.get('PROWLARR_URL') or '').rstrip('/'),
        'prowlarr_api_key': cfg.get('prowlarr_api_key') or current_app.config.get('PROWLARR_API_KEY') or '',
        'jackett_url': (cfg.get('jackett_url') or current_app.config.get('JACKETT_URL') or '').rstrip('/'),
        'jackett_api_key': cfg.get('jackett_api_key') or current_app.config.get('JACKETT_API_KEY') or '',
        'qbittorrent_url': (cfg.get('qbittorrent_url') or current_app.config.get('QBITTORRENT_URL') or '').rstrip('/'),
        'qbittorrent_username': cfg.get('qbittorrent_username') or current_app.config.get('QBITTORRENT_USERNAME') or 'admin',
        'qbittorrent_password': cfg.get('qbittorrent_password') or current_app.config.get('QBITTORRENT_PASSWORD') or '',
        'transmission_url': (cfg.get('transmission_url') or current_app.config.get('TRANSMISSION_URL') or '').rstrip('/'),
        'transmission_username': cfg.get('transmission_username') or current_app.config.get('TRANSMISSION_USERNAME') or '',
        'transmission_password': cfg.get('transmission_password') or current_app.config.get('TRANSMISSION_PASSWORD') or '',
        'deluge_url': (cfg.get('deluge_url') or current_app.config.get('DELUGE_URL') or '').rstrip('/'),
        'deluge_password': cfg.get('deluge_password') or current_app.config.get('DELUGE_PASSWORD') or '',
        'sabnzbd_url': (cfg.get('sabnzbd_url') or current_app.config.get('SABNZBD_URL') or '').rstrip('/'),
        'sabnzbd_api_key': cfg.get('sabnzbd_api_key') or current_app.config.get('SABNZBD_API_KEY') or '',
        'nzbget_url': (cfg.get('nzbget_url') or current_app.config.get('NZBGET_URL') or '').rstrip('/'),
        'nzbget_username': cfg.get('nzbget_username') or current_app.config.get('NZBGET_USERNAME') or '',
        'nzbget_password': cfg.get('nzbget_password') or current_app.config.get('NZBGET_PASSWORD') or '',
        'indexers': list(cfg.get('indexers') or []) if isinstance(cfg.get('indexers'), list) else [],
    }


def save_arr_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Update hub connector fields without wiping indexers / challenge / debrid keys."""
    row = _settings()
    if not row:
        row = GlobalSettings()
        db.session.add(row)
    current = dict(getattr(row, 'arr_settings', None) or {})
    # Seed hub defaults from env when keys are absent so validation sees effective values.
    hub_view = get_arr_config()
    for key in _HUB_KEYS:
        if key not in current and hub_view.get(key):
            current[key] = hub_view[key]
    for key in _HUB_KEYS:
        if key in payload and payload[key] is not None:
            current[key] = str(payload[key]).strip()
    for key in _CONNECTOR_URL_KEYS:
        value = (current.get(key) or '').strip()
        if not value:
            continue
        ok, result = validate_connector_http_url(value)
        if not ok:
            raise ValueError(f'{key}: {result} (set ALLOW_PRIVATE_LAN_URLS=true for RFC1918 *arr hosts)')
        current[key] = result.rstrip('/')
    row.arr_settings = current
    db.session.commit()
    return {
        **{k: current.get(k) or '' for k in _HUB_KEYS},
        'prowlarr_api_key': '***' if current.get('prowlarr_api_key') else '',
        'jackett_api_key': '***' if current.get('jackett_api_key') else '',
        'qbittorrent_password': '***' if current.get('qbittorrent_password') else '',
        'transmission_password': '***' if current.get('transmission_password') else '',
        'deluge_password': '***' if current.get('deluge_password') else '',
        'sabnzbd_api_key': '***' if current.get('sabnzbd_api_key') else '',
        'nzbget_password': '***' if current.get('nzbget_password') else '',
    }


def connector_status() -> list[dict[str, Any]]:
    cfg = get_arr_config()
    native = indexer_status_summary()
    return [
        native,
        {
            'id': 'prowlarr',
            'configured': bool(cfg['prowlarr_url'] and cfg['prowlarr_api_key']),
            'url': cfg['prowlarr_url'] or None,
        },
        {
            'id': 'jackett',
            'configured': bool(cfg['jackett_url'] and cfg['jackett_api_key']),
            'url': cfg['jackett_url'] or None,
        },
        {
            'id': 'qbittorrent',
            'configured': bool(cfg['qbittorrent_url']),
            'url': cfg['qbittorrent_url'] or None,
        },
        {
            'id': 'transmission',
            'configured': bool(cfg['transmission_url']),
            'url': cfg['transmission_url'] or None,
        },
        {
            'id': 'deluge',
            'configured': bool(cfg['deluge_url']),
            'url': cfg['deluge_url'] or None,
        },
        {
            'id': 'sabnzbd',
            'configured': bool(cfg['sabnzbd_url'] and cfg['sabnzbd_api_key']),
            'url': cfg['sabnzbd_url'] or None,
        },
        {
            'id': 'nzbget',
            'configured': bool(cfg['nzbget_url']),
            'url': cfg['nzbget_url'] or None,
        },
    ]


def search_indexers(query: str, *, limit: int = 25) -> list[ArrHit]:
    """Merge hits from native Torznab/Newznab + Prowlarr + Jackett (not exclusive)."""
    query = (query or '').strip()
    if not query:
        return []
    limit = max(1, int(limit))
    cfg = get_arr_config()
    hits: list[ArrHit] = []

    for indexer in ready_native_indexers():
        try:
            hits.extend(_search_native_indexer(indexer, query, limit=limit))
        except Exception as exc:
            logger.warning('Native indexer %s search failed: %s', indexer.get('name'), _exc_for_log(exc))

    if cfg['prowlarr_url'] and cfg['prowlarr_api_key']:
        try:
            hits.extend(_search_prowlarr(cfg, query, limit=limit))
        except Exception as exc:
            logger.warning('Prowlarr search failed: %s', _exc_for_log(exc))

    if cfg['jackett_url'] and cfg['jackett_api_key']:
        try:
            hits.extend(_search_jackett(cfg, query, limit=limit))
        except Exception as exc:
            logger.warning('Jackett search failed: %s', _exc_for_log(exc))

    return _dedupe_hits(hits, limit=limit)


def _dedupe_hits(hits: list[ArrHit], *, limit: int) -> list[ArrHit]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    out: list[ArrHit] = []
    for hit in hits:
        url_key = (hit.download_url or '').strip().lower()
        title_key = (hit.title or '').strip().lower()
        if url_key and url_key in seen_urls:
            continue
        if not url_key and title_key and title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        out.append(hit)
        if len(out) >= limit:
            break
    return out


def _torznab_api_url(base_url: str) -> str:
    """Ensure Torznab/Newznab base ends at an API root (append /api when needed)."""
    cleaned = (base_url or '').rstrip('/')
    lower = cleaned.lower()
    if lower.endswith('/api') or '/api?' in lower or lower.endswith('torznab') or '/results/torznab' in lower:
        return cleaned
    return cleaned + '/api'


def _never_lan_indexer_url(url: str) -> tuple[bool, str]:
    """Indexer hosts are public — never LAN, even with the homelab flag on."""
    return validate_outbound_http_url(url, allow_http=True, allow_private_lan=False)


def _search_native_indexer(indexer: dict[str, Any], query: str, *, limit: int) -> list[ArrHit]:
    base = (indexer.get('url') or '').strip()
    api_key = (indexer.get('api_key') or '').strip()
    if not base or not api_key:
        return []
    ok, cleaned = validate_outbound_http_url(base, allow_http=True, allow_private_lan=False)
    if not ok:
        raise ValueError(cleaned)
    api_url = _torznab_api_url(cleaned)
    params = {
        't': 'search',
        'q': query,
        'apikey': api_key,
        'limit': limit,
    }
    resp = fetch_with_challenge_retry(
        'get',
        api_url,
        params=params,
        timeout=DEFAULT_TIMEOUT,
        # Same never-LAN policy the URL was validated under above, now applied
        # to redirect hops as well.
        validator=_never_lan_indexer_url,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Indexer '{indexer.get('name')}' search failed ({resp.status_code})",
        )
    content_type = (resp.headers.get('Content-Type') or '').lower()
    body = resp.text or ''
    if 'json' in content_type or body.lstrip().startswith('{') or body.lstrip().startswith('['):
        return _parse_native_json(body, indexer, limit=limit)
    return _parse_native_xml(body, indexer, limit=limit)


def _parse_native_json(body: str, indexer: dict[str, Any], *, limit: int) -> list[ArrHit]:
    try:
        payload = json_loads_safe(body)
    except Exception:
        return []
    items = payload
    if isinstance(payload, dict):
        items = payload.get('Results') or payload.get('results') or payload.get('items') or []
    if not isinstance(items, list):
        return []
    hits: list[ArrHit] = []
    name = indexer.get('name')
    protocol = indexer.get('protocol') or 'torznab'
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        hits.append(ArrHit(
            title=str(item.get('title') or item.get('Title') or item.get('name') or 'Untitled'),
            indexer=name,
            size=_as_int(item.get('size') or item.get('Size')),
            seeders=_as_int(item.get('seeders') or item.get('Seeders')),
            download_url=(
                item.get('downloadUrl')
                or item.get('download_url')
                or item.get('Link')
                or item.get('guid')
                or item.get('magnetUrl')
            ),
            info_url=item.get('infoUrl') or item.get('Details') or item.get('comments'),
            protocol='torrent' if protocol == 'torznab' else 'usenet',
        ))
    return hits


def json_loads_safe(body: str) -> Any:
    return json.loads(body)


def _local_tag(tag: str) -> str:
    if '}' in tag:
        return tag.rsplit('}', 1)[-1]
    return tag


def _parse_native_xml(body: str, indexer: dict[str, Any], *, limit: int) -> list[ArrHit]:
    if not body.strip():
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    items = [el for el in root.iter() if _local_tag(el.tag).lower() == 'item']
    hits: list[ArrHit] = []
    name = indexer.get('name')
    protocol = indexer.get('protocol') or 'torznab'
    for item in items[:limit]:
        title = 'Untitled'
        link = None
        guid = None
        comments = None
        size = None
        seeders = None
        enclosure = None
        for child in list(item):
            tag = _local_tag(child.tag).lower()
            text = (child.text or '').strip()
            if tag == 'title' and text:
                title = text
            elif tag == 'link' and text:
                link = text
            elif tag == 'guid' and text:
                guid = text
            elif tag == 'comments' and text:
                comments = text
            elif tag == 'size' and text:
                size = _as_int(text)
            elif tag == 'enclosure':
                enclosure = child.attrib.get('url') or enclosure
                if size is None and child.attrib.get('length'):
                    size = _as_int(child.attrib.get('length'))
            elif tag == 'attr':
                attr_name = (child.attrib.get('name') or '').lower()
                attr_val = child.attrib.get('value')
                if attr_name == 'seeders':
                    seeders = _as_int(attr_val)
                elif attr_name == 'size' and size is None:
                    size = _as_int(attr_val)
                elif attr_name in ('magneturl', 'downloadurl') and not enclosure:
                    enclosure = attr_val
        hits.append(ArrHit(
            title=title,
            indexer=name,
            size=size,
            seeders=seeders,
            download_url=enclosure or link or guid,
            info_url=comments or link,
            protocol='torrent' if protocol == 'torznab' else 'usenet',
        ))
    return hits


def _as_int(value: Any) -> int | None:
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _search_prowlarr(cfg: dict, query: str, *, limit: int) -> list[ArrHit]:
    url = urljoin(cfg['prowlarr_url'] + '/', 'api/v1/search')
    resp = fetch_with_challenge_retry(
        'get',
        url,
        params={'query': query, 'type': 'search', 'limit': limit},
        headers={'X-Api-Key': cfg['prowlarr_api_key']},
        timeout=DEFAULT_TIMEOUT,
        # Admin-configured hub: the same LAN-aware policy it was saved under,
        # now applied to the URL actually fetched and to every redirect hop.
        validator=validate_connector_http_url,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f'Prowlarr search failed ({resp.status_code})')
    payload = resp.json()
    if not isinstance(payload, list):
        return []
    hits: list[ArrHit] = []
    for item in payload[:limit]:
        hits.append(ArrHit(
            title=str(item.get('title') or item.get('fileName') or 'Untitled'),
            indexer=item.get('indexer'),
            size=item.get('size'),
            seeders=item.get('seeders'),
            download_url=item.get('downloadUrl') or item.get('guid'),
            info_url=item.get('infoUrl'),
            protocol=item.get('protocol'),
        ))
    return hits


def _search_jackett(cfg: dict, query: str, *, limit: int) -> list[ArrHit]:
    url = urljoin(cfg['jackett_url'] + '/', 'api/v2.0/indexers/all/results')
    resp = fetch_with_challenge_retry(
        'get',
        url,
        params={'apikey': cfg['jackett_api_key'], 'Query': query},
        timeout=DEFAULT_TIMEOUT,
        validator=validate_connector_http_url,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f'Jackett search failed ({resp.status_code})')
    payload = resp.json() if resp.content else {}
    results = payload.get('Results') if isinstance(payload, dict) else payload
    if not isinstance(results, list):
        return []
    hits: list[ArrHit] = []
    for item in results[:limit]:
        hits.append(ArrHit(
            title=str(item.get('Title') or 'Untitled'),
            indexer=item.get('Tracker'),
            size=item.get('Size'),
            seeders=item.get('Seeders'),
            download_url=item.get('Link') or item.get('MagnetUri'),
            info_url=item.get('Details'),
            protocol='torrent',
        ))
    return hits


def qbittorrent_add_url(download_url: str) -> dict[str, Any]:
    cfg = get_arr_config()
    if not cfg['qbittorrent_url']:
        raise RuntimeError('qBittorrent URL is not configured')
    if not download_url:
        raise ValueError('download_url is required')

    session = requests.Session()
    login = safe_request(
        'POST',
        urljoin(cfg['qbittorrent_url'] + '/', 'api/v2/auth/login'),
        validator=validate_connector_http_url,
        session=session,
        data={
            'username': cfg['qbittorrent_username'],
            'password': cfg['qbittorrent_password'],
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if login.status_code >= 400 or (login.text or '').strip().lower() == 'fails.':
        raise RuntimeError('qBittorrent login failed')

    add = safe_request(
        'POST',
        urljoin(cfg['qbittorrent_url'] + '/', 'api/v2/torrents/add'),
        validator=validate_connector_http_url,
        session=session,
        data={'urls': download_url},
        timeout=DEFAULT_TIMEOUT,
    )
    if add.status_code >= 400:
        raise RuntimeError(f'qBittorrent add failed ({add.status_code})')
    return {'status': 'queued', 'download_url': download_url}


def transmission_add_url(download_url: str) -> dict[str, Any]:
    cfg = get_arr_config()
    if not cfg['transmission_url']:
        raise RuntimeError('Transmission URL is not configured')
    if not download_url:
        raise ValueError('download_url is required')
    auth = None
    if cfg.get('transmission_username'):
        auth = (cfg['transmission_username'], cfg.get('transmission_password') or '')
    # Session id handshake
    session = requests.Session()
    ping = safe_request(
        'POST',
        urljoin(cfg['transmission_url'] + '/', 'transmission/rpc'),
        validator=validate_connector_http_url,
        session=session,
        json={'method': 'session-get'},
        auth=auth,
        timeout=DEFAULT_TIMEOUT,
    )
    headers = {}
    session_id = ping.headers.get('X-Transmission-Session-Id')
    if session_id:
        headers['X-Transmission-Session-Id'] = session_id
    add = safe_request(
        'POST',
        urljoin(cfg['transmission_url'] + '/', 'transmission/rpc'),
        validator=validate_connector_http_url,
        session=session,
        json={'method': 'torrent-add', 'arguments': {'filename': download_url}},
        headers=headers,
        auth=auth,
        timeout=DEFAULT_TIMEOUT,
    )
    if add.status_code >= 400:
        raise RuntimeError(f'Transmission add failed ({add.status_code})')
    return {'status': 'queued', 'provider': 'transmission', 'download_url': download_url}


def sabnzbd_add_url(nzb_url: str) -> dict[str, Any]:
    cfg = get_arr_config()
    if not cfg['sabnzbd_url'] or not cfg['sabnzbd_api_key']:
        raise RuntimeError('SABnzbd is not configured')
    if not nzb_url:
        raise ValueError('nzb_url is required')
    resp = safe_request(
        'GET',
        urljoin(cfg['sabnzbd_url'] + '/', 'api'),
        validator=validate_connector_http_url,
        params={
            'mode': 'addurl',
            'name': nzb_url,
            'apikey': cfg['sabnzbd_api_key'],
            'output': 'json',
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f'SABnzbd add failed ({resp.status_code})')
    return {'status': 'queued', 'provider': 'sabnzbd', 'download_url': nzb_url}


def nzbget_add_url(nzb_url: str) -> dict[str, Any]:
    """Queue an NZB/URL via NZBGet JSON-RPC ``append``."""
    cfg = get_arr_config()
    if not cfg['nzbget_url']:
        raise RuntimeError('NZBGet URL is not configured')
    if not nzb_url:
        raise ValueError('nzb_url is required')
    auth = None
    if cfg.get('nzbget_username'):
        auth = (cfg['nzbget_username'], cfg.get('nzbget_password') or '')
    # NZBGet JSON-RPC: append(NZBFilename, NZBContent, Category, Priority, AddToTop, AddPaused, DupeKey, DupeScore, DupeMode)
    # When NZBContent is a URL, NZBGet fetches it.
    payload = {
        'method': 'append',
        'params': [
            '',  # NZBFilename (auto from URL)
            nzb_url,
            '',  # Category
            0,  # Priority
            False,  # AddToTop
            False,  # AddPaused
            '',  # DupeKey
            0,  # DupeScore
            'SCORE',  # DupeMode
        ],
        'id': 1,
    }
    resp = safe_request(
        'POST',
        urljoin(cfg['nzbget_url'] + '/', 'jsonrpc'),
        validator=validate_connector_http_url,
        json=payload,
        auth=auth,
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f'NZBGet add failed ({resp.status_code})')
    body = resp.json() if resp.content else {}
    if isinstance(body, dict) and body.get('error'):
        raise RuntimeError(f"NZBGet error: {body.get('error')}")
    return {'status': 'queued', 'provider': 'nzbget', 'download_url': nzb_url, 'result': body.get('result')}


def send_to_download_client(download_url: str, *, provider: str = 'qbittorrent') -> dict[str, Any]:
    provider = (provider or 'qbittorrent').lower()
    if provider == 'qbittorrent':
        return qbittorrent_add_url(download_url)
    if provider == 'transmission':
        return transmission_add_url(download_url)
    if provider == 'sabnzbd':
        return sabnzbd_add_url(download_url)
    if provider == 'nzbget':
        return nzbget_add_url(download_url)
    if provider == 'deluge':
        # Deluge JSON-RPC varies by plugin; queue via Transmission-compatible path when unset.
        raise RuntimeError('Deluge send requires WebUI JSON plugin — configure Transmission or qBittorrent for now')
    raise ValueError(f'Unknown download client: {provider}')
