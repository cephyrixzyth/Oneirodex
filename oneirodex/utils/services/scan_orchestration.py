"""Scan orchestration service.

Bodies moved verbatim from the root module ``oneirodex/utilities.py`` in wave
A2.3 (``scan_and_add_games`` + ``_scan_and_add_games_body`` + nested
``process_single_game``, schedule math, queue drain/fail helpers, and the
``handle_auto_scan`` / ``handle_manual_scan`` Flask form handlers).
"""
import os
from datetime import datetime, timedelta, timezone
from threading import Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from flask import current_app, flash, redirect, url_for, session, copy_current_request_context
from oneirodex.utils.functions import (
    load_scanning_filter_patterns,
    load_skip_dir_patterns,
    load_skip_dir_regex_patterns,
)
from oneirodex.models import (
    Game, Library, AllowedFileType, ScanJob, GlobalSettings, UnmatchedFolder
)
from oneirodex.utils.global_settings import global_settings_row
from oneirodex import db
from oneirodex.utils.game_core import remove_from_lib
from oneirodex.utils.gamenames import get_game_names_from_folder, get_game_names_from_files
from oneirodex.utils.scanning import process_game_with_fallback, process_game_updates, process_game_extras, process_pc_dlc_and_extra_roots, is_scan_job_running, bump_scan_job_progress
from oneirodex.utils.igdb_api import IGDBRateLimiter
from oneirodex.utils.security import is_safe_path, get_allowed_base_directories
from oneirodex.utils.worker_caps import (
    clamp_scan_threads,
    cooperative_yield,
    iter_chunks,
)
from oneirodex.utils.scan_match_settings import resolve_scan_match_policy
import logging

logger = logging.getLogger(__name__)

SCHEDULE_HOURS = {
    '8_hours': 8,
    '24_hours': 24,
    '48_hours': 48,
}


def compute_next_run(
    schedule_key=None,
    from_time=None,
    *,
    schedule_kind=None,
    interval_minutes=None,
    cron_expr=None,
):
    """Next UTC run for preset hours, interval minutes, or a 5-field cron.

    Legacy call sites pass only ``schedule_key`` (``8_hours`` / ``24_hours`` /
    ``48_hours``). Interval/cron use the keyword args (and/or columns on a job).
    """
    base = from_time or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)

    kind = (schedule_kind or '').strip().lower() or None
    if kind == 'interval' or (interval_minutes and not schedule_key):
        minutes = int(interval_minutes or 0)
        if minutes < 1:
            return None
        return base + timedelta(minutes=minutes)

    if kind == 'cron' or (cron_expr and not schedule_key):
        expr = (cron_expr or '').strip()
        if not expr:
            return None
        from oneirodex.utils.cron_schedule import next_cron_fire

        try:
            return next_cron_fire(expr, from_time=base)
        except ValueError:
            logger.warning(f'Invalid scan cron expression: {expr!r}')
            return None

    hours = SCHEDULE_HOURS.get(schedule_key)
    if not hours:
        return None
    return base + timedelta(hours=hours)


def resolve_scan_mode_for_path(folder_path, requested_mode='auto'):
    """Resolve folders/files/auto into a concrete scan mode.

    Auto: if the target has mostly ROM/archive files at depth 1 → files;
    if it has game-like subfolders → folders; ambiguous → folders.
    """
    mode = (requested_mode or 'auto').strip().lower()
    if mode in ('folders', 'files'):
        return mode
    if mode not in ('auto', ''):
        return 'folders'

    path = (folder_path or '').strip()
    if not path or not os.path.isdir(path):
        return 'folders'

    archive_ext = {
        '.zip', '.7z', '.rar', '.iso', '.chd', '.rvz', '.wbfs', '.cso',
        '.nsp', '.xci', '.vpk', '.cia', '.3ds', '.nds', '.gba', '.gb', '.gbc',
        '.nes', '.sfc', '.smc', '.n64', '.z64', '.v64', '.nds', '.cue', '.bin',
        '.pbp', '.cso', '.img', '.rom',
    }
    try:
        names = os.listdir(path)
    except OSError:
        return 'folders'

    file_hits = 0
    dir_hits = 0
    for name in names:
        if name.startswith('.'):
            continue
        full = os.path.join(path, name)
        try:
            if os.path.isdir(full):
                dir_hits += 1
            elif os.path.isfile(full):
                ext = os.path.splitext(name)[1].lower()
                if ext in archive_ext:
                    file_hits += 1
        except OSError:
            continue

    if file_hits >= 3 and file_hits > dir_hits * 2:
        return 'files'
    if dir_hits >= 1:
        return 'folders'
    if file_hits >= 1:
        return 'files'
    return 'folders'


def _drain_scan_queue_safe():
    """Best-effort FIFO promote after a scan leaves Running/Stopping."""
    try:
        from oneirodex.utils.scan_queue import drain_scan_queue
        drain_scan_queue(current_app._get_current_object())
    except Exception as drain_exc:
        logger.error(f"[SCAN QUEUE] Drain failed: {drain_exc}")


def _fail_scan_job_and_drain(job_or_id, error_message):
    """Mark a job Failed (if still busy) and promote the next Queued scan."""
    try:
        job = job_or_id
        if isinstance(job_or_id, str):
            job = db.session.get(ScanJob, job_or_id)
        if job and job.status in ('Running', 'Stopping', 'Queued'):
            job.status = 'Failed'
            job.is_enabled = False
            job.current_processing = None
            job.error_message = error_message
            try:
                db.session.commit()
            except SQLAlchemyError as exc:
                logger.error(f"[SCAN QUEUE] Failed to mark job Failed: {exc}")
                db.session.rollback()
    except Exception as exc:
        logger.error(f"[SCAN QUEUE] fail-and-drain helper error: {exc}")
    _drain_scan_queue_safe()


def scan_and_add_games(folder_path, scan_mode='folders', library_uuid=None, remove_missing=False, existing_job=None, download_missing_images=False, force_updates_extras_scan=False, fetch_hltb=False, force_hltb_refetch=False, schedule=None, force_parallel=False):
    # Only check for running jobs if we're not restarting/resuming an existing job
    # Prefer start_or_queue_scan() at call sites so second requests queue instead of dropping.
    # force_parallel=True (admin opt-in) allows overlapping jobs; still respects thread caps.
    if not existing_job and is_scan_job_running() and not force_parallel:
        logger.info(
            "A scan is already in progress. Request dropped at worker entry — "
            "callers should use start_or_queue_scan() so the request is queued."
        )
        return

    scan_job_id = getattr(existing_job, 'id', None)
    try:
        body_job_id = _scan_and_add_games_body(
            folder_path,
            scan_mode=scan_mode,
            library_uuid=library_uuid,
            remove_missing=remove_missing,
            existing_job=existing_job,
            download_missing_images=download_missing_images,
            force_updates_extras_scan=force_updates_extras_scan,
            fetch_hltb=fetch_hltb,
            force_hltb_refetch=force_hltb_refetch,
            schedule=schedule,
            force_parallel=force_parallel,
        )
        if body_job_id:
            scan_job_id = body_job_id
    except Exception as exc:
        logger.error(f"[SCAN] Unhandled scan failure: {exc}")
        if not scan_job_id:
            try:
                stuck = db.session.execute(
                    select(ScanJob.id).where(
                        ScanJob.library_uuid == library_uuid,
                        ScanJob.status.in_(('Running', 'Stopping')),
                    ).order_by(ScanJob.last_run.desc()).limit(1)
                ).scalar()
                scan_job_id = stuck
            except Exception:
                pass
        if scan_job_id:
            _fail_scan_job_and_drain(scan_job_id, f'Scan crashed: {exc}')
        raise
    finally:
        # Safety net: never leave *this* job Running/Stopping forever (blocks FIFO).
        if scan_job_id:
            try:
                leftover = db.session.get(ScanJob, scan_job_id)
                if leftover and leftover.status in ('Running', 'Stopping'):
                    prior = leftover.status
                    leftover.status = 'Failed'
                    leftover.is_enabled = False
                    leftover.current_processing = None
                    leftover.error_message = (
                        leftover.error_message
                        or 'Scan ended without a terminal status; marked Failed so the queue can drain.'
                    )
                    db.session.commit()
                    logger.info(
                        f"[SCAN QUEUE] Safety-net Failed for stuck job {leftover.id} "
                        f"(was still {prior})"
                    )
                    _drain_scan_queue_safe()
            except Exception as safety_exc:
                logger.error(f"[SCAN QUEUE] Safety-net drain failed: {safety_exc}")


def _scan_and_add_games_body(folder_path, scan_mode='folders', library_uuid=None, remove_missing=False, existing_job=None, download_missing_images=False, force_updates_extras_scan=False, fetch_hltb=False, force_hltb_refetch=False, schedule=None, force_parallel=False):
    """Core scan worker. Returns ScanJob id when known."""
    scan_job_entry = None
    # Cache settings once at the start of scan
    settings_obj = global_settings_row()
    update_folder_name = settings_obj.update_folder_name if settings_obj else 'updates'
    extras_folder_name = settings_obj.extras_folder_name if settings_obj else 'extras'
    enable_game_updates = settings_obj.enable_game_updates if settings_obj else False
    enable_game_extras = settings_obj.enable_game_extras if settings_obj else False
    scan_thread_count = clamp_scan_threads(
        settings_obj.scan_thread_count if settings_obj else 1
    )

    # Extract local metadata + scan/match policy into a plain dict (thread-safe).
    # We can't pass SQLAlchemy objects across threads, so extract values now.
    match_policy = resolve_scan_match_policy(settings_obj)
    settings_dict = {
        'use_local_metadata': settings_obj.use_local_metadata if settings_obj else False,
        'write_local_metadata': settings_obj.write_local_metadata if settings_obj else False,
        'use_local_images': settings_obj.use_local_images if settings_obj else False,
        'local_metadata_filename': settings_obj.local_metadata_filename if settings_obj else 'oneirodex.json',
        'propose_only_scan': match_policy.get('propose_only_scan', False),
        'scan_mode': scan_mode,
        # W20-4 — identify/dupe/peel must see admin overrides, not only code defaults.
        **{k: match_policy[k] for k in (
            'dupe_title_threshold',
            'match_high_threshold',
            'match_ambiguous_gap',
            'peel_profile',
            'enable_year_drop_variant',
            'enable_pack_peel_variant',
            'enable_edition_peel_variant',
            'enable_sequel_numeral_variant',
        )},
    }

    # Log local metadata settings once at scan start
    if settings_obj:
        logger.info(f"📋 [LOCAL METADATA] Settings: use_local_metadata={settings_dict['use_local_metadata']}, write_local_metadata={settings_dict['write_local_metadata']}, use_local_images={settings_dict['use_local_images']}")
    
    # Initialize IGDB rate limiter for scanning operations
    igdb_rate_limiter = IGDBRateLimiter()
    
    # Bulk prefetch existing games and unmatched folders for performance
    logger.info("Prefetching existing games and unmatched folders...")
    existing_game_paths = set(
        db.session.execute(
            select(Game.full_disk_path).filter_by(library_uuid=library_uuid)
        ).scalars().all()
    )
    existing_unmatched_paths = set(
        db.session.execute(
            select(UnmatchedFolder.folder_path).filter_by(library_uuid=library_uuid)
        ).scalars().all()
    )
    logger.info(f"Prefetched {len(existing_game_paths)} existing games and {len(existing_unmatched_paths)} unmatched folders")
    
    # Use existing job or create new one (before library/extension gates so early
    # failures can mark the job Failed instead of leaving it Running forever).
    if existing_job:
        # Re-query the job to ensure it's bound to the current session
        scan_job_entry = db.session.get(ScanJob, existing_job.id)
        if not scan_job_entry:
            logger.warning(f"Existing scan job {existing_job.id} not found.")
            return getattr(existing_job, 'id', None)
        logger.info(f"Using existing scan job: {scan_job_entry.id}")
    else:
        # Local import: scan_queue imports scan_and_add_games from this module,
        # so a module-level import here would close the cycle. Every other
        # scan_queue use in this file is function-local for the same reason.
        from oneirodex.utils.scan_queue import PROCESS_TOKEN, scan_run_values

        # Create initial scan job
        scan_job_entry = ScanJob(
            folders={folder_path: True},
            content_type='Games',
            status='Running',
            is_enabled=True,
            last_run=datetime.now(),
            library_uuid=library_uuid,
            error_message='',
            total_folders=0,
            folders_success=0,
            folders_failed=0,
            removed_count=0,
            scan_folder=folder_path,
            setting_remove=remove_missing,
            setting_filefolder=(scan_mode == 'files'),
            setting_download_missing_images=download_missing_images,
            setting_force_updates_extras=force_updates_extras_scan,
            schedule=schedule if schedule in ('8_hours', '24_hours', '48_hours') else None,
            # This process is about to run the scan on its own thread, so it
            # owns the job. Without the stamp a job created down this path — the
            # direct callers that bypass start_or_queue_scan — would be
            # indistinguishable from a pre-upgrade row, and an orphan here would
            # go back to blocking the queue for STALE_RUNNING_SECONDS.
            owner_token=PROCESS_TOKEN,
        )

        for key, value in scan_run_values().items():
            setattr(scan_job_entry, key, value)
        db.session.add(scan_job_entry)
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            # Roll back before bailing. A failed flush leaves the session in a
            # "needs rollback" state, so every later statement on it — the rest
            # of the request included — raises PendingRollbackError instead of
            # anything describing the real problem.
            #
            # This path is reachable in normal use: a library_uuid with no
            # matching library trips scan_jobs_library_uuid_fkey, and the
            # missing-library handling below never gets to run because the job
            # it wants to mark Failed could not be inserted in the first place.
            db.session.rollback()
            logger.error(f"Database error when adding ScanJob: {str(e)}")
            return None  # cannot proceed without ScanJob

    job_id = scan_job_entry.id

    # Library + allowed extensions (after job exists so failures mark Failed + drain).
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
    if not library:
        error_message = f"Library with UUID {library_uuid} not found."
        logger.error(error_message)
        scan_job_entry.status = 'Failed'
        scan_job_entry.error_message = error_message
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Database error when updating ScanJob with error: {str(e)}")
        _drain_scan_queue_safe()
        return job_id

    allowed_extensions = [
        ext.value.lower()
        for ext in db.session.execute(select(AllowedFileType)).scalars().all()
    ]
    if not allowed_extensions:
        error_message = (
            "No allowed file types found in database. "
            "Please configure them in the admin panel."
        )
        logger.error(error_message)
        scan_job_entry.status = 'Failed'
        scan_job_entry.error_message = error_message
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Database error when updating ScanJob with error: {str(e)}")
        _drain_scan_queue_safe()
        return job_id

    logger.info(
        f"Starting auto scan for games in folder: {folder_path} with scan mode: "
        f"{scan_mode} and library UUID: {library_uuid} for platform: {library.platform.name}"
    )

    # Check access perm
    if not os.path.exists(folder_path) or not os.access(folder_path, os.R_OK):
        error_message = f"Cannot access folder at path {folder_path}. Check permissions."
        logger.error(error_message)
        scan_job_entry.status = 'Failed'
        scan_job_entry.error_message = error_message
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            logger.error(f"Database error when updating ScanJob with error: {str(e)}")
        _drain_scan_queue_safe()
        return job_id

    # Load patterns before they are used
    insensitive_patterns, sensitive_patterns = load_scanning_filter_patterns()
    skip_dir_patterns = load_skip_dir_patterns()
    skip_dir_regexes = load_skip_dir_regex_patterns()

    try:
        # Use database-stored allowed extensions
        if scan_mode == 'folders':
            scan_depth = getattr(library, 'scan_depth', 1) or 1
            game_names_with_paths = get_game_names_from_folder(
                folder_path,
                insensitive_patterns,
                sensitive_patterns,
                scan_depth=scan_depth,
                skip_dir_patterns=skip_dir_patterns,
                skip_dir_regexes=skip_dir_regexes,
            )
        elif scan_mode == 'files':
            game_names_with_paths = get_game_names_from_files(folder_path, allowed_extensions, insensitive_patterns, sensitive_patterns)

        scan_job_entry.total_folders = len(game_names_with_paths)
        db.session.commit()
        if not game_names_with_paths:
            logger.info(f"No games found in folder: {folder_path}")
            scan_job_entry.error_message = "No games found."
    except Exception as e:
        scan_job_entry.status = 'Failed'
        scan_job_entry.error_message = str(e)
        db.session.commit()
        logger.error(f"Error during pattern loading or game name extraction: {str(e)}")
        _drain_scan_queue_safe()
        return job_id

    def process_single_game(game_info, scan_job_id, library_uuid, update_folder_name, extras_folder_name, enable_game_updates, enable_game_extras, existing_game_paths, existing_unmatched_paths, igdb_rate_limiter, app, force_updates_extras_scan=False, fetch_hltb=False, force_hltb_refetch=False, settings=None):
        """Process a single game with rate limiting and thread-safe database operations."""
        game_name = game_info['name']
        full_disk_path = game_info['full_path']
        result = {'game_name': game_name, 'success': False, 'error': None}
        
        # Fast path - check cached sets BEFORE rate limiting
        # But if force_updates_extras_scan or force_hltb_refetch is enabled, we need to process existing games
        if existing_game_paths and full_disk_path in existing_game_paths:
            logger.warning(f"Game already exists (cached): {game_name} at {full_disk_path}")
            # Continue processing if:
            # 1. force_updates_extras_scan is enabled AND (updates OR extras scanning is enabled), OR
            # 2. force_hltb_refetch is enabled
            should_process_existing = False
            if force_updates_extras_scan and (enable_game_updates or enable_game_extras):
                should_process_existing = True
                logger.info(f"Force mode enabled, checking updates/extras for existing game: {game_name}")
            if force_hltb_refetch:
                should_process_existing = True
                logger.info(f"Force HLTB refetch enabled, will update HLTB data for existing game: {game_name}")

            if not should_process_existing:
                with app.app_context():
                    from oneirodex.utils.library_health import (
                        clear_restored_missing_path_status,
                    )

                    if clear_restored_missing_path_status(
                        [full_disk_path],
                        library_uuid=library_uuid,
                    ):
                        db.session.commit()
                return {'game_name': game_name, 'success': True, 'already_exists': True}

            game_already_exists = True
        else:
            game_already_exists = False
        
        if existing_unmatched_paths and full_disk_path in existing_unmatched_paths:
            logger.info(f"Folder already logged as unmatched (cached): {full_disk_path}")
            return {'game_name': game_name, 'success': False, 'already_unmatched': True}
        
        # Ensure we have a Flask app context for database operations
        with app.app_context():
            try:
                # Use rate limiter for IGDB API calls
                igdb_rate_limiter.acquire()
                try:
                    # If game already exists and we're in force mode, skip game processing and go directly to updates/extras
                    if game_already_exists:
                        success = True
                        logger.warning(f"Skipping game processing for existing game in force mode: {game_name}")
                    else:
                        success = process_game_with_fallback(game_name, full_disk_path, scan_job_id, library_uuid, fetch_hltb=fetch_hltb, settings=settings)
                    
                    result['success'] = success
                    
                    if success:
                        # Check for updates folder using the cached setting
                        if enable_game_updates:
                            updates_folder = os.path.join(full_disk_path, update_folder_name)
                            if os.path.exists(updates_folder) and os.path.isdir(updates_folder):
                                logger.info(f"Updates folder found for game: {game_name}")
                                process_game_updates(game_name, full_disk_path, updates_folder, library_uuid, update_folder_name)
                            else:
                                logger.info(f"No updates folder found for game: {game_name}")
                        else:
                            logger.warning(f"Updates scanning disabled, skipping for game: {game_name}")

                        # Check for extras folder
                        if enable_game_extras:
                            extras_folder = os.path.join(full_disk_path, extras_folder_name)
                            if os.path.exists(extras_folder) and os.path.isdir(extras_folder):
                                logger.info(f"Extras folder found for game: {game_name}")
                                process_game_extras(game_name, full_disk_path, extras_folder, library_uuid, extras_folder_name)
                            else:
                                logger.info(f"No extras folder found for game: {game_name}")
                            # PC-first: also associate common DLC/extra folder names + sibling DLC sidecars
                            process_pc_dlc_and_extra_roots(
                                game_name,
                                full_disk_path,
                                library_uuid,
                                extras_folder_name=extras_folder_name,
                                update_folder_name=update_folder_name,
                            )
                        else:
                            logger.warning(f"Extras scanning disabled, skipping for game: {game_name}")

                        # Fetch HLTB data for existing games if force_hltb_refetch is enabled
                        if game_already_exists and force_hltb_refetch:
                            try:
                                from oneirodex.models import GlobalSettings
                                settings = global_settings_row()
                                if settings and settings.enable_hltb_integration:
                                    from oneirodex.utils.hltb import update_game_hltb_sync
                                    # Get the game UUID from database
                                    from oneirodex.models import Game
                                    game_obj = db.session.execute(
                                        select(Game).where(Game.full_disk_path == full_disk_path)
                                    ).scalars().first()
                                    if game_obj:
                                        logger.info(f"Refetching HLTB data for existing game '{game_name}'...")
                                        update_game_hltb_sync(game_obj.uuid, game_obj.name)
                                    else:
                                        logger.info(f"Could not find game in database to refetch HLTB: {game_name}")
                            except Exception as e:
                                logger.error(f"Failed to refetch HLTB data for '{game_name}': {e}")
                                # Don't fail the scan if HLTB fetch fails
                    else:
                        result['unmatched'] = True
                        logger.info(f"[PROCESS INFO] Game '{game_name}' could not be matched to IGDB database or was already unmatched.")
                        logger.info(f"[PROCESS INFO] Game path: {full_disk_path}")
                        logger.error("[PROCESS INFO] This is informational, not an error")
                        
                finally:
                    igdb_rate_limiter.release()
                    
            except Exception as e:
                result['error'] = str(e)
                logger.error(f"[PROCESS EXCEPTION] Exception in process_single_game for '{game_name}': {str(e)}")
                logger.error(f"[PROCESS EXCEPTION] Game path: {full_disk_path}")
                logger.error(f"[PROCESS EXCEPTION] Full exception: {repr(e)}")
                import traceback
                logger.error(f"[PROCESS EXCEPTION] Traceback: {traceback.format_exc()}")
                try:
                    db.session.rollback()
                except Exception:
                    pass
            finally:
                # Drop worker-bound session state so threads do not share a dirty Session.
                db.session.remove()
                
        return result
    
    # Process games either sequentially or in parallel based on thread count
    scan_was_cancelled = False
    scan_job_id = scan_job_entry.id
    total_to_process = len(game_names_with_paths)
    if scan_thread_count > 1:
        # Multithreaded processing — bounded queue (chunked submit) + hard thread cap.
        logger.info(f"Using multithreaded scanning with {scan_thread_count} threads (capped)")
        processed_count = 0
        app_obj = current_app._get_current_object()
        chunk_size = max(scan_thread_count * 2, scan_thread_count)
        with ThreadPoolExecutor(max_workers=scan_thread_count) as executor:
            for chunk in iter_chunks(game_names_with_paths, chunk_size):
                if scan_was_cancelled:
                    break
                future_to_game = {
                    executor.submit(
                        process_single_game,
                        game_info,
                        scan_job_id,
                        library_uuid,
                        update_folder_name,
                        extras_folder_name,
                        enable_game_updates,
                        enable_game_extras,
                        existing_game_paths,
                        existing_unmatched_paths,
                        igdb_rate_limiter,
                        app_obj,
                        force_updates_extras_scan,
                        fetch_hltb,
                        force_hltb_refetch,
                        settings_dict,
                    ): game_info
                    for game_info in chunk
                }

                # Process completed futures — always count first, then honor Stop by
                # cancelling pending work and draining in-flight results (do not return early).
                for future in as_completed(future_to_game):
                    # Discard any worker-touched session state on the coordinator thread.
                    db.session.remove()

                    if future.cancelled():
                        continue

                    game_info = future_to_game[future]
                    try:
                        result = future.result()
                        processed_count += 1
                        label = (
                            f"Processing: {result.get('game_name') or game_info['name']} "
                            f"({processed_count}/{total_to_process})"
                        )
                        if result.get('success'):
                            bump_scan_job_progress(
                                scan_job_id,
                                success=True,
                                current_processing=label,
                            )
                        else:
                            bump_scan_job_progress(
                                scan_job_id,
                                failed=True,
                                current_processing=label,
                            )
                            if result.get('unmatched'):
                                logger.error(f"[SCAN INFO] Game '{result['game_name']}' was unmatched (not an error)")
                            elif result.get('error'):
                                error_line = f"Failed to process '{result['game_name']}': {result['error']}"
                                job_row = db.session.get(ScanJob, scan_job_id)
                                if job_row:
                                    job_row.error_message = (job_row.error_message or "") + f"{error_line}\n"
                                    db.session.commit()
                                logger.error(f"[SCAN ERROR] {error_line}")
                                logger.error(f"[SCAN ERROR] Game path: {game_info.get('full_path')}")
                                logger.error(f"[SCAN ERROR] Full result: {result}")

                    except Exception as e:
                        processed_count += 1
                        bump_scan_job_progress(
                            scan_job_id,
                            failed=True,
                            current_processing=f"Error: {game_info['name']} ({processed_count}/{total_to_process})",
                        )
                        error_line = f"Exception processing '{game_info['name']}': {str(e)}"
                        job_row = db.session.get(ScanJob, scan_job_id)
                        if job_row:
                            job_row.error_message = (job_row.error_message or "") + f"{error_line}\n"
                            db.session.commit()
                        logger.error(f"[SCAN EXCEPTION] {error_line}")
                        logger.error(f"[SCAN EXCEPTION] Game path: {game_info.get('full_path', 'unknown')}")
                        logger.error(f"[SCAN EXCEPTION] Full exception: {repr(e)}")
                        import traceback
                        logger.error(f"[SCAN EXCEPTION] Traceback: {traceback.format_exc()}")

                    cooperative_yield()

                    # After counting, check shutdown / user Stop
                    from oneirodex.utils.shutdown import should_continue_processing
                    scan_job_entry = db.session.get(ScanJob, scan_job_id)
                    stop_requested = (
                        not should_continue_processing()
                        or not scan_job_entry
                        or not scan_job_entry.is_enabled
                    )
                    if stop_requested:
                        scan_was_cancelled = True
                        for f in future_to_game:
                            if not f.done():
                                f.cancel()
                        if scan_job_entry:
                            scan_job_entry.status = 'Stopping'
                            if not should_continue_processing():
                                scan_job_entry.error_message = 'Scan cancelled due to application shutdown'
                            else:
                                scan_job_entry.error_message = (
                                    scan_job_entry.error_message
                                    or 'Scan is stopping, waiting for in-flight folders to finish'
                                )
                            scan_job_entry.current_processing = (
                                f"Stopping… ({processed_count}/{total_to_process})"
                            )
                            db.session.commit()
                        # Keep draining as_completed so in-flight results still bump counters

            # Finalize cancel after all futures settled (executor context waits on exit too)
            db.session.remove()
            scan_job_entry = db.session.get(ScanJob, scan_job_id)
            if scan_was_cancelled and scan_job_entry:
                scan_job_entry.status = 'Cancelled'
                if not scan_job_entry.error_message or 'stopping' in (scan_job_entry.error_message or '').lower():
                    scan_job_entry.error_message = 'Scan cancelled by user'
                scan_job_entry.current_processing = None
                scan_job_entry.is_enabled = False
                db.session.commit()
    else:
        # Use the same processor as the pool: thread count must not change
        # force-refresh behavior. Each call owns its app context/session too.
        app_obj = current_app._get_current_object()
        for processed_count, game_info in enumerate(game_names_with_paths, start=1):
            db.session.remove()
            scan_job_entry = db.session.get(ScanJob, scan_job_id)
            from oneirodex.utils.shutdown import should_continue_processing
            if not scan_job_entry or not scan_job_entry.is_enabled or not should_continue_processing():
                if scan_job_entry:
                    scan_job_entry.status = 'Cancelled'
                    scan_job_entry.error_message = 'Scan cancelled by user'
                    scan_job_entry.current_processing = None
                    scan_job_entry.is_enabled = False
                    db.session.commit()
                scan_was_cancelled = True
                break
            result = process_single_game(
                game_info, scan_job_id, library_uuid, update_folder_name,
                extras_folder_name, enable_game_updates, enable_game_extras,
                existing_game_paths, existing_unmatched_paths, igdb_rate_limiter,
                app_obj, force_updates_extras_scan, fetch_hltb, force_hltb_refetch,
                settings_dict,
            )
            bump_scan_job_progress(
                scan_job_id, success=bool(result.get('success')),
                failed=not result.get('success'),
                current_processing=f"Processing: {game_info['name']} ({processed_count}/{total_to_process})",
            )
            if result.get('error'):
                scan_job_entry = db.session.get(ScanJob, scan_job_id)
                scan_job_entry.error_message = (scan_job_entry.error_message or '') + str(result['error']) + '\n'
                db.session.commit()
            cooperative_yield()

    db.session.remove()
    scan_job_entry = db.session.get(ScanJob, scan_job_id)
    if not scan_job_entry:
        return scan_job_id

    # The library is done filling (completed *or* cancelled after some titles
    # landed), so the pending new-game digest can go out with a final count
    # (UX-B7). Without this it fires on a five-second debounce, so any pause
    # longer than that — a slow scrape, a big file, a rate-limited provider —
    # announces a library that is still being added to.
    try:
        from oneirodex.utils.notifications import flush_library_add_digest

        flush_library_add_digest(library_uuid)
    except Exception as exc:
        # A notification must never fail a completed scan.
        logger.error(f"Could not flush library-add digest: {exc}")

    if scan_was_cancelled:
        # Counters already finalized; skip Completed / remove_missing / image pass
        logger.warning(f"Scan cancelled for folder: {folder_path} with ScanJob ID: {scan_job_id}")
        _drain_scan_queue_safe()
        return scan_job_id

    if scan_job_entry.status != 'Failed':
        scan_job_entry.status = 'Completed'
        # Remember last scan root for refresh-all
        if library is not None:
            library.last_scan_folder = folder_path
        # Schedule next run when configured (preset / interval / cron)
        from oneirodex.utils.scan_queue import job_next_run_from_row

        job_schedule = schedule or getattr(scan_job_entry, 'schedule', None)
        if job_schedule in SCHEDULE_HOURS and not getattr(scan_job_entry, 'schedule_kind', None):
            scan_job_entry.schedule = job_schedule
            scan_job_entry.schedule_kind = 'preset'
        next_run = job_next_run_from_row(scan_job_entry)
        if next_run is None and job_schedule in SCHEDULE_HOURS:
            next_run = compute_next_run(job_schedule)
        if next_run is not None:
            scan_job_entry.next_run = next_run
            scan_job_entry.status = 'Scheduled'
            scan_job_entry.is_enabled = True
            logger.info(
                f"Scheduled next scan for {scan_job_entry.next_run} "
                f"(kind={getattr(scan_job_entry, 'schedule_kind', None)}, schedule={job_schedule})"
            )
    
    # Persist path_status for every library game (cheap exists per row — not Ops poll).
    # When remove_missing is enabled, also delete rows whose path is gone.
    logger.info("Refreshing path_status for library games...")
    from oneirodex.utils.library_health import (
        PATH_STATUS_MISSING,
        refresh_game_path_status,
    )
    games_in_library = db.session.execute(
        select(Game).filter_by(library_uuid=library_uuid)
    ).scalars().all()
    for game in games_in_library:
        try:
            status = refresh_game_path_status(game)
        except Exception as e:
            logger.error(f"Error refreshing path_status for {game.name}: {e}")
            continue
        if status != PATH_STATUS_MISSING:
            continue
        logger.warning(f"Game no longer found at path: {game.full_disk_path}")
        if not remove_missing:
            continue
        try:
            remove_from_lib(game.uuid)
            scan_job_entry.removed_count += 1
            logger.info(
                f"Removed game {game.name} as it no longer exists at {game.full_disk_path}"
            )
        except Exception as e:
            logger.error(f"Error removing game {game.name}: {e}")

    # If download_missing_images is enabled, check for and queue missing images
    if download_missing_images:
        logger.info("🔍 Download missing images option enabled - checking for missing images...")
        try:
            from oneirodex.utils.game_core import process_missing_images_for_scan
            result = process_missing_images_for_scan(library_uuid, current_app._get_current_object())
            
            if result.get('success'):
                message = f"Missing images scan: {result['message']}"
                logger.info(message)
                
                # Add to scan job status for user feedback
                if scan_job_entry.error_message:
                    scan_job_entry.error_message += f" | {message}"
                else:
                    scan_job_entry.error_message = message
                    
            else:
                error_message = f"Missing images scan failed: {result.get('error', 'Unknown error')}"
                logger.error(error_message)
                scan_job_entry.error_message += f" | {error_message}"
                
        except Exception as e:
            error_message = f"Error during missing images processing: {str(e)}"
            logger.error(error_message)
            scan_job_entry.error_message += f" | {error_message}"

    try:
        # Truncate error message if it's too long
        if scan_job_entry.error_message and len(scan_job_entry.error_message) > 500:
            scan_job_entry.error_message = scan_job_entry.error_message[:497] + "..."
        
        db.session.commit()
        logger.info(f"Scan completed for folder: {folder_path} with ScanJob ID: {scan_job_entry.id}")
    except SQLAlchemyError as e:
        logger.error(f"Database error when finalizing ScanJob: {str(e)}")

    # FIFO: promote next Queued scan once this job is no longer Running/Stopping.
    _drain_scan_queue_safe()
    return scan_job_id


def handle_auto_scan(auto_form):
    logger.info("handle_auto_scan: function running.")
    logger.info(f"Auto-scan form data: {auto_form.data}")
    library_uuid = auto_form.library_uuid.data
    if auto_form.validate_on_submit():
        from flask import request
        from flask_login import current_user
        from oneirodex.utils.scan_queue import (
            normalize_schedule_fields,
            parse_force_parallel,
            parse_queue_policy,
            start_or_queue_scan,
        )

        remove_missing = auto_form.remove_missing.data
        download_missing_images = auto_form.download_missing_images.data
        force_updates_extras_scan = auto_form.force_updates_extras_scan.data
        fetch_hltb = auto_form.fetch_hltb.data
        force_hltb_refetch = auto_form.force_hltb_refetch.data
        schedule = (auto_form.schedule.data or '').strip() or None
        schedule_fields = normalize_schedule_fields(
            schedule,
            interval_value=auto_form.schedule_interval_value.data,
            interval_unit=auto_form.schedule_interval_unit.data,
            cron_expr=auto_form.schedule_cron.data,
        )
        if schedule_fields.get('error'):
            flash(schedule_fields['error'], 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='auto'))

        library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
        if not library:
            logger.warning("Selected library does not exist. Please select a valid library.")
            flash('Selected library does not exist. Please select a valid library.', 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='auto'))

        folder_path = (auto_form.folder_path.data or '').strip()
        scan_mode = auto_form.scan_mode.data
        logger.info(
            f"Auto-scan form submitted. Library: {library.name}, Folder: {folder_path}, "
            f"Scan mode: {scan_mode}, Download missing images: {download_missing_images}"
        )

        allowed_bases = get_allowed_base_directories(current_app)
        if not allowed_bases:
            flash('Service configuration error: No allowed base directories configured.', 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='auto'))

        # folder_path is relative to whichever scan location the admin browsed
        # (the OS base folder unless they picked another declared root).
        from oneirodex.utils.library_roots import resolve_scan_path

        full_path, root_error = resolve_scan_path(
            folder_path, auto_form.library_root.data, current_app,
        )
        if root_error:
            flash(f'Service configuration error: {root_error}', 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='auto'))

        is_safe, error_message = is_safe_path(full_path, allowed_bases)
        if not is_safe:
            logger.warning(f"Security error: Auto-scan path validation failed for {full_path}: {error_message}")
            flash(f"Access denied: {error_message}", 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='auto'))

        if not os.path.exists(full_path) or not os.access(full_path, os.R_OK):
            flash(f"Cannot access folder: {full_path}. Please check the path and permissions.", 'danger')
            logger.warning("Cannot access folder: %s. Check the path and permissions.", full_path)
            session['active_tab'] = 'auto'
            return redirect(url_for('admin2.scan_management', library_uuid=library_uuid, active_tab='auto'))

        force_raw = request.form.get('force_parallel') or request.args.get('force_parallel')
        policy_raw = request.form.get('queue_policy') or request.args.get('queue_policy')
        queue_policy = parse_queue_policy(policy_raw, force_parallel=force_raw)
        is_admin = bool(
            getattr(current_user, 'is_authenticated', False)
            and getattr(current_user, 'role', None) == 'admin'
        )

        scan_mode = resolve_scan_mode_for_path(full_path, auto_form.scan_mode.data)
        logger.info(f"Resolved scan mode for {full_path}: {scan_mode}")

        result = start_or_queue_scan(
            folder_path=full_path,
            library_uuid=library_uuid,
            scan_mode=scan_mode,
            remove_missing=remove_missing,
            download_missing_images=download_missing_images,
            force_updates_extras_scan=force_updates_extras_scan,
            fetch_hltb=fetch_hltb,
            force_hltb_refetch=force_hltb_refetch,
            schedule=schedule,
            schedule_fields=schedule_fields,
            queue_policy=queue_policy,
            allow_force=is_admin,
            app=current_app._get_current_object(),
        )
        flash_cat = 'info' if result['status'] in ('started', 'queued') else 'danger'
        if result['status'] == 'started' and parse_force_parallel(force_raw):
            flash_cat = 'warning'
        flash(result['message'], flash_cat)
        session['active_tab'] = 'auto'
    else:
        flash(f"Auto-scan form validation failed: {auto_form.errors}", 'danger')
        logger.warning(f"Auto-scan form validation failed: {auto_form.errors}")
    return redirect(url_for('admin2.scan_management', library_uuid=library_uuid, active_tab='auto'))



def handle_manual_scan(manual_form):
    session['active_tab'] = 'manual'
    library_uuid = manual_form.library_uuid.data
    if manual_form.validate_on_submit():
        from flask import request
        from flask_login import current_user
        from oneirodex.utils.scan_queue import (
            is_scan_busy,
            parse_force_parallel,
            parse_queue_policy,
            start_or_queue_scan,
        )

        folder_path = (manual_form.folder_path.data or '').strip()
        scan_mode = manual_form.scan_mode.data
        force_updates_extras_scan = manual_form.force_updates_extras_scan.data
        fetch_hltb = manual_form.fetch_hltb.data
        force_hltb_refetch = manual_form.force_hltb_refetch.data

        if not library_uuid:
            flash('Please select a library.', 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='manual'))

        # Store library_uuid in session for use in identify page
        session['selected_library_uuid'] = library_uuid
        logger.info(f"Manual scan: Selected library UUID: {library_uuid}")

        # Validate folder path security
        allowed_bases = get_allowed_base_directories(current_app)
        if not allowed_bases:
            flash('Service configuration error: No allowed base directories configured.', 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='manual'))

        from oneirodex.utils.library_roots import resolve_scan_path

        full_path, root_error = resolve_scan_path(
            folder_path, manual_form.library_root.data, current_app,
        )
        if root_error:
            flash(f'Service configuration error: {root_error}', 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='manual'))
        logger.info(f"Manual scan form submitted. Full path: {full_path}, Library UUID: {library_uuid}")

        # Security validation: ensure the constructed path is within allowed directories
        is_safe, error_message = is_safe_path(full_path, allowed_bases)
        if not is_safe:
            logger.warning(f"Security error: Manual scan path validation failed for {full_path}: {error_message}")
            flash(f"Access denied: {error_message}", 'danger')
            return redirect(url_for('admin2.scan_management', active_tab='manual'))

        if not (os.path.exists(full_path) and os.access(full_path, os.R_OK)):
            flash("Folder does not exist or cannot be accessed.", "danger")
            return redirect(url_for('admin2.scan_management', library_uuid=library_uuid, active_tab='manual'))

        # Busy → same queue contract as Auto Scan (queue by default; admin may force).
        # Idle Manual remains identify "List Games" (does not start a ScanJob).
        if is_scan_busy():
            force_raw = request.form.get('force_parallel') or request.args.get('force_parallel')
            policy_raw = request.form.get('queue_policy') or request.args.get('queue_policy')
            queue_policy = parse_queue_policy(policy_raw, force_parallel=force_raw)
            is_admin = bool(
                getattr(current_user, 'is_authenticated', False)
                and getattr(current_user, 'role', None) == 'admin'
            )
            scan_mode = resolve_scan_mode_for_path(full_path, manual_form.scan_mode.data)
            result = start_or_queue_scan(
                folder_path=full_path,
                library_uuid=library_uuid,
                scan_mode=scan_mode,
                remove_missing=False,
                download_missing_images=False,
                force_updates_extras_scan=force_updates_extras_scan,
                fetch_hltb=fetch_hltb,
                force_hltb_refetch=force_hltb_refetch,
                schedule=None,
                queue_policy=queue_policy,
                allow_force=is_admin,
                app=current_app._get_current_object(),
            )
            flash_cat = 'info' if result['status'] in ('started', 'queued') else 'danger'
            if result['status'] == 'started' and parse_force_parallel(force_raw):
                flash_cat = 'warning'
            flash(result['message'], flash_cat)
            session['active_tab'] = 'manual'
            return redirect(url_for('admin2.scan_management', library_uuid=library_uuid, active_tab='manual'))

        # Check write permissions if local metadata writing is enabled
        from oneirodex.utils.local_metadata import check_library_write_permissions
        settings = global_settings_row()

        if settings and settings.write_local_metadata:
            logger.info(f"🔍 [PERMISSIONS] Checking write permissions for library path: {full_path}")
            all_ok, failed_paths = check_library_write_permissions(full_path)

            if not all_ok:
                logger.warning(f"🚫 [PERMISSIONS] Write permission check failed for {len(failed_paths)} path(s)")
                # Store permission errors in session to show in modal
                session['permission_check_failed'] = True
                session['permission_errors'] = failed_paths
                session['permission_check_path'] = full_path
                flash('Write permission check failed. Please review the permission errors.', 'danger')
                return redirect(url_for('admin2.scan_management', active_tab='manual', show_permissions_modal='true'))

        logger.info("Folder exists and can be accessed.")
        # Idle Manual must resolve Auto the same way the busy path does;
        # otherwise scan_mode stays 'auto' and falls through to files mode.
        scan_mode = resolve_scan_mode_for_path(full_path, manual_form.scan_mode.data)
        logger.info(f"Resolved idle Manual scan mode for {full_path}: {scan_mode}")
        insensitive_patterns, sensitive_patterns = load_scanning_filter_patterns()
        skip_dir_patterns = load_skip_dir_patterns()
        skip_dir_regexes = load_skip_dir_regex_patterns()
        if scan_mode == 'folders':
            lib = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
            scan_depth = getattr(lib, 'scan_depth', 1) or 1 if lib else 1
            games_with_paths = get_game_names_from_folder(
                full_path,
                insensitive_patterns,
                sensitive_patterns,
                scan_depth=scan_depth,
                skip_dir_patterns=skip_dir_patterns,
                skip_dir_regexes=skip_dir_regexes,
            )
        else:  # files mode
            # Load allowed file types from database
            allowed_file_types = db.session.execute(select(AllowedFileType)).scalars().all()
            supported_extensions = [file_type.value for file_type in allowed_file_types]
            if not supported_extensions:
                flash("No allowed file types defined in the database.", "danger")
                return redirect(url_for('admin2.scan_management', active_tab='manual'))

            games_with_paths = get_game_names_from_files(full_path, supported_extensions, insensitive_patterns, sensitive_patterns)
        session['game_paths'] = {game['name']: game['full_path'] for game in games_with_paths}
        session['force_updates_extras_scan'] = force_updates_extras_scan
        session['fetch_hltb'] = fetch_hltb
        session['force_hltb_refetch'] = force_hltb_refetch
        logger.info(f"Found {len(session['game_paths'])} games in the folder.")
        flash('Manual scan processed for folder: ' + full_path, 'info')
    else:
        flash('Manual scan form validation failed.', 'danger')

    logger.debug("Game paths: %s", session.get('game_paths', {}))
    return redirect(url_for('admin2.scan_management', library_uuid=library_uuid, active_tab='manual'))


__all__ = [
    "SCHEDULE_HOURS",
    "compute_next_run",
    "resolve_scan_mode_for_path",
    "_drain_scan_queue_safe",
    "_fail_scan_job_and_drain",
    "scan_and_add_games",
    "_scan_and_add_games_body",
    "handle_auto_scan",
    "handle_manual_scan",
]
