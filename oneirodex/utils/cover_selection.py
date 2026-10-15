"""Cover search + selection policy for single-title and mass art tools.

Artwork only — never downloads game binaries. Prefer local SteamGridDB hits,
then IGDB, then GiantBomb, then Meta/Quest IGDB, then procedural generate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Image, Library
from oneirodex.utils.artwork_apply import apply_cover_from_url
from oneirodex.utils.providers import ProviderDisabledError, get_provider
from oneirodex.utils.runtime_config import get_runtime_config

# Ordered default preference for auto-apply.
DEFAULT_PROVIDER_ORDER: tuple[str, ...] = (
    'steamgriddb',
    'igdb',
    'giantbomb',
    'meta_quest',
)

POLICY_ALIASES: dict[str, tuple[str, ...]] = {
    'sgdb_then_igdb_then_generate': ('steamgriddb', 'igdb', 'giantbomb', 'meta_quest', 'generate'),
    'prefer_local_sgdb': ('steamgriddb', 'igdb', 'giantbomb', 'meta_quest', 'generate'),
    # Admin ImagesPage auto-pick default.
    'best_available': ('steamgriddb', 'igdb', 'giantbomb', 'meta_quest', 'generate'),
    'igdb_only': ('igdb',),
    'sgdb_only': ('steamgriddb',),
    'generate_only': ('generate',),
}


@dataclass
class CoverCandidate:
    provider: str
    url: str
    thumb_url: str | None = None
    game_name: str | None = None
    score: int | None = None
    image_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'provider': self.provider,
            'url': self.url,
            'thumb_url': self.thumb_url,
            'game_name': self.game_name,
            'score': self.score,
            'id': self.image_id,
        }


def image_save_path_status(config=None) -> dict[str, Any]:
    """Report whether IMAGE_SAVE_PATH exists and is writable (ops diagnostics)."""
    if config is None:
        config = get_runtime_config() or {}
    path = config.get('IMAGE_SAVE_PATH')
    if not path:
        return {
            'path': None,
            'exists': False,
            'writable': False,
            'error': 'IMAGE_SAVE_PATH is not configured',
        }
    exists_on_disk = os.path.isdir(path)
    writable = False
    error = None
    if not exists_on_disk:
        try:
            os.makedirs(path, exist_ok=True)
            exists_on_disk = os.path.isdir(path)
        except OSError as exc:
            error = f'Cannot create IMAGE_SAVE_PATH: {exc}'
    if exists_on_disk:
        writable = os.access(path, os.W_OK)
        if not writable:
            error = f"IMAGE_SAVE_PATH '{path}' is not writable by the Oneirodex process"
    return {
        'path': path,
        'exists': exists_on_disk,
        'writable': writable,
        'error': error,
    }


def resolve_policy(policy: str | None) -> tuple[str, ...]:
    raw = (policy or 'sgdb_then_igdb_then_generate').strip().lower()
    if raw in POLICY_ALIASES:
        return POLICY_ALIASES[raw]
    if raw.startswith('provider:'):
        provider_id = raw.split(':', 1)[1].strip()
        if provider_id:
            return (provider_id,)
    # Comma-separated custom order
    parts = tuple(p.strip() for p in raw.split(',') if p.strip())
    return parts or POLICY_ALIASES['sgdb_then_igdb_then_generate']


def search_cover_candidates(
    query: str,
    *,
    providers: list[str] | None = None,
    limit_per_provider: int = 8,
) -> dict[str, Any]:
    """Search one or more artwork providers; return merged candidates + per-provider errors."""
    q = (query or '').strip()
    if not q:
        return {'query': q, 'candidates': [], 'errors': [{'error': 'query is required'}]}

    provider_ids = providers or list(DEFAULT_PROVIDER_ORDER)
    candidates: list[CoverCandidate] = []
    errors: list[dict[str, str]] = []

    for provider_id in provider_ids:
        if provider_id == 'generate':
            continue
        try:
            provider = get_provider(provider_id)
        except KeyError:
            errors.append({'provider': provider_id, 'error': f'Unknown provider: {provider_id}'})
            continue
        if not provider.is_enabled():
            errors.append({
                'provider': provider_id,
                'error': provider.config_hint() or f'{provider_id} is not configured',
            })
            continue
        try:
            hits = provider.search_covers(q, limit=limit_per_provider)
        except ProviderDisabledError as exc:
            errors.append({'provider': provider_id, 'error': exc.message})
            continue
        except Exception as exc:  # noqa: BLE001 — surface per-provider failures
            errors.append({'provider': provider_id, 'error': str(exc)})
            continue
        for hit in hits:
            candidates.append(
                CoverCandidate(
                    provider=provider_id,
                    url=hit.url,
                    thumb_url=hit.thumb_url,
                    game_name=hit.game_name,
                    score=hit.score,
                    image_id=hit.id,
                )
            )

    return {
        'query': q,
        'candidates': [c.to_dict() for c in candidates],
        'errors': errors,
    }


def games_missing_cover_query(
    *,
    library_uuid: str | None = None,
    platform: str | None = None,
    service: str | None = None,
    missing_cover: bool = True,
    limit: int = 50,
):
    """Build a SQLAlchemy select for games matching mass-cover filters."""
    query = select(Game).options(joinedload(Game.library)).join(Library)
    if library_uuid:
        query = query.filter(Game.library_uuid == library_uuid)
    if platform:
        # Library.platform is an Enum — accept enum name or value string.
        from oneirodex.platform import LibraryPlatform

        plat = None
        for member in LibraryPlatform:
            if member.name.lower() == platform.lower() or member.value.lower() == platform.lower():
                plat = member
                break
        if plat is not None:
            query = query.filter(Library.platform == plat)
        else:
            query = query.filter(Library.platform == platform)
    if service:
        # Best-effort: match library name containing service label (Steam / GOG folders).
        query = query.filter(Library.name.ilike(f'%{service}%'))
    if missing_cover:
        has_cover = (
            select(Image.id)
            .where(
                Image.game_uuid == Game.uuid,
                Image.image_type == 'cover',
                Image.is_downloaded.is_(True),
            )
            .correlate(Game)
            .exists()
        )
        query = query.filter(~has_cover)
    return query.order_by(Game.name.asc()).limit(max(1, min(int(limit or 50), 200)))


def list_games_for_cover_batch(
    *,
    library_uuid: str | None = None,
    platform: str | None = None,
    service: str | None = None,
    missing_cover: bool = True,
    limit: int = 50,
) -> list[Game]:
    return list(
        db.session.execute(
            games_missing_cover_query(
                library_uuid=library_uuid,
                platform=platform,
                service=service,
                missing_cover=missing_cover,
                limit=limit,
            )
        ).scalars().unique().all()
    )


def apply_policy_to_game(
    game: Game,
    *,
    policy: str | None = None,
    limit_per_provider: int = 5,
    generate_fn: Callable[[Game], dict] | None = None,
    config=None,
) -> dict[str, Any]:
    """
    Apply cover selection policy to one game.

    Returns status dict with success/failure reason for queue/UI display.
    """
    steps = resolve_policy(policy)
    query = (game.name or '').strip()
    if not query:
        return {
            'game_uuid': game.uuid,
            'name': game.name,
            'status': 'failed',
            'error': 'Game has no name to search',
        }

    path_status = image_save_path_status(config)
    if not path_status.get('writable'):
        return {
            'game_uuid': game.uuid,
            'name': game.name,
            'status': 'failed',
            'error': path_status.get('error') or 'IMAGE_SAVE_PATH is not writable',
            'image_save_path': path_status,
        }

    last_error = None
    for step in steps:
        if step == 'generate':
            if generate_fn is None:
                last_error = 'Generate step requested but no generate_fn provided'
                continue
            try:
                result = generate_fn(game)
                return {
                    'game_uuid': game.uuid,
                    'name': game.name,
                    'status': 'applied',
                    'provider': 'generate',
                    'result': result,
                }
            except Exception as exc:  # noqa: BLE001
                last_error = f'Generate failed: {exc}'
                continue

        search = search_cover_candidates(
            query,
            providers=[step],
            limit_per_provider=limit_per_provider,
        )
        if search['errors'] and not search['candidates']:
            last_error = search['errors'][0].get('error') or f'{step} search failed'
            continue
        if not search['candidates']:
            last_error = f'No cover candidates from {step}'
            continue

        top = search['candidates'][0]
        try:
            applied = apply_cover_from_url(
                game.uuid,
                top['url'],
                provider_id=top['provider'],
                image_type='cover',
                config=config,
            )
            return {
                'game_uuid': game.uuid,
                'name': game.name,
                'status': 'applied',
                'provider': top['provider'],
                'url': top['url'],
                'result': applied,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = f'{step} apply failed: {exc}'
            continue

    return {
        'game_uuid': game.uuid,
        'name': game.name,
        'status': 'failed',
        'error': last_error or 'No provider in policy succeeded',
        'policy': list(steps),
    }


def batch_search_covers(
    *,
    library_uuid: str | None = None,
    platform: str | None = None,
    service: str | None = None,
    missing_cover: bool = True,
    limit_games: int = 25,
    providers: list[str] | None = None,
    limit_per_provider: int = 5,
    config=None,
) -> dict[str, Any]:
    games = list_games_for_cover_batch(
        library_uuid=library_uuid,
        platform=platform,
        service=service,
        missing_cover=missing_cover,
        limit=limit_games,
    )
    rows = []
    for game in games:
        search = search_cover_candidates(
            game.name or '',
            providers=providers,
            limit_per_provider=limit_per_provider,
        )
        rows.append({
            'game_uuid': game.uuid,
            'name': game.name,
            'library_uuid': game.library_uuid,
            'platform': (
                game.library.platform.value
                if game.library and game.library.platform
                else None
            ),
            'candidates': search['candidates'],
            'errors': search['errors'],
        })
    return {
        'count': len(rows),
        'games': rows,
        'image_save_path': image_save_path_status(config),
        'filters': {
            'library_uuid': library_uuid,
            'platform': platform,
            'service': service,
            'missing_cover': missing_cover,
        },
    }


def batch_apply_covers(
    *,
    game_uuids: list[str] | None = None,
    library_uuid: str | None = None,
    platform: str | None = None,
    service: str | None = None,
    missing_cover: bool = True,
    limit_games: int = 25,
    policy: str | None = None,
    generate_fn: Callable[[Game], dict] | None = None,
    config=None,
) -> dict[str, Any]:
    if game_uuids:
        games = list(
            db.session.execute(
                select(Game)
                .options(joinedload(Game.library))
                .filter(Game.uuid.in_(game_uuids))
            ).scalars().unique().all()
        )
    else:
        games = list_games_for_cover_batch(
            library_uuid=library_uuid,
            platform=platform,
            service=service,
            missing_cover=missing_cover,
            limit=limit_games,
        )

    results = []
    applied = 0
    failed = 0
    for game in games:
        row = apply_policy_to_game(
            game, policy=policy, generate_fn=generate_fn, config=config,
        )
        results.append(row)
        if row.get('status') == 'applied':
            applied += 1
        else:
            failed += 1

    return {
        'applied': applied,
        'failed': failed,
        'results': results,
        'policy': list(resolve_policy(policy)),
        'image_save_path': image_save_path_status(config),
    }
