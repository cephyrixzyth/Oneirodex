"""Fetch top gaming headlines from public RSS feeds (best-effort)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import requests

from product_env import getenv_product
from oneirodex.utils.http_safe import safe_get
from oneirodex.utils.security import validate_user_outbound_http_url

DEFAULT_FEED_URLS = (
    'https://www.polygon.com/rss/index.xml',
    'https://www.pcgamer.com/rss/',
    'https://www.rockpapershotgun.com/feed',
)
MAX_FEED_BYTES = 512_000


def feed_urls() -> tuple[str, ...]:
    """Which sites headlines come from.

    Was a hardcoded tuple, so a household that did not care for one of these
    three — or wanted a site of its own — had no say at all. ``ONEIRODEX_NEWS_FEEDS``
    (or ``ONEIRODEX_NEWS_FEEDS``) replaces the list entirely (comma or pipe
    separated); unset keeps the defaults. Only http(s) entries are accepted:
    this list is fetched by the server, so a `file://` in it would be a read
    of the server's own disk.
    """
    raw = (getenv_product('NEWS_FEEDS') or '').strip()
    if not raw:
        return DEFAULT_FEED_URLS

    urls = []
    for chunk in raw.replace('|', ',').split(','):
        url = chunk.strip()
        if url.lower().startswith(('http://', 'https://')) and url not in urls:
            urls.append(url)
    return tuple(urls) or DEFAULT_FEED_URLS


def source_name(url: str) -> str:
    """The host, as shown on a headline card and used to filter by site."""
    try:
        return url.split('/')[2].replace('www.', '')
    except IndexError:
        return url

_TAG_RE = re.compile(r'<[^>]+>')


def _strip_html(text: str) -> str:
    return _TAG_RE.sub('', text or '').strip()


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ''
    return node.text.strip()


# Feeds advertise artwork in several places depending on generator. Checked in
# rough order of reliability; the first https image wins.
_MEDIA_NS = 'http://search.yahoo.com/mrss/'
_IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')


def _item_image(node: ET.Element | None) -> str | None:
    """Pull a headline image out of an RSS/Atom entry (UX-C14).

    Only ``https`` is accepted: these URLs are rendered in the member app, and
    an http image on an https page is blocked as mixed content anyway.
    """
    if node is None:
        return None

    candidates: list[str] = []

    for tag in (f'{{{_MEDIA_NS}}}content', f'{{{_MEDIA_NS}}}thumbnail'):
        for el in node.findall(tag):
            url = (el.attrib.get('url') or '').strip()
            if url:
                candidates.append(url)

    for el in node.findall('enclosure'):
        url = (el.attrib.get('url') or '').strip()
        mime = (el.attrib.get('type') or '').lower()
        if url and (mime.startswith('image/') or url.lower().endswith(_IMAGE_EXT)):
            candidates.append(url)

    # Atom: <link rel="enclosure" type="image/..." href="...">
    for el in node.findall('{http://www.w3.org/2005/Atom}link'):
        if (el.attrib.get('rel') or '') == 'enclosure':
            url = (el.attrib.get('href') or '').strip()
            mime = (el.attrib.get('type') or '').lower()
            if url and (mime.startswith('image/') or url.lower().endswith(_IMAGE_EXT)):
                candidates.append(url)

    for url in candidates:
        if url.startswith('https://'):
            return url[:500]
    return None


def _parse_feed(xml_bytes: bytes, source: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items

    # RSS 2.0
    for item in root.findall('.//item'):
        title = _text(item.find('title'))
        link = _text(item.find('link'))
        summary = _strip_html(_text(item.find('description')))
        published = _text(item.find('pubDate'))
        if title and link:
            items.append({
                'title': title[:240],
                'url': link,
                'summary': summary[:400],
                'published_at': published,
                'source': source,
                'image_url': _item_image(item),
            })

    # Atom
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    for entry in root.findall('.//{http://www.w3.org/2005/Atom}entry') or root.findall('.//a:entry', ns):
        title = _text(entry.find('{http://www.w3.org/2005/Atom}title'))
        link_el = entry.find('{http://www.w3.org/2005/Atom}link')
        link = ''
        if link_el is not None:
            link = link_el.attrib.get('href') or _text(link_el)
        summary = _strip_html(
            _text(entry.find('{http://www.w3.org/2005/Atom}summary'))
            or _text(entry.find('{http://www.w3.org/2005/Atom}content'))
        )
        published = _text(entry.find('{http://www.w3.org/2005/Atom}updated')) or _text(
            entry.find('{http://www.w3.org/2005/Atom}published')
        )
        if title and link:
            items.append({
                'title': title[:240],
                'url': link,
                'summary': summary[:400],
                'published_at': published,
                'source': source,
                'image_url': _item_image(entry),
            })

    return items


def fetch_gaming_headlines(*, limit: int = 12) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for url in feed_urls():
        if len(collected) >= limit:
            break
        source = source_name(url)
        try:
            with requests.Session() as session:
                with safe_get(
                    url,
                    validator=validate_user_outbound_http_url,
                    session=session,
                    headers={'User-Agent': 'OneirodexNews/0.2'},
                    timeout=6,
                    stream=True,
                ) as resp:
                    resp.raise_for_status()
                    xml = bytearray()
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if len(xml) + len(chunk) > MAX_FEED_BYTES:
                            raise ValueError('News feed exceeds size limit')
                        xml.extend(chunk)
                    xml_bytes = bytes(xml)
            collected.extend(_parse_feed(xml_bytes, source))
        except Exception:
            continue

    # De-dupe by URL
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in collected:
        key = item.get('url') or ''
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique
