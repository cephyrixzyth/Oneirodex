"""Framework-independent payload projections shared by Discover routes."""
from __future__ import annotations

from oneirodex.utils.cover_url import resolve_game_cover_url
from oneirodex.utils.functions import format_size
from oneirodex.utils.game_details_payload import browse_trailer_fields
from oneirodex.utils.lifecycle import web_lifecycle_fields
from oneirodex.utils.play_url import browse_play_fields, library_platform_key
from oneirodex.utils.secondary_scrapers import game_card_flags
from oneirodex.utils.store_ownership import ownership_flags


def serialize_discover_game(
    game,
    cover_image,
    *,
    is_favorite,
    has_local_override,
    owned_game_uuids=None,
    user_id=None,
    client_state=None,
    client_connected=None,
    updates_count=None,
):
    """Shape one Discover tile without importing the route module."""
    cover_url = resolve_game_cover_url(game, cover_image)
    owned_uuids = owned_game_uuids or set()
    platform_key = library_platform_key(game)
    platform_label = None
    library = getattr(game, 'library', None)
    platform = getattr(library, 'platform', None) if library is not None else None
    if platform is not None:
        platform_label = getattr(platform, 'value', None) or platform_key

    return {
        'id': game.id,
        'uuid': game.uuid,
        'name': game.name,
        'cover_url': cover_url,
        'summary': game.summary,
        'url': game.url,
        'size': format_size(game.size),
        'genres': [genre.name for genre in game.genres],
        'is_favorite': is_favorite,
        'has_local_override': has_local_override,
        'date_identified': game.date_identified.isoformat() if game.date_identified else None,
        'date_created': game.date_created.isoformat() if game.date_created else None,
        'first_release_date': (
            game.first_release_date.isoformat()
            if game.first_release_date
            else None
        ),
        'freshness_status': getattr(game, 'freshness_status', None),
        'library_platform': platform_key,
        'library_platform_label': platform_label,
        'badge_title_collision': bool(platform_key),
        **browse_play_fields(game),
        **browse_trailer_fields(game),
        **game_card_flags(game),
        **web_lifecycle_fields(
            game,
            user_id=user_id,
            client_state=client_state,
            client_connected=client_connected,
            updates_count=updates_count,
        ),
        **ownership_flags(game.uuid, owned_uuids),
    }


__all__ = ['serialize_discover_game']
