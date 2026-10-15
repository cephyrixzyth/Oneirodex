"""GiantBomb + PCGamingWiki enrichment providers (metadata / links only)."""

from __future__ import annotations

import os
from urllib.parse import quote

import requests
from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.providers.base import (
    ImageSearchResult,
    MetadataImageProvider,
    ProviderDisabledError,
    fetch_outbound_image,
    mask_api_key,
)

DEFAULT_TIMEOUT = 20


def get_giantbomb_api_key() -> str | None:
    env = (os.getenv('GIANTBOMB_API_KEY') or '').strip()
    if env:
        return env
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    key = getattr(settings, 'giantbomb_api_key', None) if settings else None
    return (key or '').strip() or None


class GiantBombProvider(MetadataImageProvider):
    id = 'giantbomb'
    name = 'GiantBomb'
    description = 'Search GiantBomb for game metadata and cover images (requires API key).'

    def is_enabled(self) -> bool:
        return bool(get_giantbomb_api_key())

    def config_hint(self) -> str:
        key = get_giantbomb_api_key()
        if key:
            return f'API key configured ({mask_api_key(key)})'
        return 'Set GIANTBOMB_API_KEY or Admin Integrations → GiantBomb'

    def search_covers(self, query: str, *, limit: int = 20) -> list[ImageSearchResult]:
        key = get_giantbomb_api_key()
        if not key:
            raise ProviderDisabledError(self.id, 'GiantBomb API key is not configured')
        q = (query or '').strip()
        if not q:
            return []
        limit = max(1, min(int(limit or 20), 50))
        resp = requests.get(
            'https://www.giantbomb.com/api/search/',
            params={
                'api_key': key,
                'format': 'json',
                'query': q,
                'resources': 'game',
                'limit': limit,
            },
            headers={'User-Agent': 'Oneirodex/1.0 (self-hosted library)'},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f'GiantBomb search failed ({resp.status_code})')
        payload = resp.json() if resp.content else {}
        results: list[ImageSearchResult] = []
        for item in payload.get('results') or []:
            image = item.get('image') or {}
            url = image.get('super_url') or image.get('medium_url') or image.get('small_url')
            if not url:
                continue
            results.append(ImageSearchResult(
                id=str(item.get('id') or url),
                url=url,
                thumb_url=image.get('thumb_url') or image.get('small_url'),
                game_id=item.get('id'),
                game_name=item.get('name'),
                image_type='cover',
            ))
        return results

    def fetch_image(self, url: str) -> tuple[bytes, str | None]:
        return fetch_outbound_image(
            url,
            timeout=DEFAULT_TIMEOUT,
            headers={'User-Agent': 'Oneirodex/1.0 (self-hosted library)'},
        )


def pcgamingwiki_enrichment(game_name: str) -> dict:
    """
    Build a PCGamingWiki deep link + optional MediaWiki search hit.
    Does not scrape page HTML; uses public MediaWiki API opensearch only.
    """
    name = (game_name or '').strip()
    if not name:
        return {'provider': 'pcgamingwiki', 'results': []}

    wiki_search = f'https://www.pcgamingwiki.com/w/api.php'
    resp = requests.get(
        wiki_search,
        params={
            'action': 'opensearch',
            'search': name,
            'limit': 5,
            'namespace': 0,
            'format': 'json',
        },
        headers={'User-Agent': 'Oneirodex/1.0 (self-hosted library)'},
        timeout=DEFAULT_TIMEOUT,
    )
    results = []
    if resp.status_code < 400:
        payload = resp.json()
        # opensearch: [query, titles, descriptions, urls]
        if isinstance(payload, list) and len(payload) >= 4:
            titles, urls = payload[1], payload[3]
            for title, url in zip(titles, urls):
                results.append({'title': title, 'url': url})
    if not results:
        results.append({
            'title': name,
            'url': f'https://www.pcgamingwiki.com/wiki/Special:Search?search={quote(name)}',
        })
    return {'provider': 'pcgamingwiki', 'query': name, 'results': results}


class PcGamingWikiProvider(MetadataImageProvider):
    """Link enrichment provider — no cover download pipeline."""

    id = 'pcgamingwiki'
    name = 'PCGamingWiki'
    description = 'Find PCGamingWiki pages for DRM-free fix / settings notes (links only).'

    def is_enabled(self) -> bool:
        return True

    def config_hint(self) -> str:
        return 'No API key required — uses public MediaWiki opensearch'

    def search_covers(self, query: str, *, limit: int = 20) -> list[ImageSearchResult]:
        # Not an image provider; return empty covers and use enrichment endpoint instead.
        return []

    def fetch_image(self, url: str) -> tuple[bytes, str | None]:
        raise RuntimeError('PCGamingWiki does not provide downloadable cover images')
