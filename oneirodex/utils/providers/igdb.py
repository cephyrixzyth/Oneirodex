"""IGDB cover search provider (artwork only — uses existing IGDB credentials)."""

from __future__ import annotations

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.igdb_api import make_igdb_api_request
from oneirodex.utils.providers.base import (
    ImageSearchResult,
    MetadataImageProvider,
    ProviderDisabledError,
    fetch_outbound_image,
)

DEFAULT_TIMEOUT = 20


def igdb_credentials_configured() -> bool:
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    return bool(settings and settings.igdb_client_id and settings.igdb_client_secret)


class IgdbCoverProvider(MetadataImageProvider):
    id = 'igdb'
    name = 'IGDB Covers'
    description = 'Search IGDB for cover art using your existing IGDB API credentials.'

    def is_enabled(self) -> bool:
        return igdb_credentials_configured()

    def config_hint(self) -> str:
        if self.is_enabled():
            return 'Using GlobalSettings IGDB client credentials'
        return 'Configure IGDB client ID/secret under Integrations → IGDB'

    def _require_enabled(self) -> None:
        if not self.is_enabled():
            raise ProviderDisabledError(self.id, 'IGDB is not configured')

    def search_covers(self, query: str, *, limit: int = 20) -> list[ImageSearchResult]:
        self._require_enabled()
        q = (query or '').strip().replace('"', '')
        if not q:
            return []
        limit = max(1, min(int(limit or 20), 50))
        # Search games, then pull cover image_id for each hit
        game_query = (
            f'search "{q}"; fields id,name,cover.image_id; '
            f'where cover != null; limit {limit};'
        )
        response = make_igdb_api_request('https://api.igdb.com/v4/games', game_query)
        if isinstance(response, dict) and response.get('error'):
            raise RuntimeError(str(response['error']))
        if not isinstance(response, list):
            return []

        results: list[ImageSearchResult] = []
        for game in response:
            if len(results) >= limit:
                break
            cover = game.get('cover') or {}
            image_id = cover.get('image_id') if isinstance(cover, dict) else None
            if not image_id:
                continue
            url = f'https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg'
            thumb = f'https://images.igdb.com/igdb/image/upload/t_cover_small/{image_id}.jpg'
            results.append(
                ImageSearchResult(
                    id=str(image_id),
                    url=url,
                    thumb_url=thumb,
                    game_id=game.get('id'),
                    game_name=game.get('name'),
                    image_type='cover',
                    mime='image/jpeg',
                )
            )
        return results

    def fetch_image(self, url: str) -> tuple[bytes, str | None]:
        self._require_enabled()
        return fetch_outbound_image(url, timeout=DEFAULT_TIMEOUT)
