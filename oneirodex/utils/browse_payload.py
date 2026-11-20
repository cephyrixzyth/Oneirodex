"""Row serialisation + response body for the ``/browse_games`` grid.

Split out of ``routes.browse_games`` alongside
:mod:`oneirodex.utils.browse_query`. :func:`build_browse_payload` produces the
exact dict the view used to hand ``jsonify`` — ``games`` / ``total`` / ``pages``
/ ``current_page`` — for both the populated and the empty-page paths.
"""

from __future__ import annotations

from oneirodex.utils.browse_query import BrowseQueryResult
from oneirodex.utils.cover_url import resolve_game_cover_url
from oneirodex.utils.functions import format_size
from oneirodex.utils.game_details_payload import browse_trailer_fields
from oneirodex.utils.game_editions import normalize_title
from oneirodex.utils.lifecycle import web_lifecycle_fields
from oneirodex.utils.local_metadata import has_local_images, has_local_metadata
from oneirodex.utils.play_url import browse_play_fields
from oneirodex.utils.rom_language import rom_browse_flags
from oneirodex.utils.secondary_scrapers import game_card_flags
from oneirodex.utils.store_ownership import ownership_flags


def serialize_browse_row(game, result: BrowseQueryResult) -> dict:
    """Serialise one ``Game`` row to its browse-grid dict.

    All per-page context (covers, statuses, edition platforms, ownership,
    lifecycle, …) comes from ``result``; see
    :class:`oneirodex.utils.browse_query.BrowseQueryResult`.
    """
    settings = result.settings
    cover_image = result.covers_by_uuid.get(game.uuid)
    cover_url = resolve_game_cover_url(game, cover_image)
    genres = [genre.name for genre in game.genres]
    game_size_formatted = format_size(game.size)

    has_local_override = False
    if settings:
        if (
            settings.use_local_metadata
            and has_local_metadata(
                game.full_disk_path,
                settings.local_metadata_filename or "oneirodex.json",
            )
        ) or (settings.use_local_images and has_local_images(game.full_disk_path)):
            has_local_override = True

    user_status = result.user_statuses.get(game.uuid)

    library_platform_key = None
    library_platform_label = None
    if game.library is not None and game.library.platform is not None:
        platform = game.library.platform
        library_platform_key = getattr(platform, "name", None) or str(platform)
        library_platform_label = (
            getattr(platform, "value", None) or library_platform_key
        )

    edition_platforms = result.edition_platforms_by_key.get(
        normalize_title(game.name) or '#' + str(game.uuid)
    ) or ([library_platform_key] if library_platform_key else [])

    steam_app_id = getattr(game, "steam_app_id", None)
    steam_url = getattr(game, "steam_url", None) or None
    if steam_app_id and not steam_url:
        steam_url = f"https://store.steampowered.com/app/{int(steam_app_id)}"

    return {
        "id": game.id,
        "uuid": game.uuid,
        "name": game.name,
        "cover_url": cover_url,
        "summary": game.summary,
        "url": game.url,
        "size": game_size_formatted,
        "genres": genres,
        "library_uuid": game.library_uuid,
        "library_platform": library_platform_key,
        "library_platform_label": library_platform_label,
        "is_favorite": game.uuid in result.favorite_uuids,
        # This member's newest save state, or None. The tile says "Resume"
        # and hands the slot to the play shell, which then asks rather than
        # silently loading it.
        "resume_state": result.resume_by_uuid.get(game.uuid),
        "date_identified": game.date_identified.isoformat()
        if game.date_identified
        else None,
        "date_created": game.date_created.isoformat() if game.date_created else None,
        "first_release_date": game.first_release_date.isoformat()
        if game.first_release_date
        else None,
        "has_local_override": has_local_override,
        "user_status": user_status,
        "freshness_status": game.freshness_status,
        "freshness_confidence": game.freshness_confidence,
        "local_version": game.local_version,
        "steam_app_id": steam_app_id,
        "steam_url": steam_url,
        "badge_title_collision": bool(library_platform_key),
        # Newest hardware first, so the client reads element 0 as "the
        # latest system this was released on" and never has to rank
        # anything itself. Always includes this row's own system, so the
        # count is systems-for-the-title, not systems-besides-this-one.
        "edition_platforms": edition_platforms,
        "edition_count": len(edition_platforms),
        **browse_play_fields(game),
        **browse_trailer_fields(game),
        **game_card_flags(game),
        **rom_browse_flags(
            game,
            result.preferred_locale,
            has_translation_patch=game.uuid in result.patch_game_uuids,
        ),
        **web_lifecycle_fields(
            game,
            updates_count=result.update_counts.get(game.uuid, 0),
            user_id=result.current_user_id,
            client_connected=result.client_connected,
            client_state=result.lifecycle_map.get(game.uuid),
        ),
        **ownership_flags(game.uuid, result.owned_game_uuids),
    }


def build_browse_payload(result: BrowseQueryResult) -> dict:
    """Build the ``/browse_games`` response body from a query result.

    Identical shape for a populated page and a guaranteed-empty one
    (``BrowseQueryResult.empty``): ``{games, total, pages, current_page}``.
    """
    return {
        "games": [serialize_browse_row(game, result) for game in result.games],
        "total": result.total,
        "pages": result.pages,
        "current_page": result.page,
    }
