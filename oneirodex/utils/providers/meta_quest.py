"""Meta / Quest metadata + cover search (artwork / identify only — never downloads games).

Identify modes (``META_QUEST_API_MODE``):
  - ``igdb`` (default) — search IGDB games on Quest platform IDs (practical catalog).
  - ``csv_only`` — no live catalog search; empty list (ownership uses CSV register).
  - ``disabled`` — always empty.
  - ``unofficial_graphql`` — **off unless** ``META_QUEST_UNOFFICIAL_GRAPHQL=1``; stub returns
    empty until a supported official path exists (never default-on).

Optional ``META_GRAPH_ACCESS_TOKEN`` is reserved for a future official Meta catalog.
VR is signaled via ``is_vr`` / Virtual Reality perspective — not a LibraryPlatform leaf.
"""

from __future__ import annotations

import os
import re

import requests
from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.igdb_api import make_igdb_api_request
from oneirodex.utils.providers.base import (
    ImageSearchResult,
    MetadataImageProvider,
    ProviderDisabledError,
    fetch_outbound_image,
    mask_api_key,
)
from oneirodex.utils.providers.igdb import igdb_credentials_configured

DEFAULT_TIMEOUT = 20

# Identify + ownership API modes (AC2). Unofficial GraphQL never default-on.
API_MODES = frozenset({'igdb', 'csv_only', 'disabled', 'unofficial_graphql'})

# IGDB platform IDs for Meta / Oculus Quest family (metadata search only).
META_QUEST_PLATFORM_IDS: tuple[int, ...] = (
    162,   # Oculus VR
    384,   # Oculus Quest
    386,   # Meta Quest 2
    471,   # Meta Quest 3
    509,   # Meta Quest Pro
)

SOURCE_ALIASES = frozenset({'meta_quest', 'meta', 'quest'})


def get_meta_graph_access_token() -> str | None:
    """Optional Meta Graph token — live store catalog not required for identify."""
    env = (os.getenv('META_GRAPH_ACCESS_TOKEN') or '').strip()
    if env:
        return env
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    key = getattr(settings, 'meta_graph_access_token', None) if settings else None
    return (key or '').strip() or None


def unofficial_graphql_enabled() -> bool:
    """Unofficial graph.oculus.com path — explicit opt-in only (never default-on)."""
    raw = (os.getenv('META_QUEST_UNOFFICIAL_GRAPHQL') or '').strip().lower()
    return raw in ('1', 'true', 'yes', 'on')


def get_meta_quest_api_mode() -> str:
    """
    Resolve identify search mode.

    Default ``igdb`` when unset (practical Quest-platform search). Operators may set
    ``META_QUEST_API_MODE=csv_only|disabled|unofficial_graphql``. Unofficial GraphQL
    still requires ``META_QUEST_UNOFFICIAL_GRAPHQL=1`` or it degrades to empty results.
    """
    raw = (os.getenv('META_QUEST_API_MODE') or 'igdb').strip().lower()
    if raw in ('meta', 'quest'):
        return 'igdb'
    if raw in API_MODES:
        return raw
    return 'igdb'


def normalize_meta_quest_source(source: str | None) -> str | None:
    """Map UI aliases (meta / quest) to canonical ``meta_quest``."""
    key = (source or '').strip().lower()
    if key in SOURCE_ALIASES:
        return 'meta_quest'
    return None


def _platform_filter_clause() -> str:
    ids = ','.join(str(pid) for pid in META_QUEST_PLATFORM_IDS)
    return f'platforms = ({ids})'


def _hit_dict(
    *,
    hit_id,
    name: str | None,
    url: str | None,
    cover_url: str | None,
    summary: str | None = None,
    platforms: list[str] | None = None,
    release_date=None,
    igdb_id=None,
) -> dict:
    """Identify UI hit — metadata / ownership only; never install/download URLs."""
    store_id = str(hit_id) if hit_id is not None else None
    return {
        'source': 'meta_quest',
        'id': hit_id,
        'name': name,
        'url': url,
        'cover_url': cover_url,
        'summary': summary,
        'meta_quest_id': store_id,
        'igdb_id': igdb_id,
        'platforms': platforms or [],
        'release_date': release_date,
        'is_vr': True,
        'ownership_only': True,
        'api_mode': get_meta_quest_api_mode(),
        'note': (
            'Metadata / ownership register only — Oneirodex never downloads '
            'Meta Quest Store DRM titles.'
        ),
    }


def _search_igdb(game_name: str, limit: int) -> list[dict]:
    clean = re.sub(r'[\(\)\[\]]', '', game_name or '').strip().replace('"', '')
    if not clean:
        return []
    if not igdb_credentials_configured():
        return []

    query = (
        f'search "{clean}"; '
        f'fields id,name,slug,summary,cover.image_id,first_release_date,platforms.name; '
        f'where {_platform_filter_clause()}; '
        f'limit {limit};'
    )
    try:
        response = make_igdb_api_request('https://api.igdb.com/v4/games', query)
    except Exception as exc:  # noqa: BLE001 — identify UI must degrade gracefully
        print(f'Meta/Quest IGDB search error for {game_name}: {exc}')
        return []

    if isinstance(response, dict) and response.get('error'):
        print(f'Meta/Quest IGDB search error: {response["error"]}')
        return []
    if not isinstance(response, list):
        return []

    results: list[dict] = []
    for game in response:
        cover = game.get('cover') or {}
        image_id = cover.get('image_id') if isinstance(cover, dict) else None
        cover_url = None
        if image_id:
            cover_url = f'https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg'
        platforms = [
            p.get('name') for p in (game.get('platforms') or [])
            if isinstance(p, dict) and p.get('name')
        ]
        slug = game.get('slug')
        results.append(
            _hit_dict(
                hit_id=game.get('id'),
                name=game.get('name'),
                url=f'https://www.igdb.com/games/{slug}' if slug else None,
                cover_url=cover_url,
                summary=game.get('summary'),
                platforms=platforms,
                release_date=game.get('first_release_date'),
                igdb_id=game.get('id'),
            )
        )
    return results


def _search_unofficial_graphql(game_name: str, limit: int) -> list[dict]:
    """Stub: unofficial GraphQL stays empty unless explicitly enabled (and still unused)."""
    if not unofficial_graphql_enabled():
        return []
    # Deliberately empty — we do not call graph.oculus.com from product code.
    # Ownership remains CSV; identify falls back to IGDB when mode is flipped back.
    _ = (game_name, limit)
    return []


def search_meta_quest_games(game_name: str, limit: int = 10) -> list[dict]:
    """
    Identify-UI search hits for Meta/Quest titles.

    Returns the same shape as Steam/GOG/RAWG identify results. Never downloads
    DRM binaries — metadata + cover URLs only. Empty list on miss/error (no raise).
    """
    limit = max(1, min(int(limit or 10), 20))
    mode = get_meta_quest_api_mode()
    if mode == 'disabled' or mode == 'csv_only':
        return []
    if mode == 'unofficial_graphql':
        return _search_unofficial_graphql(game_name, limit)
    return _search_igdb(game_name, limit)


class MetaQuestProvider(MetadataImageProvider):
    """Cover search for Meta/Quest titles via IGDB platforms (artwork only)."""

    id = 'meta_quest'
    name = 'Meta Quest Store (IGDB)'
    description = (
        'Search Meta/Quest platform titles via IGDB for identify and cover art. '
        'Ownership is CSV register-only. Unofficial GraphQL is off by default. '
        'Never downloads DRM games.'
    )

    def is_enabled(self) -> bool:
        mode = get_meta_quest_api_mode()
        if mode in ('disabled', 'csv_only'):
            return False
        if mode == 'unofficial_graphql':
            return unofficial_graphql_enabled()
        return igdb_credentials_configured()

    def config_hint(self) -> str:
        mode = get_meta_quest_api_mode()
        token = get_meta_graph_access_token()
        if mode == 'disabled':
            return 'META_QUEST_API_MODE=disabled'
        if mode == 'csv_only':
            return 'csv_only — use POST /api/ownership/meta_quest/csv for ownership register'
        if mode == 'unofficial_graphql':
            if not unofficial_graphql_enabled():
                return (
                    'unofficial_graphql mode set but META_QUEST_UNOFFICIAL_GRAPHQL is off '
                    '(default) — search returns empty'
                )
            return 'unofficial_graphql enabled (unsupported stub — returns empty)'
        if self.is_enabled() and token:
            return (
                f'IGDB configured; Meta Graph token present ({mask_api_key(token)}) '
                '(official catalog stub — IGDB used for search)'
            )
        if self.is_enabled():
            return (
                'Using IGDB Quest platform filter. Ownership: CSV register-only. '
                'Optional: META_GRAPH_ACCESS_TOKEN / META_QUEST_API_MODE.'
            )
        return 'Configure IGDB client ID/secret under Integrations → IGDB'

    def _require_enabled(self) -> None:
        if not self.is_enabled():
            raise ProviderDisabledError(
                self.id,
                self.config_hint() or 'Meta/Quest search is not configured',
            )

    def search_covers(self, query: str, *, limit: int = 20) -> list[ImageSearchResult]:
        self._require_enabled()
        hits = search_meta_quest_games(query, limit=limit)
        results: list[ImageSearchResult] = []
        for hit in hits:
            url = hit.get('cover_url')
            if not url:
                continue
            results.append(
                ImageSearchResult(
                    id=str(hit.get('id') or url),
                    url=url,
                    thumb_url=url.replace('/t_cover_big/', '/t_cover_small/'),
                    game_id=hit.get('igdb_id') if isinstance(hit.get('igdb_id'), int) else None,
                    game_name=hit.get('name'),
                    image_type='cover',
                    mime='image/jpeg',
                )
            )
        return results

    def fetch_image(self, url: str) -> tuple[bytes, str | None]:
        self._require_enabled()
        return fetch_outbound_image(url, timeout=DEFAULT_TIMEOUT)
