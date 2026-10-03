"""``retrieve_and_save_game`` (scan identify god-function) + its collaborators.

Bodies moved verbatim from ``oneirodex/utils/game_core.py`` in wave A2.3.
The implicit module-global ``settings`` written by ``create_game_instance``
(``global settings``) lives here, exactly as it did in game_core.
"""
from datetime import datetime, UTC
from flask import flash, current_app, abort, has_request_context
import os, uuid
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from oneirodex import db
from oneirodex.models import (
    Game, Image, Library, GlobalSettings,
    Developer, Publisher, Genre, Theme, GameMode, Platform,
    PlayerPerspective, GameURL, ScanJob, Category, Status,
    game_developer_association
)
from oneirodex.utils.licensed_catalog import upsert_releases_from_igdb_payload
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.helpers.fs import (
    read_first_nfo_content, get_folder_size_in_bytes_updates, format_size,
)
from oneirodex.utils.helpers.counts import delete_associations_for_game
from oneirodex.utils.helpers.urls import website_category_to_string
from oneirodex.utils.helpers.platforms import igdb_platform_id_for
from oneirodex.utils.clients.images import (
    download_image, download_stored_image, cover_title_for_uuid,
)
from oneirodex.utils.clients.igdb import (
    search_igdb_for_game, fetch_game_by_igdb_id, fetch_and_store_game_urls,
)
from oneirodex.utils.igdb_api import make_igdb_api_request
from oneirodex.utils.gamenames import generate_goty_variants
from oneirodex.utils.fandom_alias import (
    fandom_match_reason,
    fandom_suggested_kind,
    is_fandom_soft_propose,
)
from oneirodex.utils.match_scoring import select_best_match, rank_candidates
from oneirodex.utils.match_proposal import (
    MATCH_REASON_CATALOG_DISAGREEMENT,
    MATCH_REASON_INSUFFICIENT_AGREEMENT,
    build_match_proposal,
    write_match_proposal,
)
from oneirodex.utils.game_name_parse import parse_game_label, detect_update_packaging, looks_like_patch_package
from oneirodex.utils.image_kinds import IGDB_DOWNLOAD_KINDS
from oneirodex.utils.rom_name_peel import (
    parse_console_rom_label,
    should_arcade_propose_first,
    should_use_console_rom_peel,
)
from oneirodex.utils.scan_match_settings import resolve_scan_match_policy
from oneirodex.utils.metadata_providers import stage_d_source_ids
from oneirodex.utils.software_identify import (
    agreement_count,
    agreement_satisfied,
    apply_catalog_identity_to_game,
    corroborate_igdb_with_catalogs,
    igdb_retry_title_from_store,
    resolve_stage_d_store_candidate,
    try_stage_d_store_identify,
)
from oneirodex.utils.steam_lookup import fetch_steam_title_by_app_id
from oneirodex.utils.secondary_scrapers import (
    fetch_steam_data, game_indicates_vr, normalize_perspective_name, VR_PERSPECTIVE_NAME
)
from oneirodex.utils.metadata_enrichment import apply_enriched_metadata
from oneirodex.utils.notifications import notify_admins_new_game
from oneirodex.utils.scanning import log_unmatched_folder, delete_game_images
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.duplicate_check import (
    explain_duplicate_match,
    normalize_rom_region,
    same_duplicate_scope,
    should_mark_as_duplicate,
)

# Sentinel: IGDB id is taken by another system/region — caller should import
# without the unique igdb_id/slug (title-group browse still pairs the editions).
IMPORT_CROSS_SYSTEM_EDITION = 'import_cross_system_edition'
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from oneirodex.utils.worker_caps import (
    clamp_image_download_batch,
    clamp_image_download_threads,
    cooperative_yield,
)
from oneirodex.utils.services.igdb_maps import category_mapping, status_mapping
from oneirodex.utils.services.entities import get_or_create_entity
from oneirodex.utils.services.game_lookup import (
    check_existing_game_by_path, check_existing_game_by_igdb_id,
)
from oneirodex.utils.services.game_enrich import (
    enrich_game_with_steam, enrich_game_all_sources, queue_post_identify_enrichment,
)
from oneirodex.utils.services.image_pipeline import (
    store_image_url_for_download, smart_process_images_for_game, process_and_save_image,
)
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "handle_existing_igdb_collision",
    "is_propose_only_scan",
    "attach_igdb_taxonomy_to_game",
    "ensure_manual_identify_taxonomy",
    "create_game_instance",
    "enumerate_companies",
    "retrieve_and_save_game",
]


def _peel_rom_region(peel) -> str | None:
    if not isinstance(peel, dict):
        return None
    return normalize_rom_region(peel.get('rom_region'))


def handle_existing_igdb_collision(
    *,
    existing_game,
    igdb_id,
    full_disk_path,
    game_name,
    scan_job_id,
    library_uuid,
    candidates=None,
    steam_title=None,
    match_policy=None,
    peel=None,
    library=None,
):
    """
    Same IGDB ID already in library. Mark Duplicate only for true title/path
    copies on the **same system + region**; otherwise Unmatched + proposal so
    remasters/collections can be reviewed.

    Cross-system (or different known ROM region) collisions return
    ``IMPORT_CROSS_SYSTEM_EDITION`` so the caller can import a separate Game
    without the unique igdb_id/slug — browse title-grouping pairs the editions.

    BE-DET-5: when both sides are clear multi-disc siblings (same cleaned title,
    different disc index), attach the new path as a disc GameExtra and return
    the existing Game (no second Game, no Duplicate trail).

    Returns existing Game on multi-disc attach; IMPORT_CROSS_SYSTEM_EDITION when
    the caller should import without IGDB id; None when caller should abort.
    """
    scan_library = library
    if scan_library is None and library_uuid:
        scan_library = db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalar_one_or_none()
    new_region = _peel_rom_region(peel)
    if new_region is None:
        from oneirodex.utils.rom_language import parse_rom_language_tags

        new_region = normalize_rom_region(
            parse_rom_language_tags(full_disk_path or game_name).get('rom_region')
        )

    if not same_duplicate_scope(
        existing_game,
        new_platform=getattr(scan_library, 'platform', None),
        new_library_uuid=library_uuid,
        new_rom_region=new_region,
    ):
        logger.info(
            f"IGDB ID {igdb_id} already used by '{existing_game.name}' "
            f"({existing_game.full_disk_path}) on another system/region — "
            f"importing '{game_name}' as a cross-system edition (no shared igdb_id)."
        )
        return IMPORT_CROSS_SYSTEM_EDITION

    # BE-DET-5 — clear multi-disc sibling → one Game + disc index (not N Games).
    try:
        from oneirodex.utils.multi_disc import try_attach_multi_disc_sibling

        if try_attach_multi_disc_sibling(
            existing_game=existing_game,
            full_disk_path=full_disk_path,
            game_name=game_name,
            peel=peel,
        ):
            logger.info(
                f"📀 [MULTI-DISC] Attached disc sibling for IGDB ID {igdb_id}: "
                f"'{game_name}' → existing '{existing_game.name}' "
                f"({existing_game.full_disk_path})"
            )
            return existing_game
    except Exception as multi_err:  # noqa: BLE001
        logger.warning(f"⚠️ Multi-disc attach skipped for {full_disk_path}: {multi_err}")

    policy = match_policy if isinstance(match_policy, dict) else resolve_scan_match_policy()
    dupe_thr = policy.get('dupe_title_threshold')
    scope_kwargs = {
        'new_platform': getattr(scan_library, 'platform', None),
        'new_library_uuid': library_uuid,
        'new_rom_region': new_region,
    }
    if should_mark_as_duplicate(
        existing_game,
        full_disk_path,
        game_name,
        title_threshold=dupe_thr,
        **scope_kwargs,
    ):
        match = explain_duplicate_match(
            existing_game,
            full_disk_path,
            game_name,
            title_threshold=dupe_thr,
            **scope_kwargs,
        )
        logger.info(
            f"Duplicate folder for IGDB ID {igdb_id}: "
            f"'{game_name}' ≈ existing '{existing_game.name}' "
            f"({existing_game.full_disk_path}) reason={match['match_reason']} "
            f"score={match['match_score']}"
        )
        log_unmatched_folder(
            scan_job_id,
            full_disk_path,
            'Duplicate',
            library_uuid=library_uuid,
            matched_game_uuid=match.get('matched_game_uuid'),
            match_reason=match.get('match_reason'),
            match_score=match.get('match_score'),
        )
        return None

    logger.info(
        f"IGDB ID {igdb_id} already used by '{existing_game.name}' "
        f"at {existing_game.full_disk_path}, but folder '{game_name}' looks different — "
        "logging Unmatched for review (not Duplicate)."
    )
    log_unmatched_folder(scan_job_id, full_disk_path, 'Unmatched', library_uuid=library_uuid)
    try:
        proposal = build_match_proposal(
            game_name,
            candidates or [{'id': igdb_id, 'name': existing_game.name}],
            steam_title=steam_title,
            confidence='low',
        )
        proposal['proposal']['already_in_library'] = {
            'uuid': existing_game.uuid,
            'name': existing_game.name,
            'path': existing_game.full_disk_path,
            'igdb_id': igdb_id,
            'reason': 'igdb_id_collision_different_folder_title',
        }
        if write_match_proposal(full_disk_path, proposal):
            try:
                from oneirodex.utils.match_proposal import sync_unmatched_kind_hint

                sync_unmatched_kind_hint(full_disk_path, proposal)
            except Exception:
                pass
    except Exception as proposal_err:
        logger.warning(f"⚠️ Failed to write collision proposal for {full_disk_path}: {proposal_err}")
    return None


def _strip_unique_igdb_identity(game_data: dict) -> dict:
    """Copy IGDB payload without unique igdb_id/slug so a cross-system edition can import."""
    payload = dict(game_data)
    payload.pop('id', None)
    payload.pop('slug', None)
    return payload


def is_propose_only_scan(settings):
    """
    Determine whether the propose-only scan setting is enabled.

    Accepts either a settings dict (as built/threaded through scan helpers)
    or a GlobalSettings SQLAlchemy instance. When enabled, the scanner must
    never auto-import a game — even on a high-confidence IGDB match — and
    should instead write a match proposal sidecar for admin review.
    """
    if not settings:
        return False
    if isinstance(settings, dict):
        return bool(settings.get('propose_only_scan'))
    return bool(getattr(settings, 'propose_only_scan', False))


def attach_igdb_taxonomy_to_game(game, igdb_payload):
    """Attach IGDB genres/themes/modes/platforms/perspectives with create-missing upsert.

    Same behavior as scan identify (`retrieve_and_save_game`): names not yet in
    the local taxonomy become new Genre/Theme/GameMode/Platform/PlayerPerspective
    rows via `get_or_create_entity`, then are linked to the game. Existing
    relations are preserved (union). Does not touch DRM binaries.
    """
    if not game or not isinstance(igdb_payload, dict):
        return {
            'genres': [],
            'themes': [],
            'game_modes': [],
            'platforms': [],
            'player_perspectives': [],
        }

    attached = {
        'genres': [],
        'themes': [],
        'game_modes': [],
        'platforms': [],
        'player_perspectives': [],
    }

    def _attach(key, model_class, relation_attr):
        entries = igdb_payload.get(key) or []
        relation = getattr(game, relation_attr)
        existing = {
            (getattr(e, 'name', '') or '').strip().lower()
            for e in (relation or [])
        }
        for entry in entries:
            if isinstance(entry, dict):
                raw_name = entry.get('name')
            else:
                raw_name = entry
            if not raw_name:
                continue
            name = str(raw_name).strip()
            if not name:
                continue
            lowered = name.lower()
            entity = get_or_create_entity(model_class, name=name)
            if lowered not in existing or entity not in relation:
                if entity not in relation:
                    relation.append(entity)
                existing.add(lowered)
                attached[key].append(name)

    _attach('genres', Genre, 'genres')
    _attach('themes', Theme, 'themes')
    _attach('game_modes', GameMode, 'game_modes')
    _attach('platforms', Platform, 'platforms')
    _attach('player_perspectives', PlayerPerspective, 'player_perspectives')
    return attached


def ensure_manual_identify_taxonomy(game, igdb_id):
    """Re-fetch IGDB by id and attach taxonomy on manual identify/apply.

    Closes the form-checkbox gap: names absent from the DB taxonomy are created
    instead of being silently dropped by the Identify UI. Custom-range ids
    (>= 2000000420) skip the IGDB round-trip. Returns the attach summary or None.
    """
    if game is None or igdb_id is None:
        return None
    try:
        numeric_id = int(igdb_id)
    except (TypeError, ValueError):
        return None
    if numeric_id >= 2000000420:
        return None

    response = fetch_game_by_igdb_id(numeric_id)
    if not response or not isinstance(response, list) or not response:
        return None
    return attach_igdb_taxonomy_to_game(game, response[0])


def create_game_instance(
    game_data,
    full_disk_path,
    folder_size_bytes,
    library_uuid,
    *,
    peel: dict | None = None,
):
    global settings
    settings = global_settings_row()
    new_game = None  # Initialize new_game to None
    
    try:
        if not isinstance(game_data, dict):
            raise ValueError("create_game_instance game_data is not a dictionary")

        # Fetch library details using library_uuid
        library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
        if not library:
            logger.warning(f"Library with UUID {library_uuid} not found.")
            return None

        category_id = game_data.get('category')
        category_enum = category_mapping.get(category_id, None)
        status_id = game_data.get('status')
        status_enum = status_mapping.get(status_id, None)
        if 'videos' in game_data:
            video_urls = [f"https://www.youtube.com/watch?v={video['video_id']}" for video in game_data['videos']]
            videos_comma_separated = ','.join(video_urls)
        else:
            videos_comma_separated = ""
            
        logger.info(f"create_game_instance Creating game instance for '{game_data.get('name')}' with UUID: {game_data.get('id')} in library '{library.name}' on platform '{library.platform.name}'.")
        igdb_id = game_data.get('id')
        # Cross-system editions import without igdb_id/slug — both columns are unique.
        slug = game_data.get('slug') if igdb_id is not None else None
        new_game = Game(
            library_uuid=library_uuid,
            igdb_id=igdb_id,
            name=game_data['name'],
            summary=game_data.get('summary'),
            storyline=game_data.get('storyline'),
            url=game_data.get('url'),
            first_release_date=datetime.fromtimestamp(game_data.get('first_release_date', 0), UTC) if game_data.get('first_release_date') else None,
            aggregated_rating=game_data.get('aggregated_rating'),
            aggregated_rating_count=game_data.get('aggregated_rating_count'),
            rating=game_data.get('rating'),
            rating_count=game_data.get('rating_count'),
            slug=slug,
            status=status_enum,
            category=category_enum,
            total_rating=game_data.get('total_rating'),
            total_rating_count=game_data.get('total_rating_count'),
            video_urls=videos_comma_separated,
            full_disk_path=full_disk_path,
            size=folder_size_bytes,
            date_created=datetime.now(UTC),
            date_identified=datetime.now(UTC),
            steam_url='',
            times_downloaded=0
        )
        from oneirodex.utils.library_health import mark_game_path_ok

        mark_game_path_ok(new_game)

        db.session.add(new_game)
        db.session.flush()
        try:
            from oneirodex.utils.rom_hash import apply_file_hashes_to_game

            apply_file_hashes_to_game(new_game, full_disk_path)
        except Exception as hash_err:  # noqa: BLE001 — hashing must not fail the scan
            logger.warning(f"create_game_instance ROM hash skipped for '{new_game.name}': {hash_err}")
        try:
            from oneirodex.utils.rom_language import apply_rom_language_fields

            apply_rom_language_fields(
                new_game,
                full_disk_path or new_game.name,
                peel=peel,
            )
        except Exception as lang_err:  # noqa: BLE001
            logger.warning(f"create_game_instance ROM language parse skipped: {lang_err}")
        try:
            from oneirodex.utils.multi_disc import apply_disc_fields

            apply_disc_fields(
                new_game,
                full_disk_path or new_game.name,
                peel=peel,
            )
        except Exception as disc_err:  # noqa: BLE001
            logger.warning(f"create_game_instance disc index parse skipped: {disc_err}")
        try:
            platform_key = getattr(library.platform, 'name', None)
            upsert_releases_from_igdb_payload(platform_key or '', game_data)
        except Exception as catalog_err:  # noqa: BLE001 — cache must not fail the scan
            logger.warning(f"create_game_instance licensed catalog cache skipped: {catalog_err}")
        if igdb_id is not None:
            fetch_and_store_game_urls(new_game.uuid, igdb_id)
        logger.info(f"create_game_instance Finished processing game '{new_game.name}'. URLs (if any) have been fetched and stored.")
        
    except Exception as e:
        game_name = game_data.get('name') if isinstance(game_data, dict) else str(game_data)
        logger.error(f"create_game_instance Error during the game instance creation or URL fetching for game '{game_name}'. Error: {e}")
    
    return new_game


def enumerate_companies(game_instance, igdb_game_id, involved_company_ids):
    if not involved_company_ids:
        logger.info("No company IDs provided for enumeration.")
        return

    company_ids_str = ','.join(map(str, involved_company_ids))
    # print(f"Company IDs: {company_ids_str}")

    try:
        response_json = make_igdb_api_request(
            "https://api.igdb.com/v4/involved_companies",
            f"""fields company.name, developer, publisher, game;
                where game={igdb_game_id} & id=({company_ids_str});"""
        )

        if not isinstance(response_json, list):
            logger.info(f"Unexpected response structure: {response_json}")
            return

        for company_data in response_json:
            company_info = company_data.get('company')
            if not isinstance(company_info, dict) or 'name' not in company_info:
                logger.info(f"Unexpected company data structure or missing name: {company_data}")
                continue  # Skip to the next

            company_name = company_info['name'][:50] 
            is_developer = company_data.get('developer', False)
            is_publisher = company_data.get('publisher', False)

            if is_developer:
                # print(f"Company {company_name} is a developer.")
                developer = get_or_create_entity(Developer, name=company_name)

                game_instance.developer = developer

            if is_publisher:
                # print(f"Company {company_name} is a publisher.")
                publisher = get_or_create_entity(Publisher, name=company_name)
                game_instance.publisher = publisher
    except Exception as e:
        logger.error(f"Failed to enumerate companies due to an error: {e}")
        return

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to enumerate companies due to a database error: {e}")


def retrieve_and_save_game(
    game_name,
    full_disk_path,
    scan_job_id=None,
    library_uuid=None,
    fetch_hltb=False,
    settings=None,
    defer_enrichment=None,
):
    # print(f"retrieve_and_save_game Retrieving and saving game: {game_name} on {full_disk_path} to library with UUID {library_uuid}.")
    from oneirodex.utils.local_metadata import read_local_metadata
    from oneirodex.utils.event_logging import log_system_event
    from flask import flash

    # Scan workers pass scan_job_id — defer Steam/images/HLTB so identify commits fast.
    if defer_enrichment is None:
        defer_enrichment = scan_job_id is not None

    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
    if not library:
        logger.warning(f"retrieve_and_save_game Library with UUID {library_uuid} not found.")
        return None


    existing_game_by_path = check_existing_game_by_path(full_disk_path)
    if existing_game_by_path:
        return existing_game_by_path

    # Load settings once if not provided
    # Settings can be either a dict (from threaded scan) or a SQLAlchemy object
    if settings is None:
        settings_obj = global_settings_row()
        # Convert to dict for consistent handling
        settings = {
            'use_local_metadata': settings_obj.use_local_metadata if settings_obj else False,
            'write_local_metadata': settings_obj.write_local_metadata if settings_obj else False,
            'use_local_images': settings_obj.use_local_images if settings_obj else False,
            'local_metadata_filename': settings_obj.local_metadata_filename if settings_obj else 'oneirodex.json',
            'propose_only_scan': settings_obj.propose_only_scan if settings_obj else False,
        }
        match_policy = resolve_scan_match_policy(settings_obj)
    elif not isinstance(settings, dict):
        # If it's a SQLAlchemy object, convert to dict
        match_policy = resolve_scan_match_policy(settings)
        settings = {
            'use_local_metadata': settings.use_local_metadata,
            'write_local_metadata': settings.write_local_metadata,
            'use_local_images': settings.use_local_images,
            'local_metadata_filename': settings.local_metadata_filename or 'oneirodex.json',
            'propose_only_scan': getattr(settings, 'propose_only_scan', False),
        }
    else:
        match_policy = resolve_scan_match_policy(settings)

    settings['propose_only_scan'] = bool(
        settings.get('propose_only_scan') or match_policy.get('propose_only_scan')
    )

    # PRIORITY 1: Check for local metadata file (NEW!)
    if settings and settings.get('use_local_metadata'):
        logger.info(f"🔍 [LOCAL METADATA] Checking for existing metadata file in: {full_disk_path}")
        local_metadata = read_local_metadata(full_disk_path,
                                             settings.get('local_metadata_filename', 'oneirodex.json'))
        if local_metadata and 'igdb_id' in local_metadata:
            igdb_id = local_metadata['igdb_id']
            logger.info(f"✅ LOCAL METADATA: Found IGDB ID {igdb_id} in {full_disk_path}")

            # Fetch game data directly by IGDB ID
            response_json = fetch_game_by_igdb_id(igdb_id)

            if response_json and 'error' not in response_json and len(response_json) > 0:
                logger.info(f"✅ Successfully fetched game from local metadata: {response_json[0].get('name')}")

                # Check for duplicate (eager-load library for collision scope)
                existing_game_with_same_igdb_id = db.session.execute(
                    select(Game)
                    .options(joinedload(Game.library))
                    .filter(Game.igdb_id == igdb_id, Game.full_disk_path != full_disk_path)
                ).scalar_one_or_none()

                game_payload = response_json[0]
                if existing_game_with_same_igdb_id:
                    collision = handle_existing_igdb_collision(
                        existing_game=existing_game_with_same_igdb_id,
                        igdb_id=igdb_id,
                        full_disk_path=full_disk_path,
                        game_name=game_name,
                        scan_job_id=scan_job_id,
                        library_uuid=library_uuid,
                        candidates=response_json,
                        match_policy=match_policy,
                        peel=None,
                        library=library,
                    )
                    if collision is not IMPORT_CROSS_SYSTEM_EDITION:
                        return collision
                    game_payload = _strip_unique_igdb_identity(game_payload)

                # Create game from IGDB data (continue with existing logic at line 472)
                nfo_content = read_first_nfo_content(full_disk_path)
                # Scan path: defer full tree walk — large NAS/Unraid folders block identify for minutes.
                if defer_enrichment:
                    folder_size_bytes = 0
                    logger.info(f"Deferring folder size walk for scan identify: {full_disk_path}")
                else:
                    folder_size_bytes = get_folder_size_in_bytes_updates(full_disk_path)
                    logger.info(f"Folder size for {full_disk_path}: {format_size(folder_size_bytes)}")
                new_game = create_game_instance(
                    game_data=game_payload,
                    full_disk_path=full_disk_path,
                    folder_size_bytes=folder_size_bytes,
                    library_uuid=library.uuid
                )

                if new_game is None:
                    logger.warning(f"Failed to create game instance from local metadata for {game_name}. Skipping further processing.")
                    return None

                attach_igdb_taxonomy_to_game(new_game, response_json[0])

                if 'involved_companies' in response_json[0]:
                    involved_company_ids = response_json[0]['involved_companies']
                    if involved_company_ids and new_game.igdb_id is not None:
                        enumerate_companies(new_game, new_game.igdb_id, involved_company_ids)
                    else:
                        logger.info("No involved companies found for game from local metadata.")

                if not defer_enrichment:
                    enrich_game_all_sources(new_game, lookup_name=new_game.name)

                if 'videos' in response_json[0]:
                    video_urls = [f"https://www.youtube.com/embed/{video['video_id']}" for video in response_json[0]['videos']]
                    videos_comma_separated = ','.join(video_urls)
                    new_game.video_urls = videos_comma_separated

                db.session.commit()
                logger.info(f"Processing images for game: {new_game.name}")
                # Use smart image processing — pass expanded cover/screenshot
                # objects when present so store can reuse URLs without a second
                # IGDB round-trip (bare ids still work).
                cover_data = response_json[0].get('cover')
                screenshots_data = response_json[0].get('screenshots') or []
                if defer_enrichment:
                    queue_post_identify_enrichment(
                        new_game.uuid,
                        fetch_hltb=fetch_hltb,
                        cover_data=cover_data,
                        screenshots_data=screenshots_data,
                    )
                else:
                    smart_process_images_for_game(new_game.uuid, cover_data, screenshots_data)

                    if fetch_hltb:
                        # Fetch HLTB data if requested
                        from oneirodex.utils.hltb import update_game_hltb_sync
                        update_game_hltb_sync(new_game.uuid, new_game.name)

                # Now write the metadata file if setting is enabled
                if settings and settings.get('write_local_metadata'):
                    logger.info(f"💾 [LOCAL METADATA] Writing metadata file for '{new_game.name}' (from existing local metadata)")
                    from oneirodex.utils.local_metadata import write_local_metadata
                    write_success = write_local_metadata(
                        full_disk_path=full_disk_path,
                        igdb_id=igdb_id,
                        game_title=new_game.name,
                        manually_verified=True,
                        filename=settings.get('local_metadata_filename', 'oneirodex.json')
                    )
                    if not write_success:
                        logger.warning("⚠️ [LOCAL METADATA] Failed to write metadata file (already exists or permission issue)")

                return new_game
            else:
                # Failed to fetch from IGDB - check if it's a connectivity issue
                error_msg = f"⚠️ Local metadata has IGDB ID {igdb_id} but failed to fetch from API."
                logger.error(error_msg)
                log_system_event(
                    f"Failed to fetch game data for IGDB ID {igdb_id} from local metadata at {full_disk_path}. Check internet connection or IGDB API status.",
                    event_type='metadata',
                    event_level='warning'
                )
                # Fall through to normal search below
        else:
            logger.info("📝 [LOCAL METADATA] No existing metadata file found, will attempt IGDB search")

    platform_id = igdb_platform_id_for(library.platform)

    # PRIORITY 2: Search IGDB API by folder/file name (existing code)
    # Prefer Steam App ID title hint when folder name contains (digits)
    raw_folder_label = os.path.basename(full_disk_path.rstrip('\\/'))
    use_console_rom_peel = should_use_console_rom_peel(library, full_disk_path, settings)
    if use_console_rom_peel:
        parsed_label = parse_console_rom_label(
            raw_folder_label,
            platform=library.platform,
        )
    else:
        parsed_label = parse_game_label(
            raw_folder_label,
            peel_profile=match_policy.get('peel_profile'),
        )

    # W22-M5 — bare UPDATE/Updates package folders: never auto-import, never Soft title.
    update_meta = {
        'is_bare_update_package': bool(parsed_label.get('is_bare_update_package')),
        'update_folder_hint': bool(parsed_label.get('update_folder_hint')),
        'match_reason': parsed_label.get('update_match_reason'),
    }
    if not use_console_rom_peel and not update_meta['match_reason']:
        update_meta = detect_update_packaging(
            raw_folder_label,
            cleaned_name=parsed_label.get('cleaned_name'),
            transforms=parsed_label.get('transforms'),
        )
    # A standalone patch/update package ("<Game> update 1.0.7.0 - 1.0.8.0",
    # "Update_from_v1_to_v2", "Unofficial Patch") is an update FOR a game, not a
    # game. Importing it created the game from the update folder -- under the
    # wrong title for a sequel's update (Alan Wake 2 update -> Alan Wake) -- and
    # left the real folder flagged as a duplicate of its own update.
    if not use_console_rom_peel and looks_like_patch_package(raw_folder_label):
        update_meta['is_bare_update_package'] = True
    if update_meta.get('is_bare_update_package'):
        logger.info(
            f"📦 [UPDATE-PACKAGE] Folder '{raw_folder_label}' looks like an update/"
            "patch package — propose/Unmatched only (never auto-import / Soft title)."
        )
        try:
            proposal = {
                'proposal': {
                    'cleaned_name': (parsed_label.get('cleaned_name') or '').strip(),
                    'transforms': list(parsed_label.get('transforms') or []),
                    'candidates': [],
                    'confidence': 'none',
                    'suggested_kind': None,
                    'update_folder_hint': True,
                    'is_bare_update_package': True,
                    'match_reason': 'update_package_folder',
                    'proposed_at': datetime.now(UTC).isoformat(),
                }
            }
            if write_match_proposal(full_disk_path, proposal):
                logger.info(
                    f"📝 [UPDATE-PACKAGE] Wrote update-package proposal for "
                    f"'{raw_folder_label}'"
                )
            try:
                from oneirodex.utils.match_proposal import sync_unmatched_kind_hint

                sync_unmatched_kind_hint(full_disk_path, proposal)
            except Exception:
                pass
        except Exception as proposal_err:
            logger.info(
                f"⚠️ Failed to write update-package proposal for "
                f"{full_disk_path}: {proposal_err}"
            )
        if scan_job_id:
            log_unmatched_folder(
                scan_job_id,
                full_disk_path,
                'Unmatched',
                library_uuid=library.uuid,
                match_reason='update_package_folder',
                suggested_kind=None,
                suggested_candidate_name=None,
            )
        return None

    steam_title = None
    if parsed_label.get('steam_app_id'):
        steam_title = fetch_steam_title_by_app_id(parsed_label['steam_app_id'])
        if steam_title:
            logger.info(f"Steam App ID {parsed_label['steam_app_id']} resolved to '{steam_title}'")

    # Prefer parse_game_label Stage A0–A14 (PC/folder) or console B15–B20 peel for
    # files-mode ROM leaves. Fall back to scan-cleaned name. C11 bare franchise /
    # ROM propose-only (proto/hack/unl/multicart) → propose only (no auto-import).
    # BE-DET-8: ARCADE set basenames + large ARCADE trees → propose-first.
    # BE-DET-9: fandom soft alias / series / remaster / EN↔JP → propose-first.
    variant_base = (parsed_label.get('cleaned_name') or '').strip() or game_name
    bare_franchise = bool(parsed_label.get('bare_franchise'))
    arcade_propose_first = should_arcade_propose_first(
        library, full_disk_path, parsed_label,
    )
    fandom_soft_propose = is_fandom_soft_propose(variant_base)
    rom_propose_only = bool(
        parsed_label.get('propose_only')
        or parsed_label.get('is_multicart')
        or arcade_propose_first
        or fandom_soft_propose
    )
    if rom_propose_only:
        bare_franchise = True
    search_variants = generate_goty_variants(variant_base, policy=match_policy)
    # Re-attach spaced " VR" when Stage A peeled a VR suffix (helps Steam/IGDB
    # titles like "3DSen VR" after glued 3DSenVR → 3DSen).
    if parsed_label.get('had_vr_suffix') and variant_base:
        vr_variant = f'{variant_base} VR'
        if vr_variant not in search_variants:
            search_variants.insert(1 if search_variants else 0, vr_variant)
    if game_name and game_name.strip() and not bare_franchise:
        for extra in generate_goty_variants(game_name, policy=match_policy):
            if extra not in search_variants:
                search_variants.append(extra)
    if steam_title and steam_title not in search_variants:
        search_variants = [steam_title] + [v for v in search_variants if v != steam_title]
    logger.info(f"Generated search variants for '{variant_base}': {search_variants}")
    if bare_franchise:
        reason_bits = []
        if parsed_label.get('is_multicart'):
            reason_bits.append('multicart')
        if arcade_propose_first:
            if parsed_label.get('is_arcade_set'):
                reason_bits.append('ARCADE set propose-first')
            else:
                reason_bits.append('large ARCADE propose-first')
        elif parsed_label.get('propose_only') and not parsed_label.get('is_multicart'):
            reason_bits.append('ROM propose-only')
        if fandom_soft_propose:
            reason_bits.append(
                fandom_match_reason(variant_base) or 'fandom soft alias'
            )
        if parsed_label.get('bare_franchise'):
            reason_bits.append('bare franchise (C11)')
        detail = ', '.join(reason_bits) if reason_bits else 'propose/manual only'
        logger.info(
            f"🏷️ [{detail}] Label '{variant_base}' — "
            "will propose/manual only (no auto-import)"
        )

    response_json = None
    successful_search_name = None
    selected_game = None
    high_confidence_candidates = None
    last_low_confidence_candidates = None
    last_low_confidence_search = None

    high_thr = match_policy.get('match_high_threshold')
    amb_gap = match_policy.get('match_ambiguous_gap')

    # Try each variant until we find a high-confidence match
    for search_name in search_variants:
        logger.info(f"Trying IGDB search with: '{search_name}'")
        candidates = search_igdb_for_game(search_name, platform_id, limit=10)
        if not candidates:
            logger.info(f"No match found for variant: '{search_name}'")
            continue

        best, confidence = select_best_match(
            search_name,
            candidates,
            steam_title=steam_title,
            high_threshold=high_thr,
            ambiguous_gap=amb_gap,
        )
        ranked = rank_candidates(search_name, candidates, steam_title=steam_title)
        logger.info(
            f"IGDB candidates for '{search_name}': "
            + ", ".join(f"{c.get('name')}={c.get('match_score'):.2f}" for c in ranked[:5])
            + f" → confidence={confidence}"
        )

        if confidence == 'high' and best is not None:
            selected_game = best
            successful_search_name = search_name
            response_json = [best]
            high_confidence_candidates = candidates
            logger.info(f"High-confidence match with search variant: '{search_name}' → {best.get('name')}")
            break

        last_low_confidence_candidates = candidates
        last_low_confidence_search = search_name
        logger.info(f"Low-confidence / ambiguous results for '{search_name}' — not auto-importing")

    # Store-title IGDB retry: after folder variants miss, ask Steam/GOG/Epic for
    # an exact title and re-search IGDB once with that canonical name. Raises
    # hit-rate without fuzzy auto-import; Stage D still owns custom-range create.
    store_candidate = None
    if (
        selected_game is None
        and not bare_franchise
        and not is_propose_only_scan(settings)
    ):
        try:
            store_candidate = resolve_stage_d_store_candidate(
                cleaned_name=variant_base,
                steam_app_id=parsed_label.get('steam_app_id'),
                steam_title=steam_title,
                sources=stage_d_source_ids(),
            )
        except Exception as store_err:
            logger.warning(f"⚠️ [Stage D] Store resolve failed for {full_disk_path}: {store_err}")
            store_candidate = None
        retry_title = igdb_retry_title_from_store(store_candidate, search_variants)
        if retry_title:
            logger.info(f"Trying IGDB search with store title: '{retry_title}'")
            candidates = search_igdb_for_game(retry_title, platform_id, limit=10)
            if candidates:
                best, confidence = select_best_match(
                    retry_title,
                    candidates,
                    steam_title=retry_title,
                    high_threshold=high_thr,
                    ambiguous_gap=amb_gap,
                )
                ranked = rank_candidates(retry_title, candidates, steam_title=retry_title)
                logger.info(
                    f"IGDB candidates for store title '{retry_title}': "
                    + ", ".join(
                        f"{c.get('name')}={c.get('match_score'):.2f}" for c in ranked[:5]
                    )
                    + f" → confidence={confidence}"
                )
                if confidence == 'high' and best is not None:
                    selected_game = best
                    successful_search_name = retry_title
                    response_json = [best]
                    high_confidence_candidates = candidates
                    logger.info(
                        f"High-confidence match with store title: '{retry_title}' "
                        f"→ {best.get('name')}"
                    )

    if selected_game is not None:
        try:
            platform_key = getattr(getattr(library, 'platform', None), 'name', None)
            catalog = corroborate_igdb_with_catalogs(
                igdb_name=selected_game.get('name'),
                cleaned_name=variant_base,
                library_platform=platform_key,
            )
        except Exception as catalog_err:
            logger.warning(f"⚠️ [W34] Catalog corroboration failed for {full_disk_path}: {catalog_err}")
            catalog = {
                'verdict': 'no_signal',
                'agreed': [],
                'disagreed': [],
                'skipped': ['error'],
            }
        if catalog.get('verdict') == 'disagree':
            logger.info(
                f"🛑 [W34] Catalog disagreement for '{game_name}' "
                f"(IGDB {selected_game.get('name')}) — writing Review proposal, not importing."
            )
            try:
                proposal = build_match_proposal(
                    game_name,
                    high_confidence_candidates or [selected_game],
                    steam_title=steam_title,
                    confidence='high',
                )
                body = proposal.setdefault('proposal', {})
                body['match_reason'] = MATCH_REASON_CATALOG_DISAGREEMENT
                body['action'] = 'review'
                body['catalog_disagreement'] = {
                    'igdb_name': selected_game.get('name'),
                    'cleaned_name': variant_base,
                    'disagreed': catalog.get('disagreed') or [],
                    'agreed': catalog.get('agreed') or [],
                }
                if write_match_proposal(full_disk_path, proposal):
                    logger.info(
                        f"📝 [W34] Wrote catalog-disagreement proposal for '{variant_base}' "
                        f"→ {os.path.join(full_disk_path, 'oneirodex.proposal.json')}"
                    )
            except Exception as proposal_err:
                logger.info(
                    f"⚠️ [W34] Failed to write catalog-disagreement proposal "
                    f"for {full_disk_path}: {proposal_err}"
                )
            log_unmatched_folder(
                scan_job_id,
                full_disk_path,
                'Unmatched',
                library_uuid=library.uuid,
                match_reason=MATCH_REASON_CATALOG_DISAGREEMENT,
            )
            return None
        # H1d (pass-8 finding): with IDENTIFY_AGREEMENT_MIN >= 2 a title only
        # IGDB named goes to review instead of importing. Default 1 keeps
        # today's behaviour. Same proposal shape as the disagreement branch.
        if not agreement_satisfied(catalog):
            logger.info(
                f"🛑 [H1d] Only {agreement_count(catalog)} source(s) agree on '{game_name}' "
                f"(IGDB {selected_game.get('name')}) — writing Review proposal, not importing."
            )
            try:
                proposal = build_match_proposal(
                    game_name,
                    high_confidence_candidates or [selected_game],
                    steam_title=steam_title,
                    confidence='high',
                )
                body = proposal.setdefault('proposal', {})
                body['match_reason'] = MATCH_REASON_INSUFFICIENT_AGREEMENT
                body['action'] = 'review'
                body['agreement'] = {
                    'igdb_name': selected_game.get('name'),
                    'sources_agreeing': agreement_count(catalog),
                    'agreed': catalog.get('agreed') or [],
                }
                write_match_proposal(full_disk_path, proposal)
            except Exception as proposal_err:
                logger.info(
                    f"⚠️ [H1d] Failed to write agreement proposal for {full_disk_path}: {proposal_err}"
                )
            log_unmatched_folder(
                scan_job_id,
                full_disk_path,
                'Unmatched',
                library_uuid=library.uuid,
                match_reason=MATCH_REASON_INSUFFICIENT_AGREEMENT,
            )
            return None
    else:
        catalog = {'verdict': 'no_signal', 'agreed': [], 'disagreed': [], 'skipped': []}

    # PROPOSE-ONLY MODE / C11 bare franchise / BE-DET-9 fandom soft:
    # never auto-import. Write the proposal sidecar for admin review and stop
    # short of creating a Game. Soft alias never invents IGDB IDs alone.
    if selected_game is not None and (is_propose_only_scan(settings) or bare_franchise):
        if fandom_soft_propose:
            reason = fandom_match_reason(variant_base) or 'fandom soft alias'
        elif bare_franchise and not is_propose_only_scan(settings):
            reason = "bare franchise (C11) / propose-first"
        else:
            reason = "propose_only_scan is enabled"
        logger.info(
            f"🧪 [PROPOSE-ONLY] High-confidence match found for '{game_name}' "
            f"(→ {selected_game.get('name')}) but {reason} — "
            "writing proposal instead of importing."
        )
        try:
            proposal = build_match_proposal(
                game_name,
                high_confidence_candidates or [selected_game],
                steam_title=steam_title,
                confidence='high',
                suggested_kind=(
                    fandom_suggested_kind(variant_base) if fandom_soft_propose else None
                ),
            )
            if fandom_soft_propose:
                reason_code = fandom_match_reason(variant_base)
                if reason_code:
                    proposal['match_reason'] = reason_code
            if write_match_proposal(full_disk_path, proposal):
                logger.info(
                    f"📝 [PROPOSE-ONLY] Wrote high-confidence match proposal for '{successful_search_name}' "
                    f"→ {os.path.join(full_disk_path, 'oneirodex.proposal.json')}"
                )
        except Exception as proposal_err:
            logger.warning(f"⚠️ Failed to write high-confidence match proposal for {full_disk_path}: {proposal_err}")
        return None

    if response_json and 'error' not in response_json and selected_game is not None:
        igdb_id = selected_game.get('id')
        if successful_search_name != game_name:
            logger.info(f"Found game '{game_name}' using search variant '{successful_search_name}' with IGDB ID {igdb_id}")
        else:
            logger.info(f"Found game {game_name} with IGDB ID {igdb_id}")

        # Check for existing game with the same IGDB ID but different folder path
        existing_game_with_same_igdb_id = db.session.execute(
            select(Game)
            .options(joinedload(Game.library))
            .filter(Game.igdb_id == igdb_id, Game.full_disk_path != full_disk_path)
        ).scalar_one_or_none()
        if existing_game_with_same_igdb_id:
            collision = handle_existing_igdb_collision(
                existing_game=existing_game_with_same_igdb_id,
                igdb_id=igdb_id,
                full_disk_path=full_disk_path,
                game_name=game_name,
                scan_job_id=scan_job_id,
                library_uuid=library_uuid,
                candidates=high_confidence_candidates or [selected_game],
                steam_title=steam_title,
                match_policy=match_policy,
                peel=parsed_label if use_console_rom_peel else None,
                library=library,
            )
            if collision is not IMPORT_CROSS_SYSTEM_EDITION:
                return collision
            selected_game = _strip_unique_igdb_identity(selected_game)

        nfo_content = read_first_nfo_content(full_disk_path)
        # Scan path: defer full tree walk — large NAS/Unraid folders block identify for minutes.
        if defer_enrichment:
            folder_size_bytes = 0
            logger.info(f"Deferring folder size walk for scan identify: {full_disk_path}")
        else:
            folder_size_bytes = get_folder_size_in_bytes_updates(full_disk_path)
            logger.info(f"Folder size for {full_disk_path}: {format_size(folder_size_bytes)}")
        new_game = create_game_instance(game_data=selected_game, full_disk_path=full_disk_path, folder_size_bytes=folder_size_bytes, library_uuid=library.uuid, peel=parsed_label if use_console_rom_peel else None)
            
        if new_game is None:
            logger.warning(f"Failed to create game instance for {game_name}. Skipping further processing.")
            return None

        if catalog.get('verdict') == 'agree' and catalog.get('agreed'):
            try:
                apply_catalog_identity_to_game(new_game, catalog['agreed'])
            except Exception as stamp_err:
                logger.warning(f"⚠️ [W34] Catalog identity stamp failed: {stamp_err}")
                
        attach_igdb_taxonomy_to_game(new_game, selected_game)

        if 'involved_companies' in selected_game:
            involved_company_ids = selected_game['involved_companies']
            if involved_company_ids and new_game.igdb_id is not None:
                enumerate_companies(new_game, new_game.igdb_id, involved_company_ids)
            else:
                logger.info(f"No involved companies found for {game_name}.")

        if not defer_enrichment:
            enrich_game_all_sources(new_game, lookup_name=new_game.name)

        if 'videos' in selected_game:
            video_urls = [f"https://www.youtube.com/embed/{video['video_id']}" for video in selected_game['videos']]
            videos_comma_separated = ','.join(video_urls)
            new_game.video_urls = videos_comma_separated
            
        db.session.commit()
        logger.info(f"Processing images for game: {new_game.name}")
        # Pass cover/screenshot refs as returned by IGDB (id or {id,url}).
        # store_image_url_for_download normalizes both shapes so cover is
        # not skipped when search returns expanded objects.
        cover_data = selected_game.get('cover')
        screenshots_data = selected_game.get('screenshots') or []
        if defer_enrichment:
            queue_post_identify_enrichment(
                new_game.uuid,
                fetch_hltb=fetch_hltb,
                cover_data=cover_data,
                screenshots_data=screenshots_data,
            )
        else:
            smart_process_images_for_game(new_game.uuid, cover_data, screenshots_data)
        try:
            new_game.nfo_content = nfo_content
            for column in new_game.__table__.columns:
                getattr(new_game, column.name)
            db.session.commit()
            logger.info(f"Game and its images saved successfully : {new_game.name}.")

            # Write local metadata file if enabled (for newly identified games)
            # Use the settings dict we already have (no DB query needed)
            if settings and settings.get('write_local_metadata'):
                logger.info(f"💾 [LOCAL METADATA] Writing metadata file for newly identified game '{new_game.name}'")
                from oneirodex.utils.local_metadata import write_local_metadata
                write_success = write_local_metadata(
                    full_disk_path=new_game.full_disk_path,
                    igdb_id=new_game.igdb_id,
                    game_title=new_game.name,
                    manually_verified=False,  # Auto-identified during scan
                    filename=settings.get('local_metadata_filename', 'oneirodex.json')
                )
                if write_success:
                    logger.info(f"✅ [LOCAL METADATA] Successfully wrote metadata file for '{new_game.name}'")
                else:
                    logger.warning(f"⚠️ [LOCAL METADATA] Failed to write metadata file for '{new_game.name}'")

            notify_admins_new_game(new_game.uuid, new_game.name)

            # Fetch HowLongToBeat data if enabled (sync path only; deferred when scanning)
            if not defer_enrichment:
                hltb_settings = global_settings_row()
                if fetch_hltb and hltb_settings and hltb_settings.enable_hltb_integration:
                    try:
                        from oneirodex.utils.hltb import update_game_hltb_sync
                        logger.info(f"Fetching HowLongToBeat data for '{new_game.name}'...")
                        update_game_hltb_sync(new_game.uuid, new_game.name)
                    except Exception as e:
                        logger.error(f"Failed to fetch HLTB data for '{new_game.name}': {e}")
                        # Don't fail the scan if HLTB fetch fails

        except IntegrityError as e: 
            db.session.rollback()
            logger.error(f"Failed to save game due to a database error: {e}")
            if has_request_context():
                flash("Failed to save game due to a duplicate entry.")
            else:
                logger.error("Failed to save game due to a duplicate entry.")
        return new_game
    else:
        if response_json and 'error' in response_json:
            # Check specifically for authentication error
            if response_json.get('error') == 'Failed to retrieve access token':
                error_msg = 'IGDB API Authentication Failed'
                if scan_job_id:
                    # Column-only update — avoid loading a ScanJob ORM row that could
                    # clobber folders_success/failed from the scan coordinator.
                    db.session.execute(
                        update(ScanJob)
                        .where(ScanJob.id == scan_job_id)
                        .values(
                            error_message=error_msg,
                            status='Failed',
                            is_enabled=False,
                        )
                    )
                    db.session.commit()
                
                log_system_event(f"IGDB API Authentication Failed: {response_json.get('error')}", 
                                 event_type='scan', event_level='error')
                return None
            
        logger.info(f"No match found: {game_name} in library {library.name} on platform {library.platform.name}.")

        # Stage D (W20-5a): IGDB miss → Steam App ID / exact storesearch or GOG
        # exact title → custom-range Game. Skipped for C11 bare franchise and
        # propose-only (those stay proposal / Unmatched). Ambiguous → fall through.
        if not bare_franchise and not is_propose_only_scan(settings):
            try:
                stage_d_size = 0
                if not defer_enrichment:
                    try:
                        stage_d_size = get_folder_size_in_bytes_updates(full_disk_path)
                    except Exception as size_err:
                        logger.warning(f"⚠️ [Stage D] Folder size skipped: {size_err}")
                        stage_d_size = 0
                stage_d_game = try_stage_d_store_identify(
                    raw_label=raw_folder_label or game_name,
                    cleaned_name=variant_base,
                    full_disk_path=full_disk_path,
                    library_uuid=library.uuid,
                    steam_app_id=parsed_label.get('steam_app_id'),
                    steam_title=steam_title,
                    size=stage_d_size,
                    candidate=store_candidate,
                    sources=stage_d_source_ids(),
                )
                if stage_d_game is not None:
                    logger.info(
                        f"✅ [Stage D] Custom game from store cascade: "
                        f"'{stage_d_game.name}' (igdb_id={stage_d_game.igdb_id}, "
                        f"steam_app_id={getattr(stage_d_game, 'steam_app_id', None)}, "
                        f"item_kind={getattr(stage_d_game, 'item_kind', None)})"
                    )
                    try:
                        db.session.commit()
                    except Exception as commit_err:
                        db.session.rollback()
                        logger.warning(f"⚠️ [Stage D] Commit failed: {commit_err}")
                        stage_d_game = None
                if stage_d_game is not None:
                    if settings and settings.get('write_local_metadata'):
                        try:
                            from oneirodex.utils.local_metadata import write_local_metadata

                            write_local_metadata(
                                full_disk_path=full_disk_path,
                                igdb_id=stage_d_game.igdb_id,
                                game_title=stage_d_game.name,
                                manually_verified=False,
                                filename=settings.get(
                                    'local_metadata_filename', 'oneirodex.json',
                                ),
                            )
                        except Exception as meta_err:
                            logger.warning(f"⚠️ [Stage D] Local metadata write failed: {meta_err}")
                    try:
                        notify_admins_new_game(stage_d_game.uuid, stage_d_game.name)
                    except Exception:
                        pass
                    return stage_d_game
            except Exception as stage_d_err:
                logger.warning(f"⚠️ [Stage D] Store cascade failed for {full_disk_path}: {stage_d_err}")
                try:
                    db.session.rollback()
                except Exception:
                    pass

            # DAT unique hash (W21-BE-DAT): console IGDB miss → unique CRC/MD5/SHA1
            # short-circuit before Stage E TGDB propose. Ambiguous / missing DAT /
            # unhashable → fall through. Skipped for C11 / propose_only / multicart
            # (same gate as Stage D).
            try:
                from oneirodex.utils.set_completion import try_dat_hash_identify

                platform_key = getattr(
                    getattr(library, 'platform', None), 'name', None,
                )
                dat_size = 0
                if not defer_enrichment:
                    try:
                        dat_size = get_folder_size_in_bytes_updates(full_disk_path)
                    except Exception:
                        dat_size = 0
                dat_game = try_dat_hash_identify(
                    full_disk_path=full_disk_path,
                    library_uuid=library.uuid,
                    library_platform=platform_key,
                    size=dat_size,
                )
                if dat_game is not None:
                    logger.info(
                        f"✅ [DAT] Unique hash identify: '{dat_game.name}' "
                        f"(igdb_id={dat_game.igdb_id}, "
                        f"crc={getattr(dat_game, 'file_crc', None)})"
                    )
                    try:
                        db.session.commit()
                    except Exception as commit_err:
                        db.session.rollback()
                        logger.warning(f"⚠️ [DAT] Commit failed: {commit_err}")
                        dat_game = None
                if dat_game is not None:
                    if settings and settings.get('write_local_metadata'):
                        try:
                            from oneirodex.utils.local_metadata import write_local_metadata

                            write_local_metadata(
                                full_disk_path=full_disk_path,
                                igdb_id=dat_game.igdb_id,
                                game_title=dat_game.name,
                                manually_verified=False,
                                filename=settings.get(
                                    'local_metadata_filename', 'oneirodex.json',
                                ),
                            )
                        except Exception as meta_err:
                            logger.warning(f"⚠️ [DAT] Local metadata write failed: {meta_err}")
                    try:
                        notify_admins_new_game(dat_game.uuid, dat_game.name)
                    except Exception:
                        pass
                    return dat_game
            except Exception as dat_err:
                logger.warning(f"⚠️ [DAT] Hash identify failed for {full_disk_path}: {dat_err}")
                try:
                    db.session.rollback()
                except Exception:
                    pass

        # Enrich Unmatched proposal with Steam software/emulator candidates so
        # gaming-adjacent titles (e.g. 3DSenVR) get an honest propose list
        # instead of empty IGDB-only Unmatched. Stage E (after Stage D miss)
        # adds propose-only MobyGames / TheGamesDB exact-title hints — no Game.
        try:
            from oneirodex.utils.software_identify import (
                enrich_proposal_with_software,
                enrich_proposal_with_stage_e,
            )

            proposal = build_match_proposal(
                raw_folder_label or game_name,
                last_low_confidence_candidates or [],
                steam_title=steam_title,
            )
            if update_meta.get('update_folder_hint'):
                body = proposal.setdefault('proposal', {})
                body['update_folder_hint'] = True
                body['match_reason'] = (
                    update_meta.get('match_reason') or 'update_packaging_hint'
                )
                # UPDATE packaging ≠ Soft title — do not invent experience.
                if body.get('suggested_kind') == 'experience' and not body.get(
                    'software_candidates'
                ):
                    body['suggested_kind'] = None
            proposal = enrich_proposal_with_software(
                proposal, raw_folder_label or game_name,
            )
            try:
                platform_key = getattr(
                    getattr(library, 'platform', None), 'name', None,
                )
                proposal = enrich_proposal_with_stage_e(
                    proposal,
                    cleaned_name=variant_base,
                    library_platform=platform_key,
                )
            except Exception as stage_e_err:
                logger.warning(f"⚠️ [Stage E] Propose enrich failed for {full_disk_path}: {stage_e_err}")
            if write_match_proposal(full_disk_path, proposal):
                body = proposal.get('proposal', {}) or {}
                soft_n = len(body.get('software_candidates') or [])
                stage_e_n = len(body.get('stage_e_candidates') or [])
                kind = body.get('suggested_kind')
                logger.info(
                    f"📝 Wrote software-enriched match proposal for '{variant_base}' "
                    f"(igdb_candidates={len(last_low_confidence_candidates or [])}, "
                    f"software_candidates={soft_n}, stage_e_candidates={stage_e_n}, "
                    f"suggested_kind={kind}) "
                    f"→ {os.path.join(full_disk_path, 'oneirodex.proposal.json')}"
                )
                # Denormalize onto UnmatchedFolder when the row already exists
                # (log_unmatched_folder also reads the sidecar when creating).
                try:
                    from oneirodex.utils.match_proposal import sync_unmatched_kind_hint

                    sync_unmatched_kind_hint(full_disk_path, proposal)
                except Exception:
                    pass
        except Exception as proposal_err:
            logger.warning(f"⚠️ Failed to write match proposal for {full_disk_path}: {proposal_err}")
        if has_request_context():
            flash("No game data found for the given name.")
        else:
            logger.info("No game data found for the given name.")
        return None

