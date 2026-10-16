"""Framework-neutral catalogue queries shared by Flask and native routes."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Library, Platform
from oneirodex.platform import mapped_core_ids, play_mode_for_platform
from oneirodex.utils.library_acl import (
    allowed_library_uuids,
    apply_game_access_filters,
    filter_libraries,
)
from oneirodex.utils.set_completion import completion_summaries_by_platform


def taxonomy_list(model_class: type[Any]) -> list[dict]:
    results = db.session.execute(select(model_class).order_by(model_class.name.asc())).scalars().all()
    return [{'id': item.id, 'name': item.name} for item in results]


def libraries_payload(user, *, fallback_image_url: str | None = None) -> list[dict]:
    libraries_query = filter_libraries(
        db.session.execute(select(Library).order_by(Library.name.asc())).scalars().all(),
        user,
    )
    return [
        {
            'uuid': lib.uuid,
            'name': lib.name,
            'image_url': lib.image_url or fallback_image_url or '/static/newstyle/default_library.jpg',
        }
        for lib in libraries_query
    ]


def library_platforms_payload(user, *, include_completion: bool = False) -> list[dict]:
    allowed = allowed_library_uuids(user)
    if allowed is not None and not allowed:
        return []

    accessible_games = apply_game_access_filters(select(Game.id, Game.library_uuid), user).subquery()
    query = (
        select(Library.platform, func.count(accessible_games.c.id))
        .select_from(Library)
        .outerjoin(accessible_games, accessible_games.c.library_uuid == Library.uuid)
        .group_by(Library.platform)
    )
    if allowed is not None:
        query = query.filter(Library.uuid.in_(list(allowed)))

    counts = {}
    for platform, game_count in db.session.execute(query).all():
        if platform is not None:
            counts[platform] = counts.get(platform, 0) + int(game_count or 0)

    completion_by_platform = completion_summaries_by_platform(user) if include_completion else {}
    data = []
    for platform, game_count in sorted(counts.items(), key=lambda item: item[0].value.lower()):
        name = platform.name
        row = {
            'id': name,
            'name': platform.value,
            'value': name,
            'game_count': game_count,
            'play_mode': play_mode_for_platform(name),
            'companion_cores': mapped_core_ids(name),
        }
        summary = completion_by_platform.get(name)
        if summary:
            regions = summary.get('regions') or []
            row['set_completion'] = {key: value for key, value in summary.items() if key != 'regions'}
            if regions:
                row['set_completion_regions'] = regions
        data.append(row)
    return data


def igdb_platforms_payload() -> list[dict]:
    results = db.session.execute(
        select(Platform)
        .join(Platform.games)
        .distinct()
        .order_by(Platform.name.asc())
    ).scalars().all()
    return [{'id': item.id, 'name': item.name} for item in results]


def ownership_store_options() -> list[dict]:
    """Stores the browse filter can answer using recorded ownership only."""
    from oneirodex.utils.store_capabilities import provider_capabilities
    from oneirodex.utils.store_ownership_common import is_ownership_sync_enabled, unofficial_store_opt_in

    return [
        {'id': provider['id'], 'name': provider['name']}
        for provider in provider_capabilities(
            enabled=is_ownership_sync_enabled(),
            unofficial_stores=unofficial_store_opt_in(),
        )
        if provider['capabilities']['store_filter'] == 'recorded_ownership'
        and provider['policy_enabled']
    ]
