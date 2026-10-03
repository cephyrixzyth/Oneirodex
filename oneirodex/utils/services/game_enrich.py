"""Steam + metadata-cascade enrichment, post-identify enrichment worker.

Bodies moved verbatim from ``oneirodex/utils/game_core.py`` in wave A2.3.
"""
import threading
from oneirodex import db
from sqlalchemy import select
from flask import current_app
from oneirodex.models import Game, Genre, GameMode, PlayerPerspective
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.metadata_enrichment import apply_enriched_metadata
from oneirodex.utils.secondary_scrapers import (
    fetch_steam_data, game_indicates_vr, normalize_perspective_name, VR_PERSPECTIVE_NAME
)
from oneirodex.utils.helpers.fs import get_folder_size_in_bytes_updates, format_size
from oneirodex.utils.services.entities import get_or_create_entity
from oneirodex.utils.services.image_pipeline import smart_process_images_for_game
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "enrich_game_with_steam",
    "_game_core_fields_missing",
    "enrich_game_all_sources",
    "queue_post_identify_enrichment",
]


def enrich_game_with_steam(game, lookup_name=None):
    """Backfill Steam store metadata onto a Game instance.

    Attaches summary (when missing), VR/player perspectives, genres, and
    GameMode rows mapped from Steam categories. Steam freeform tags have no
    Game column and are skipped. Never queues DRM downloads.

    The Steam HTTP lookup happens first and touches no DB state; the
    resulting metadata is then attached inside a SQLAlchemy savepoint
    (see `apply_enriched_metadata`) so a failure while attaching it
    cannot poison the caller's larger create/scan transaction.
    """
    name = lookup_name or getattr(game, 'name', None)
    if not name:
        result = {
            'applied': False,
            'is_vr': False,
            'perspectives_added': [],
            'genres_added': [],
            'game_modes_added': [],
            'reason': 'no_name',
        }
        logger.warning("Steam enrichment skipped (no_name); Steam VR: no")
        return result

    # A game already flagged VR used to short-circuit here, which also skipped the
    # summary/genre/mode backfill — VR detection is only one part of this pass.
    already_vr = game_indicates_vr(game)

    steam_data = fetch_steam_data(name)
    if not steam_data:
        result = {
            'applied': False,
            'is_vr': already_vr,
            'perspectives_added': [],
            'genres_added': [],
            'game_modes_added': [],
            'reason': 'no_steam_data',
        }
        logger.warning(f"Steam enrichment for '{name}': skipped (no_steam_data); Steam VR: no")
        return result

    is_vr = bool(steam_data.get('is_vr'))
    existing_names = {
        normalize_perspective_name(getattr(p, 'name', '') or '')
        for p in (game.player_perspectives or [])
    }
    perspective_names = [
        normalize_perspective_name(n)
        for n in (steam_data.get('player_perspectives') or [])
    ]
    new_names = [name_ for name_ in perspective_names if name_ and name_ not in existing_names]

    existing_genres = {
        (getattr(g, 'name', '') or '').strip().lower()
        for g in (getattr(game, 'genres', None) or [])
    }
    new_genres = [
        g.strip()
        for g in (steam_data.get('genres') or [])
        if g and g.strip() and g.strip().lower() not in existing_genres
    ]

    existing_modes = {
        (getattr(m, 'name', '') or '').strip().lower()
        for m in (getattr(game, 'game_modes', None) or [])
    }
    new_modes = [
        m.strip()
        for m in (steam_data.get('game_modes') or [])
        if m and m.strip() and m.strip().lower() not in existing_modes
    ]

    enriched = {
        'summary': steam_data.get('summary'),
        'player_perspectives': new_names,
        'genres': new_genres,
        'game_modes': new_modes,
    }
    applied_ok = apply_enriched_metadata(
        game,
        enriched,
        perspective_factory=lambda persp_name: get_or_create_entity(PlayerPerspective, name=persp_name),
        genre_factory=lambda genre_name: get_or_create_entity(Genre, name=genre_name),
        game_mode_factory=lambda mode_name: get_or_create_entity(GameMode, name=mode_name),
    )
    perspectives_added = new_names if applied_ok else []
    genres_added = new_genres if applied_ok else []
    modes_added = new_modes if applied_ok else []
    reason = None if applied_ok else 'enrichment_savepoint_rollback'

    # Scalar store fields the relation-oriented enrichment above does not cover:
    # developer, publisher, release date and App ID were previously dropped, so
    # even a successfully enriched game showed blank credits.
    if applied_ok:
        try:
            from oneirodex.utils.steam_metadata import (
                apply_steam_metadata_to_game,
                parse_steam_release_date,
            )

            apply_steam_metadata_to_game(game, {
                'developer': steam_data.get('developer'),
                'publisher': steam_data.get('publisher'),
                'first_release_date': parse_steam_release_date(steam_data.get('release_date')),
                'cover_url': steam_data.get('cover_url'),
                'steam_app_id': steam_data.get('steam_app_id'),
            })
        except Exception as scalar_err:  # noqa: BLE001
            logger.warning(f"Steam scalar backfill skipped for '{name}': {scalar_err}")

    result = {
        'applied': applied_ok,
        'is_vr': is_vr or VR_PERSPECTIVE_NAME in perspectives_added or game_indicates_vr(game),
        'perspectives_added': perspectives_added,
        'genres_added': genres_added,
        'game_modes_added': modes_added,
        'reason': reason,
        'steam_app_id': steam_data.get('steam_app_id'),
    }
    vr_label = 'yes' if result['is_vr'] else 'no'
    app_id = result.get('steam_app_id')
    app_txt = f"; steam_app_id={app_id}" if app_id else ''
    if applied_ok:
        added_txt = ', '.join(perspectives_added) if perspectives_added else 'none'
        genre_txt = ', '.join(genres_added) if genres_added else 'none'
        logger.info(
            f"Steam enrichment for '{name}': Steam VR: {vr_label}; "
            f"perspectives_added=[{added_txt}]; genres_added=[{genre_txt}]{app_txt}"
        )
    else:
        logger.info(
            f"Steam enrichment for '{name}': skipped ({reason}); Steam VR: {vr_label}"
        )
    return result


def _game_core_fields_missing(game):
    """True while the fields a library page actually shows are still blank."""
    if not (getattr(game, 'summary', None) or '').strip():
        return True
    if not (getattr(game, 'genres', None) or []):
        return True
    if getattr(game, 'developer_id', None) is None:
        return True
    return False


def enrich_game_all_sources(game, lookup_name=None):
    """Fill a newly identified game from every source, not just Steam.

    ``enrich_game_with_steam`` was the whole of what a scanned title received,
    and it answers for exactly one store. That is fine for a PC library and
    useless everywhere else: a SNES ROM is not on Steam, so every console row
    landed with ``no_steam_data`` — blank summary, no genres, no developer —
    even though searches for TheGamesDB, MobyGames, Giant Bomb and RAWG already
    existed. They were reachable from *manual* identify only.

    So: Steam first, but only where a title could plausibly be on it, then
    :func:`~oneirodex.utils.metadata_cascade.hydrate_game_from_cascade` for the
    rest. Steam is skipped in the cascade because the pass above already asked
    it, and asks for more than the cascade does (VR perspectives, game modes).

    The cascade runs inside a SAVEPOINT for the same reason the Steam pass does:
    a metadata miss must never roll back the import that triggered it.

    Returns the Steam result dict, plus a ``cascade`` key holding the walk's
    trace (``None`` when the title was already complete).
    """
    from oneirodex.utils.metadata_cascade import PC_PLATFORMS, hydrate_game_from_cascade

    name = lookup_name or getattr(game, 'name', None)
    platform = getattr(getattr(game, 'library', None), 'platform', None)
    platform_name = getattr(platform, 'name', platform)
    key = str(platform_name or '').strip().upper()

    # No platform recorded means we cannot rule Steam out, so we still ask.
    if not key or key in PC_PLATFORMS:
        result = enrich_game_with_steam(game, lookup_name=name)
    else:
        result = {
            'applied': False,
            'is_vr': game_indicates_vr(game),
            'perspectives_added': [],
            'genres_added': [],
            'game_modes_added': [],
            'reason': 'platform_not_on_steam',
        }
        logger.warning(f"Steam enrichment for '{name}': skipped (platform_not_on_steam)")

    # Steam is the one source that returns everything we show (credits, release
    # date, modes, system requirements, cover). The name-based pass above only
    # ever added a few taxonomy rows, so an IGDB-identified game with a Steam
    # App ID -- from a folder id, an earlier pass, or a hand-picked match -- now
    # gets the full appdetails mapping by id, which is exact, not a name guess.
    # Fill-don't-clobber: IGDB values are never overwritten.
    if getattr(game, 'steam_app_id', None):
        try:
            from oneirodex.utils.software_identify_custom_game import hydrate_steam_for_game

            result['steam_full'] = bool(hydrate_steam_for_game(game, game.steam_app_id))
        except Exception as steam_full_err:  # noqa: BLE001
            logger.info(f"Full Steam hydrate skipped for '{name}': {steam_full_err}")

    result['cascade'] = None
    if not _game_core_fields_missing(game):
        return result

    try:
        with db.session.begin_nested():
            outcome = hydrate_game_from_cascade(
                game,
                name=name,
                library_platform=platform_name,
                skip=('steam',),
            )
        result['cascade'] = outcome.get('trace')
        trace = outcome.get('trace') or {}
        contributed = ', '.join(trace.get('contributed') or []) or 'none'
        logger.info(
            f"Cascade enrichment for '{name}': "
            f"queried=[{', '.join(trace.get('queried') or []) or 'none'}]; "
            f"contributed=[{contributed}]"
        )
    except Exception as cascade_err:  # noqa: BLE001
        logger.info(f"Cascade enrichment savepoint rollback for '{name}': {cascade_err}")

    return result


def queue_post_identify_enrichment(
    game_uuid,
    *,
    fetch_hltb=False,
    cover_data=None,
    screenshots_data=None,
    app=None,
    run_inline=False,
    compute_folder_size=True,
):
    """Run Steam / image / HLTB / folder-size work after the Game row is committed.

    Scan workers call this with run_inline=False so identify returns quickly.
    Tests can pass run_inline=True.
    """
    if app is None:
        app = current_app._get_current_object()

    def _worker():
        with app.app_context():
            try:
                game = db.session.execute(
                    select(Game).filter_by(uuid=game_uuid)
                ).scalar_one_or_none()
                if not game:
                    return

                if compute_folder_size and game.full_disk_path:
                    try:
                        size_bytes = get_folder_size_in_bytes_updates(game.full_disk_path)
                        game.size = size_bytes
                        db.session.commit()
                        logger.info(
                            f"Deferred folder size for {game.name}: {format_size(size_bytes)}"
                        )
                    except Exception as size_err:  # noqa: BLE001
                        logger.info(f"Deferred folder size failed for {game_uuid}: {size_err}")
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                        game = db.session.execute(
                            select(Game).filter_by(uuid=game_uuid)
                        ).scalar_one_or_none()
                        if not game:
                            return

                try:
                    enrich_game_all_sources(game, lookup_name=game.name)
                    db.session.commit()
                except Exception as steam_err:  # noqa: BLE001
                    logger.info(f"Deferred metadata enrichment failed for {game_uuid}: {steam_err}")
                    try:
                        db.session.rollback()
                    except Exception:
                        pass

                try:
                    smart_process_images_for_game(
                        game_uuid,
                        cover_data=cover_data,
                        screenshots_data=screenshots_data,
                        app=app,
                        download_immediately=True,
                    )
                except Exception as img_err:  # noqa: BLE001
                    logger.info(f"Deferred image processing failed for {game_uuid}: {img_err}")

                if fetch_hltb:
                    settings = global_settings_row()
                    if settings and settings.enable_hltb_integration:
                        try:
                            from oneirodex.utils.hltb import update_game_hltb_sync

                            update_game_hltb_sync(game_uuid, game.name)
                        except Exception as hltb_err:  # noqa: BLE001
                            logger.info(f"Deferred HLTB failed for {game_uuid}: {hltb_err}")
            except Exception as enrich_err:  # noqa: BLE001
                logger.info(f"Post-identify enrichment failed for {game_uuid}: {enrich_err}")
                try:
                    db.session.rollback()
                except Exception:
                    pass

    if run_inline:
        _worker()
        return None

    thread = threading.Thread(
        target=_worker,
        daemon=True,
        name=f'enrich-{str(game_uuid)[:8]}',
    )
    thread.start()
    return thread
