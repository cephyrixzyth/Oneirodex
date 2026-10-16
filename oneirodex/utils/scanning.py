import os
import json
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import select, update

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import (
    Game, 
    Image, 
    Library, 
    GameUpdate, 
    GameExtra, 
    UnmatchedFolder,
    GlobalSettings,
    ScanJob
)
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.helpers.fs import read_first_nfo_content
from oneirodex.utils.pc_extras import (
    classify_pc_extra_folder,
    is_pc_library_platform,
    iter_pc_extra_roots,
)
from oneirodex.utils.rom_language import classify_patch_file


def bump_scan_job_progress(
    scan_job_id,
    *,
    success=False,
    failed=False,
    current_processing=None,
):
    """Atomically bump scan counters so worker commits cannot clobber progress.

    Multithreaded identify commits other ScanJob fields from worker sessions;
    ORM ``folders_success += 1`` on a stale coordinator row can stall the UI
    at 1 while games keep landing in the library.
    """
    if not scan_job_id or not (success or failed or current_processing is not None):
        return
    values = {'last_progress_update': datetime.now(timezone.utc)}
    if success:
        values['folders_success'] = ScanJob.folders_success + 1
    if failed:
        values['folders_failed'] = ScanJob.folders_failed + 1
    if current_processing is not None:
        values['current_processing'] = current_processing[:255] if current_processing else None
    db.session.execute(
        update(ScanJob).where(ScanJob.id == scan_job_id).values(**values)
    )
    db.session.commit()


def try_add_game(game_name, full_disk_path, scan_job_id, library_uuid, check_exists=True, fetch_hltb=False, settings=None, app=None, database_scope=None):
    from oneirodex.utils.game_core import (
        retrieve_and_save_game
    )
    from oneirodex.utils.malware_scan import (
        malware_scan_enabled,
        scan_path,
        should_block_result,
        should_block_heuristic_name,
    )
    from oneirodex.utils.event_logging import log_system_event

    # Fetch the library details using the library_uuid, if necessary
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
    if not library:
        print(f"Library with UUID {library_uuid} not found.")
        return False

    if check_exists:
        existing_game = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path)).scalar_one_or_none()
        if existing_game:
            print(f"Game already exists in database: {game_name} at {full_disk_path}")
            from oneirodex.utils.library_health import (
                PATH_STATUS_MISSING,
                mark_game_path_ok,
            )

            if getattr(existing_game, 'path_status', None) == PATH_STATUS_MISSING:
                mark_game_path_ok(existing_game)
            return False

    runtime_config = getattr(app, 'config', None) if app is not None else None
    if malware_scan_enabled(config=runtime_config):
        # Folder name heuristics; files also get ClamAV when reachable. Policy: skip/block on match.
        label = game_name or full_disk_path
        if should_block_heuristic_name(label):
            log_system_event(
                f"Blocked library add after malware heuristic: {full_disk_path}",
                event_type='security',
                event_level='warning',
            )
            print(f"[MALWARE SCAN] Blocked add (heuristic name) for {full_disk_path}")
            return False
        if os.path.isfile(full_disk_path):
            result = scan_path(full_disk_path)
            if should_block_result(result):
                log_system_event(
                    f"Blocked library add after malware scan: {full_disk_path}",
                    event_type='security',
                    event_level='warning',
                )
                print(f"[MALWARE SCAN] Blocked add for {full_disk_path}: {result.to_dict()}")
                return False

    allowed_bases = None
    if app is not None and hasattr(app, 'config'):
        from oneirodex.utils.security import get_allowed_base_directories

        allowed_bases = get_allowed_base_directories(app)
    game = retrieve_and_save_game(
        game_name, full_disk_path, scan_job_id, library_uuid,
        fetch_hltb=fetch_hltb, settings=settings, app=app,
        allowed_bases=allowed_bases,
        database_scope=database_scope,
    )
    return game is not None


def process_game_with_fallback(game_name, full_disk_path, scan_job_id, library_uuid, existing_game_paths=None, existing_unmatched_paths=None, fetch_hltb=False, settings=None, app=None, database_scope=None):
    worker_scope_kwargs = {}
    if app is not None:
        worker_scope_kwargs['app'] = app
    if database_scope is not None:
        worker_scope_kwargs['database_scope'] = database_scope
    # Fast path - check cached sets first if provided
    if existing_game_paths and full_disk_path in existing_game_paths:
        print(f"Game already exists (fast path): {game_name} at {full_disk_path}")
        from oneirodex.utils.library_health import clear_restored_missing_path_status

        clear_restored_missing_path_status(
            [full_disk_path],
            library_uuid=library_uuid,
        )
        return True
    
    if existing_unmatched_paths and full_disk_path in existing_unmatched_paths:
        print(f"Folder already logged as unmatched (fast path): {full_disk_path}")
        return False
    
    # Fetch library details based on library_uuid
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
    if not library:
        print(f"Library with UUID {library_uuid} not found.")
        return False

    # Log skipping of processing for already matched or unmatched folders (fallback for when cached sets not provided)
    # Do NOT bump ScanJob counters here — the scan coordinator owns folders_success/failed
    # (worker increments race with multithreaded progress and stall the UI).
    if not existing_unmatched_paths:
        existing_unmatched_folder = db.session.execute(select(UnmatchedFolder).filter_by(folder_path=full_disk_path)).scalar_one_or_none()
        if existing_unmatched_folder:
            print(f"Skipping processing for already logged unmatched folder: {full_disk_path}")
            return False

    # Check if the game already exists in the database (fallback for when cached sets not provided)
    if not existing_game_paths:
        existing_game = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path, library_uuid=library_uuid)).scalar_one_or_none()
        if existing_game:
            print(f"Game already exists in database: {game_name} at {full_disk_path}")
            from oneirodex.utils.library_health import (
                PATH_STATUS_MISSING,
                mark_game_path_ok,
            )

            if getattr(existing_game, 'path_status', None) == PATH_STATUS_MISSING:
                mark_game_path_ok(existing_game)
            # Don't increment success counter for existing games to avoid inflated counts during rescans
            return True 

    print(f'Game does not exist in database: {game_name} at {full_disk_path}')
    # Try to add the game, now using library_uuid
    if not try_add_game(game_name, full_disk_path, scan_job_id, library_uuid=library_uuid, check_exists=False, fetch_hltb=fetch_hltb, settings=settings, **worker_scope_kwargs):
        # Truncate name from the right — cap attempts so one bad title cannot
        # burn minutes of IGDB round-trips (legacy unbounded fallback loop).
        parts = game_name.split()
        max_fallback = min(3, max(0, len(parts) - 1))
        for i in range(len(parts) - 1, len(parts) - 1 - max_fallback, -1):
            if i <= 0:
                break
            fallback_name = ' '.join(parts[:i])
            if try_add_game(fallback_name, full_disk_path, scan_job_id, library_uuid=library_uuid, check_exists=False, fetch_hltb=fetch_hltb, settings=settings, **worker_scope_kwargs):
                print(f"[GAME MATCH] Success with fallback name: '{fallback_name}'")
                return True
    else:
        return True

    # If the game does not match, log it as unmatched
    matched_status = 'Unmatched'
    log_unmatched_folder(scan_job_id, full_disk_path, matched_status, library_uuid)
    return False



def log_unmatched_folder(
    scan_job_id,
    folder_path,
    matched_status,
    library_uuid=None,
    *,
    matched_game_uuid=None,
    match_reason=None,
    match_score=None,
    suggested_kind=None,
    suggested_candidate_name=None,
    stage_e_candidates=None,
    stage_e=None,
):
    # Denormalize proposal hint at log time (one sidecar read) so list API stays cheap.
    if (
        suggested_kind is None
        and suggested_candidate_name is None
        and stage_e_candidates is None
        and stage_e is None
    ) or match_reason is None:
        try:
            from oneirodex.utils.match_proposal import (
                read_proposal_kind_hint,
                resolve_proposal_path,
            )

            if (
                suggested_kind is None
                and suggested_candidate_name is None
                and stage_e_candidates is None
                and stage_e is None
            ):
                hint = read_proposal_kind_hint(folder_path)
                suggested_kind = hint.get('suggested_kind')
                suggested_candidate_name = hint.get('suggested_candidate_name')
                stage_e_candidates = hint.get('stage_e_candidates')
                stage_e = hint.get('stage_e')
            if match_reason is None:
                path = resolve_proposal_path(folder_path)
                if path:
                    with open(path, encoding='utf-8') as handle:
                        data = json.load(handle)
                    body = data.get('proposal') if isinstance(data, dict) else None
                    if isinstance(body, dict):
                        match_reason = (body.get('match_reason') or '').strip() or None
        except Exception:
            pass

    existing_unmatched_folder = db.session.execute(select(UnmatchedFolder).filter_by(folder_path=folder_path)).scalar_one_or_none()

    if existing_unmatched_folder is None:
        unmatched_folder = UnmatchedFolder(
            folder_path=folder_path,
            failed_time=datetime.now(timezone.utc),
            content_type='Games',
            library_uuid=library_uuid,
            status=matched_status,
            matched_game_uuid=matched_game_uuid,
            match_reason=match_reason,
            match_score=match_score,
            suggested_kind=suggested_kind,
            suggested_candidate_name=suggested_candidate_name,
            stage_e_candidates=stage_e_candidates,
            stage_e=stage_e,
        )
        try:
            db.session.add(unmatched_folder)
            db.session.commit()
            print(f"[UNMATCHED] Logged unmatched folder: {folder_path}")
            print(f"[UNMATCHED] Status: {matched_status}")
            print(f"[UNMATCHED] Library UUID: {library_uuid}")
            print(f"[UNMATCHED] Scan Job ID: {scan_job_id}")
            if match_reason:
                print(f"[UNMATCHED] Match: {match_reason} score={match_score}")
            if suggested_kind:
                print(f"[UNMATCHED] suggested_kind={suggested_kind}")
            if stage_e_candidates:
                print(f"[UNMATCHED] stage_e_candidates={len(stage_e_candidates)}")
        except IntegrityError:
            log_system_event(f"Failed to log unmatched folder: {folder_path}", event_type='scan', event_level='warning')
            db.session.rollback()
            print(f"[UNMATCHED ERROR] Failed to log unmatched folder due to a database error: {folder_path}")
    else:
        # Refresh match metadata when re-encountered as Duplicate
        if matched_status == 'Duplicate':
            existing_unmatched_folder.status = 'Duplicate'
            if matched_game_uuid:
                existing_unmatched_folder.matched_game_uuid = matched_game_uuid
            if match_reason:
                existing_unmatched_folder.match_reason = match_reason
            if match_score is not None:
                existing_unmatched_folder.match_score = match_score
        elif match_reason and not existing_unmatched_folder.match_reason:
            existing_unmatched_folder.match_reason = match_reason
        # Refresh kind / Stage E hint when a newer proposal exists
        if suggested_kind is not None:
            existing_unmatched_folder.suggested_kind = suggested_kind
        if suggested_candidate_name is not None:
            existing_unmatched_folder.suggested_candidate_name = suggested_candidate_name
        if stage_e_candidates is not None:
            existing_unmatched_folder.stage_e_candidates = stage_e_candidates
        if stage_e is not None:
            existing_unmatched_folder.stage_e = stage_e
        if (
            matched_status == 'Duplicate'
            or match_reason
            or suggested_kind is not None
            or suggested_candidate_name is not None
            or stage_e_candidates is not None
            or stage_e is not None
        ):
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
        print(f"[UNMATCHED SKIPPED] Unmatched folder already logged for: {folder_path}. Status: {existing_unmatched_folder.status}")
        


def process_game_updates(game_name, full_disk_path, updates_folder, library_uuid, update_folder_name=None):
    # Use passed parameter or fallback to database query
    if update_folder_name is None:
        settings = global_settings_row()
        if not settings or not settings.update_folder_name:
            print("No update folder configuration found in database")
            return
        update_folder_name = settings.update_folder_name

    print(f"Processing updates for game: {game_name}")
    print(f"Full disk path: {full_disk_path}")
    print(f"Updates folder: {updates_folder}")
    print(f"Library UUID: {library_uuid}")

    game = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path, library_uuid=library_uuid)).scalar_one_or_none()
    if not game:
        print(f"Game not found in database: {game_name}")
        return

    print(f"Game found in database: {game.name} (UUID: {game.uuid})")

    update_folders = [f for f in os.listdir(updates_folder) if os.path.isdir(os.path.join(updates_folder, f))]
    print(f"Update folders found: {update_folders}")

    for update_folder in update_folders:
        update_path = os.path.join(updates_folder, update_folder)
        print(f"Processing update: {update_folder}")
        
        significant_files = [f for f in os.listdir(update_path) if not f.lower().endswith(('.sfv', '.nfo'))]
        print(f"Significant files in update folder: {significant_files}")

        # Always store the folder path to display the proper folder name in UI
        file_path = update_path
        print(f"Using update folder path: {file_path}")

        # Create or update GameUpdate record
        game_update = db.session.execute(select(GameUpdate).filter_by(game_uuid=game.uuid, file_path=file_path)).scalar_one_or_none()
        if not game_update:
            print(f"Creating new GameUpdate record for {file_path}")
            game_update = GameUpdate(
                game_uuid=game.uuid,
                file_path=file_path,
                nfo_content=read_first_nfo_content(update_path)
            )
            db.session.add(game_update)
        else:
            print(f"Updating existing GameUpdate record for {file_path}")
            game_update.file_path = file_path
            game_update.nfo_content = read_first_nfo_content(update_path)

    try:
        db.session.commit()
        print("Successfully committed GameUpdate records to database")
    except SQLAlchemyError as e:
        print(f"Error committing GameUpdate records to database: {str(e)}")
        db.session.rollback()

    print(f"Finished processing updates for game: {game_name}")
    


def process_game_extras(
    game_name,
    full_disk_path,
    extras_folder,
    library_uuid,
    extras_folder_name=None,
    *,
    default_extra_kind=None,
):
    # Use passed parameter or fallback to database query
    if extras_folder_name is None:
        settings = global_settings_row()
        if not settings or not settings.extras_folder_name:
            print("No extras folder configuration found in database")
            return
        extras_folder_name = settings.extras_folder_name

    print(f"Processing extras for game: {game_name}")
    print(f"Full disk path: {full_disk_path}")
    print(f"Extras folder: {extras_folder}")
    print(f"Library UUID: {library_uuid}")

    game = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path, library_uuid=library_uuid)).scalar_one_or_none()
    if not game:
        print(f"Game not found in database: {game_name}")
        return

    print(f"Game found in database: {game.name} (UUID: {game.uuid})")
    extra_items = [f for f in os.listdir(extras_folder) if os.path.isfile(os.path.join(extras_folder, f)) or 
                  os.path.isdir(os.path.join(extras_folder, f))]
    print(f"Extra items found: {extra_items}")

    for extra_item in extra_items:
        extra_path = os.path.join(extras_folder, extra_item)
        print(f"Processing extra: {extra_item}")
        
        # Skip .nfo and .sfv files
        if extra_item.lower().endswith(('.nfo', '.sfv')):
            continue

        # Create or update GameExtra record
        patch_meta = classify_patch_file(extra_item) if os.path.isfile(extra_path) else None
        folder_kind = None
        if os.path.isdir(extra_path):
            folder_kind = classify_pc_extra_folder(extra_item) or default_extra_kind
        elif default_extra_kind:
            folder_kind = default_extra_kind
        game_extra = db.session.execute(select(GameExtra).filter_by(game_uuid=game.uuid, file_path=extra_path)).scalar_one_or_none()
        if not game_extra:
            print(f"Creating new GameExtra record for {extra_path}")
            game_extra = GameExtra(
                game_uuid=game.uuid,
                file_path=extra_path,
                nfo_content=read_first_nfo_content(os.path.dirname(extra_path)),
            )
            db.session.add(game_extra)
        else:
            print(f"Updating existing GameExtra record for {extra_path}")
            game_extra.file_path = extra_path
            game_extra.nfo_content = read_first_nfo_content(os.path.dirname(extra_path))
        if patch_meta:
            game_extra.extra_kind = patch_meta['extra_kind']
            game_extra.patch_format = patch_meta['patch_format']
            game_extra.target_language = patch_meta['target_language']
        elif folder_kind and not game_extra.extra_kind:
            game_extra.extra_kind = folder_kind

    try:
        db.session.commit()
        print(f"Successfully processed extras for game: {game_name}")
    except SQLAlchemyError as e:
        print(f"Error processing extras for game: {str(e)}")
        db.session.rollback()

    print(f"Finished processing extras for game: {game_name}")


def process_pc_dlc_and_extra_roots(
    game_name,
    full_disk_path,
    library_uuid,
    *,
    extras_folder_name=None,
    update_folder_name=None,
):
    """PC-first: associate under-game DLC/extra folders and sibling DLC sidecars."""
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
    if not library or not is_pc_library_platform(getattr(library, 'platform', None)):
        return

    for root in iter_pc_extra_roots(
        full_disk_path,
        configured_extras_name=extras_folder_name,
        configured_updates_name=update_folder_name,
        game_name=game_name,
        include_sidecars=True,
    ):
        print(f"PC extra/DLC root found for {game_name}: {root['path']} ({root['extra_kind']})")
        # Treat the folder itself as one GameExtra when it has no nested children to walk,
        # and also walk children the same way as the configured extras folder.
        process_game_extras(
            game_name,
            full_disk_path,
            root['path'],
            library_uuid,
            extras_folder_name=extras_folder_name,
            default_extra_kind=root['extra_kind'],
        )
        # Also register the root folder itself if it has no processable children.
        game = db.session.execute(
            select(Game).filter_by(full_disk_path=full_disk_path, library_uuid=library_uuid)
        ).scalar_one_or_none()
        if not game:
            continue
        existing = db.session.execute(
            select(GameExtra).filter_by(game_uuid=game.uuid, file_path=root['path'])
        ).scalar_one_or_none()
        if existing:
            if not existing.extra_kind:
                existing.extra_kind = root['extra_kind']
                try:
                    db.session.commit()
                except SQLAlchemyError:
                    db.session.rollback()
            continue
        try:
            children = [
                n for n in os.listdir(root['path'])
                if not n.lower().endswith(('.nfo', '.sfv'))
            ]
        except OSError:
            children = []
        if children:
            continue
        db.session.add(GameExtra(
            game_uuid=game.uuid,
            file_path=root['path'],
            extra_kind=root['extra_kind'],
            nfo_content=read_first_nfo_content(root['path']),
        ))
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()


def refresh_images_in_background(game_uuid, *, app=None):
    if app is None:
        # Legacy WSGI callers rely on the active Flask application. Native
        # FastAPI workers pass their runtime app explicitly so this path stays
        # usable in the Flask-free image.
        from flask import current_app

        app = current_app._get_current_object()

    def flash_if_request_context(message, category):
        try:
            from flask import flash, has_request_context
        except ImportError:
            return False
        if not has_request_context():
            return False
        flash(message, category)
        return True

    from oneirodex import cache
    from oneirodex.utils.igdb_api import make_igdb_api_request
    with app.app_context():
        from oneirodex.utils.game_core import (
            process_and_save_image
        )

        # Set initial progress
        cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 0}, timeout=300)

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
        if not game:
            print("Game not found.")
            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'error', 'progress': 0}, timeout=300)
            return
        try:
            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 20}, timeout=300)

            response_json = make_igdb_api_request(app.config['IGDB_API_ENDPOINT'],
                f"""fields id, cover.url, screenshots.url;
                    where id = {game.igdb_id}; limit 1;""")

            if 'error' not in response_json and response_json:
                cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 40}, timeout=300)

                delete_game_images(game_uuid, config=app.config)

                cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 60}, timeout=300)

                cover_data = response_json[0].get('cover')
                if cover_data:
                    # Pass the full cover object (id+url) so process_and_save_image
                    # can reuse the URL without a second covers lookup.
                    process_and_save_image(game.uuid, cover_data, image_type='cover', app=app)

                screenshots_data = response_json[0].get('screenshots', [])
                total_images = len(screenshots_data) + (1 if cover_data else 0)
                processed = 1 if cover_data else 0

                if total_images > 0:
                    for screenshot in screenshots_data:
                        process_and_save_image(game.uuid, screenshot, image_type='screenshot', app=app)
                        processed += 1
                        progress = 60 + int((processed / total_images) * 30)
                        cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': progress}, timeout=300)
                else:
                    # No images to process, jump to 90%
                    cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'in_progress', 'progress': 90}, timeout=300)

                db.session.commit()
                cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'complete', 'progress': 100}, timeout=300)

                if not flash_if_request_context("Game images refreshed successfully.", "success"):
                    print("Game images refreshed successfully.")
            else:
                cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'error', 'progress': 0}, timeout=300)
                if not flash_if_request_context("Failed to retrieve game images from IGDB API.", "error"):
                    print("Failed to retrieve game images from IGDB API.")

        except Exception as e:
            db.session.rollback()
            cache.set(f'image_refresh_progress_{game_uuid}', {'status': 'error', 'progress': 0}, timeout=300)
            if not flash_if_request_context(f"Failed to refresh game images: {str(e)}", "error"):
                print(f"Failed to refresh game images: {str(e)}")
            
def delete_game_images(game_uuid, *, config=None):
    if config is None:
        from flask import current_app

        config = current_app.config
        app = current_app._get_current_object()
    else:
        app = None

    def delete_images():
        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
        if not game:
            print("Game not found for image deletion.")
            return

        images_to_delete = db.session.execute(select(Image).filter_by(game_uuid=game_uuid)).scalars().all()

        for image in images_to_delete:
            try:
                relative_image_path = image.url.replace('/static/library/images/', '').strip("/")
                image_file_path = os.path.join(config['IMAGE_SAVE_PATH'], relative_image_path)
                image_file_path = os.path.normpath(image_file_path)

                if os.path.exists(image_file_path):
                    os.remove(image_file_path)
                    if not os.path.exists(image_file_path):
                        print(f"Deleted image file: {image_file_path}")
                    else:
                        print(f"Failed to delete image file: {image_file_path}")
                else:
                    print(f"Image file not found: {image_file_path}")

                db.session.delete(image)
            except Exception as e:
                print(f"Error deleting image or database operation failed: {e}")
                db.session.rollback()
                continue  # next image

        try:
            db.session.commit()
            print("All associated images have been deleted.")
        except Exception as e:
            db.session.rollback()
            print(f"Error committing image deletion changes to the database: {e}")
    if app is None:
        delete_images()
    else:
        with app.app_context():
            delete_images()
            
def is_scan_job_running():
    """
    Check if there is any scan job with the status 'Running'.
    
    Returns:
        bool: True if there is a running scan job, False otherwise.
    """
    running_scan_job = db.session.execute(select(ScanJob).filter_by(status='Running')).first()
    return running_scan_job is not None
