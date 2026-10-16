"""SteamGridDB artwork provider (grids/covers only — no game downloads)."""

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
)

STEAMGRIDDB_API_BASE = 'https://www.steamgriddb.com/api/v2'
DEFAULT_TIMEOUT = 10


def get_steamgriddb_api_key() -> str | None:
    """Server-level SteamGridDB API key from env or global settings."""
    key = (os.getenv('STEAMGRIDDB_API_KEY') or '').strip()
    if key:
        return key
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    if settings and settings.steamgriddb_api_key:
        return settings.steamgriddb_api_key.strip()
    return None


class SteamGridDBProvider(MetadataImageProvider):
    id = 'steamgriddb'
    name = 'SteamGridDB'
    description = 'Community-sourced grid covers and artwork from SteamGridDB.'

    def config_hint(self) -> str:
        return 'Set STEAMGRIDDB_API_KEY in the environment or Admin → Integrations.'

    def is_enabled(self) -> bool:
        return bool(get_steamgriddb_api_key())

    def _require_enabled(self) -> str:
        api_key = get_steamgriddb_api_key()
        if not api_key:
            raise ProviderDisabledError(
                self.id,
                'SteamGridDB is not configured. Set STEAMGRIDDB_API_KEY and restart the app.',
            )
        return api_key

    def _headers(self, api_key: str) -> dict[str, str]:
        return {'Authorization': f'Bearer {api_key}'}

    def _get_json(self, path: str, *, params: dict | None = None) -> dict:
        api_key = self._require_enabled()
        url = f'{STEAMGRIDDB_API_BASE}{path}'
        response = requests.get(
            url,
            headers=self._headers(api_key),
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code == 401:
            raise ProviderDisabledError(
                self.id,
                'SteamGridDB rejected the API key (401 Unauthorized).',
            )
        if response.status_code != 200:
            raise RuntimeError(
                f'SteamGridDB request failed ({response.status_code}) for {path}',
            )
        payload = response.json()
        if not payload.get('success'):
            raise RuntimeError(payload.get('message') or 'SteamGridDB request failed')
        return payload

    def search_covers(self, query: str, *, limit: int = 20) -> list[ImageSearchResult]:
        return self.search_artwork(query, limit=limit, art_kind='cover')

    def search_artwork(
        self,
        query: str,
        *,
        limit: int = 20,
        art_kind: str = 'cover',
    ) -> list[ImageSearchResult]:
        """Search SteamGridDB grids (cover), logos, or heroes."""
        query = (query or '').strip()
        if not query:
            return []

        kind = (art_kind or 'cover').strip().lower()
        endpoint = {
            'cover': 'grids',
            'logo': 'logos',
            'hero': 'heroes',
        }.get(kind, 'grids')
        image_type = 'cover' if kind == 'cover' else kind

        limit = max(1, min(limit, 50))
        encoded_query = quote(query, safe='')
        search_payload = self._get_json(f'/search/autocomplete/{encoded_query}')
        games = _normalize_autocomplete_games(search_payload.get('data') or [])
        if not games:
            return []

        results: list[ImageSearchResult] = []
        per_game_limit = max(1, min(limit, 20))
        for game in games[:3]:
            if len(results) >= limit:
                break
            game_id = game.get('id')
            game_name = game.get('name')
            if game_id is None:
                continue
            payload = self._get_json(
                f'/{endpoint}/game/{game_id}',
                params={'limit': per_game_limit},
            )
            for item in payload.get('data') or []:
                if len(results) >= limit:
                    break
                normalized = _normalize_grid_item(
                    item,
                    game_id=game_id,
                    game_name=game_name,
                    image_type=image_type,
                )
                if normalized is not None:
                    results.append(normalized)
        return results

    def fetch_image(self, url: str) -> tuple[bytes, str | None]:
        self._require_enabled()
        return fetch_outbound_image(url, timeout=DEFAULT_TIMEOUT)


def _normalize_autocomplete_games(raw_items: list) -> list[dict]:
    games: list[dict] = []
    for item in raw_items:
        if isinstance(item, dict) and 'id' in item and 'name' in item:
            games.append(item)
            continue
        if isinstance(item, dict) and isinstance(item.get('data'), dict):
            nested = item['data']
            if 'id' in nested and 'name' in nested:
                games.append(nested)
    return games


def _normalize_grid_item(
    item: dict,
    *,
    game_id: int | None,
    game_name: str | None,
    image_type: str = 'grid',
) -> ImageSearchResult | None:
    url = item.get('url')
    if not url:
        return None
    grid_id = item.get('id')
    return ImageSearchResult(
        id=str(grid_id if grid_id is not None else url),
        url=url,
        thumb_url=item.get('thumb'),
        width=item.get('width'),
        height=item.get('height'),
        score=item.get('score'),
        style=item.get('style'),
        mime=item.get('mime'),
        nsfw=item.get('nsfw'),
        game_id=game_id,
        game_name=game_name,
        image_type=image_type,
    )
