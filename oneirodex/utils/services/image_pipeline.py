"""IGDB image store / process / download pipeline + background downloaders.

Bodies moved verbatim from ``oneirodex/utils/game_core.py`` in wave A2.3.
"""
import os
import time
import threading
from contextlib import nullcontext
from datetime import datetime, UTC
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select, update
from werkzeug.utils import secure_filename
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Image, Game
from oneirodex.utils.image_kinds import IGDB_DOWNLOAD_KINDS
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.worker_caps import (
    clamp_image_download_batch,
    clamp_image_download_threads,
    cooperative_yield,
)
import logging

logger = logging.getLogger(__name__)


def _current_app():
    """Load Flask's context proxy only when a legacy path needs it."""
    from flask import current_app

    return current_app


def normalize_igdb_image_ref(*args, **kwargs):
    from oneirodex.utils.clients.igdb import normalize_igdb_image_ref as resolve

    return resolve(*args, **kwargs)


def _resolve_igdb_download_url(*args, **kwargs):
    from oneirodex.utils.clients.igdb import _resolve_igdb_download_url as resolve

    return resolve(*args, **kwargs)


def download_image(*args, **kwargs):
    from oneirodex.utils.clients.images import download_image as download

    return download(*args, **kwargs)


def download_stored_image(*args, **kwargs):
    from oneirodex.utils.clients.images import download_stored_image as download

    return download(*args, **kwargs)


def cover_title_for_uuid(*args, **kwargs):
    from oneirodex.utils.clients.images import cover_title_for_uuid as title_for_uuid

    return title_for_uuid(*args, **kwargs)

__all__ = [
    "store_image_url_for_download",
    "smart_process_images_for_game",
    "download_images_for_game_turbo",
    "process_and_save_image",
    "download_pending_images",
    "start_background_image_downloader",
    "download_images_for_game",
    "download_single_image_worker",
    "turbo_download_images",
    "start_turbo_background_downloader",
    "find_missing_images_for_library",
    "queue_missing_images_for_download",
    "process_missing_images_for_scan",
]


def store_image_url_for_download(game_uuid, image_data, image_type='cover'):
    """Store image URL in database for later async download.

    Accepts a bare IGDB image id, an expanded ``{id, url}`` dict, or a remote URL
    string. Always persists a row when a download URL can be resolved so the UI
    can show the remote cover before the local file lands.
    """
    try:
        image_id, known_url = normalize_igdb_image_ref(image_data)
        if image_type not in IGDB_DOWNLOAD_KINDS:
            logger.info(f"Unsupported image_type for store: {image_type}")
            return

        download_url = _resolve_igdb_download_url(image_id, image_type, known_url=known_url)
        if not download_url:
            logger.error(f"Failed to resolve download URL for {image_type} ref {image_data!r}.")
            return

        id_part = image_id if image_id is not None else 'url'
        file_name = secure_filename(f"{game_uuid}_{image_type}_{id_part}.jpg")

        image = Image(
            game_uuid=game_uuid,
            image_type=image_type,
            url=file_name,
            igdb_image_id=str(image_id) if image_id is not None else None,
            download_url=download_url,
            is_downloaded=False,
            last_error=None,
        )
        db.session.add(image)

    except Exception as e:
        logger.error(f"Error storing image URL for {image_type} {image_data}: {e}")


def smart_process_images_for_game(
    game_uuid,
    cover_data=None,
    screenshots_data=None,
    app=None,
    database_scope=None,
    download_immediately=True,
):
    """Smart image processing that uses settings to determine single-thread vs turbo mode.

    When download_immediately is False, only IGDB image URLs are stored (is_downloaded=False)
    so a background worker can fetch files later without blocking identify.

    Cover and screenshot refs may be bare IGDB ids or expanded ``{id, url}`` objects.
    """
    if app is None:
        app = _current_app()._get_current_object()
    
    try:
        scope = database_scope(app) if database_scope else nullcontext()
        app_scope = app.app_context() if database_scope is None else nullcontext()
        with app_scope, scope:
            # Get settings to determine processing mode
            from oneirodex.models import GlobalSettings
            from oneirodex.utils.cover_selection import image_save_path_status

            settings = global_settings_row()
            
            # Store image URLs first (always) — cover must not be skipped when
            # IGDB returns an expanded object instead of a bare id.
            if cover_data is not None:
                store_image_url_for_download(game_uuid, cover_data, 'cover')
            if screenshots_data:
                for screenshot_ref in screenshots_data:
                    if screenshot_ref is not None:
                        store_image_url_for_download(game_uuid, screenshot_ref, 'screenshot')
            db.session.commit()

            if not download_immediately:
                return 0

            path_status = (
                image_save_path_status(app.config)
                if database_scope is not None else image_save_path_status()
            )
            if not path_status.get('writable'):
                err = path_status.get('error') or 'IMAGE_SAVE_PATH is not writable'
                now = datetime.now(UTC)
                pending = db.session.execute(
                    select(Image).filter_by(game_uuid=game_uuid, is_downloaded=False)
                ).scalars().all()
                for image in pending:
                    image.last_error = err
                    image.last_attempt_at = now
                if pending:
                    db.session.commit()
                logger.warning(f"Skipping eager image download for {game_uuid}: {err}")
                # Remote download_url remains on each row for resolve_cover_url.
                return 0
            
            # Decide processing mode based on settings
            if settings and settings.use_turbo_image_downloads:
                # TURBO MODE - Download immediately with parallel processing
                threads = clamp_image_download_threads(
                    settings.turbo_download_threads or 4
                )
                download_kwargs = {'max_workers': threads}
                if database_scope is not None:
                    download_kwargs['database_scope'] = database_scope
                return download_images_for_game_turbo(game_uuid, app, **download_kwargs)
            else:
                # SINGLE THREAD MODE - Download one by one
                logger.warning(f"🐌 SINGLE THREAD: Processing images for game {game_uuid}")
                if database_scope is None:
                    return download_images_for_game(game_uuid, app)
                return download_images_for_game(
                    game_uuid, app, database_scope=database_scope,
                )
                
    except Exception as e:
        logger.error(f"Error in smart image processing for game {game_uuid}: {e}")
        return 0


def download_images_for_game_turbo(game_uuid, app=None, max_workers=5, database_scope=None):
    """Download all pending images for a specific game using turbo mode."""
    if app is None:
        app = _current_app()._get_current_object()
    max_workers = clamp_image_download_threads(max_workers)

    try:
        scope = database_scope(app) if database_scope else nullcontext()
        app_scope = app.app_context() if database_scope is None else nullcontext()
        with app_scope, scope:
            pending_images = db.session.execute(select(Image).filter_by(game_uuid=game_uuid, is_downloaded=False)).scalars().all()
            
            if not pending_images:
                logger.info(f"No pending images for game {game_uuid}.")
                return 0
            
            downloaded_count = 0
            successful_images = []
            failed_images = {}
            now = datetime.now(UTC)
            
            # Use ThreadPoolExecutor for parallel downloads
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_image = {
                    executor.submit(download_single_image_worker, image, app): image 
                    for image in pending_images
                }
                
                for future in as_completed(future_to_image):
                    image = future_to_image[future]
                    try:
                        result = future.result()
                        if result['success']:
                            successful_images.append(image.id)
                            downloaded_count += 1
                        else:
                            failed_images[image.id] = result.get('error') or 'Download failed for an unknown reason.'
                    except Exception as e:
                        logger.error(f"❌ Failed downloading image {image.id}: {e}")
                        failed_images[image.id] = str(e)
                    cooperative_yield()
            
            # Update database
            if successful_images:
                db.session.execute(
                    update(Image).filter(Image.id.in_(successful_images)).values(
                        is_downloaded=True, last_error=None, last_attempt_at=now
                    )
                )
            for image_id, error in failed_images.items():
                db.session.execute(
                    update(Image).filter(Image.id == image_id).values(last_error=error, last_attempt_at=now)
                )
            if successful_images or failed_images:
                db.session.commit()
            
            logger.info(f"🚀 Downloaded {downloaded_count} images for game {game_uuid[:8]}... ({len(failed_images)} failed)")
            return downloaded_count
            
    except Exception as e:
        logger.error(f"Error in turbo download for game {game_uuid}: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return 0


def process_and_save_image(game_uuid, image_data, image_type='cover', *, app=None):
    """Fetch (or reuse) an IGDB image URL, download it, and persist an Image row.

    ``image_data`` may be a bare id or an expanded ``{id, url}`` dict. When the
    dict already carries ``url``, skip the extra IGDB lookup so cover is not
    dropped under rate limits while screenshots still land.
    """
    from oneirodex.utils.cover_selection import image_save_path_status

    if app is None:
        app = _current_app()._get_current_object()

    image_id, known_url = normalize_igdb_image_ref(image_data)
    if image_type not in IGDB_DOWNLOAD_KINDS:
        logger.info(f"Unsupported image_type: {image_type}")
        return

    url = _resolve_igdb_download_url(image_id, image_type, known_url=known_url)
    if not url:
        logger.error(f"Failed to resolve URL for {image_type} ref {image_data!r}.")
        return

    id_part = image_id if image_id is not None else 'url'
    file_name = secure_filename(f"{game_uuid}_{image_type}_{id_part}.jpg")
    save_path = os.path.join(app.config['IMAGE_SAVE_PATH'], file_name)

    path_status = image_save_path_status(app.config)
    if not path_status.get('writable'):
        error = path_status.get('error') or 'IMAGE_SAVE_PATH is not writable'
        image = Image(
            game_uuid=game_uuid,
            image_type=image_type,
            url=file_name,
            igdb_image_id=str(image_id) if image_id is not None else None,
            download_url=url,
            is_downloaded=False,
            last_error=error,
            last_attempt_at=datetime.now(UTC),
        )
        db.session.add(image)
        logger.error(f"Queued {image_type} for game {game_uuid} without download: {error}")
        return

    success, error = download_image(
        url,
        save_path,
        image_type=image_type,
        title=cover_title_for_uuid(game_uuid),
    )

    image = Image(
        game_uuid=game_uuid,
        image_type=image_type,
        url=file_name,
        igdb_image_id=str(image_id) if image_id is not None else None,
        download_url=url,
        is_downloaded=success,
        last_error=None if success else (error or 'Download failed for an unknown reason.'),
        last_attempt_at=datetime.now(UTC),
    )
    db.session.add(image)
    if not success:
        logger.error(f"Failed to download {image_type} for game {game_uuid}: {image.last_error}")



def download_pending_images(
    batch_size=10, delay_between_downloads=1, app=None, *, use_app_context=True,
):
    """Download images that are queued but not yet downloaded."""
    if app is None:
        app = _current_app()._get_current_object()
        
    try:
        with app.app_context():
            # Get pending images
            pending_images = db.session.execute(select(Image).filter_by(is_downloaded=False).limit(batch_size)).scalars().all()
            
            if not pending_images:
                logger.info("No pending images to download.")
                return 0
            
            downloaded_count = 0
            failed_count = 0
            for image in pending_images:
                try:
                    image.last_attempt_at = datetime.now(UTC)

                    if not image.download_url:
                        image.last_error = 'No download URL on record for this image.'
                        failed_count += 1
                        logger.warning(f"No download URL for image {image.id}, skipping.")
                        continue

                    # Download the image
                    save_path = os.path.join(app.config['IMAGE_SAVE_PATH'], image.url)

                    success, error = download_stored_image(image, save_path)

                    if success:
                        image.is_downloaded = True
                        image.last_error = None
                        downloaded_count += 1
                        logger.info(f"Downloaded {image.image_type} for game {image.game_uuid}: {image.url}")
                    else:
                        image.last_error = error or 'Download failed for an unknown reason.'
                        failed_count += 1
                        logger.error(f"Failed to download image {image.id}: {image.last_error}")

                    # Small delay to avoid overwhelming the server
                    if delay_between_downloads > 0:
                        time.sleep(delay_between_downloads)
                        
                except Exception as e:
                    image.last_error = f"Unexpected error: {e}"
                    failed_count += 1
                    logger.error(f"Error downloading image {image.id}: {e}")
                    continue
            
            # Commit all changes
            db.session.commit()
            logger.info(f"Downloaded {downloaded_count} images ({failed_count} failed).")
            return downloaded_count
            
    except Exception as e:
        logger.error(f"Error in batch image download: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return 0


def start_background_image_downloader(interval_seconds=60):
    """Start a background thread that periodically downloads pending images."""
    # Capture the current app instance
    app = _current_app()._get_current_object()
    
    def background_worker():
        from oneirodex.utils.shutdown import should_continue_processing, sleep_interruptible
        while should_continue_processing():
            try:
                download_pending_images(batch_size=20, delay_between_downloads=0.5, app=app)
                # Use interruptible sleep to allow quick shutdown
                if not sleep_interruptible(interval_seconds):
                    break  # Shutdown requested during sleep
            except Exception as e:
                logger.error(f"Background image downloader error: {e}")
                if not sleep_interruptible(interval_seconds):
                    break  # Shutdown requested during error sleep
        logger.warning("🛑 Background image downloader stopped due to shutdown request")
    
    thread = threading.Thread(target=background_worker, daemon=True)
    thread.start()
    logger.info(f"Background image downloader started (interval: {interval_seconds}s)")
    return thread


def download_images_for_game(game_uuid, app=None, database_scope=None):
    """Download all pending images for a specific game immediately."""
    if app is None:
        app = _current_app()._get_current_object()
        
    try:
        scope = database_scope(app) if database_scope else nullcontext()
        app_scope = app.app_context() if database_scope is None else nullcontext()
        with app_scope, scope:
            pending_images = db.session.execute(select(Image).filter_by(game_uuid=game_uuid, is_downloaded=False)).scalars().all()
            
            if not pending_images:
                logger.info(f"No pending images for game {game_uuid}.")
                return 0
            
            downloaded_count = 0
            for image in pending_images:
                try:
                    image.last_attempt_at = datetime.now(UTC)

                    if not image.download_url:
                        image.last_error = 'No download URL on record for this image.'
                        continue

                    save_path = os.path.join(app.config['IMAGE_SAVE_PATH'], image.url)

                    success, error = download_stored_image(image, save_path)

                    if success:
                        image.is_downloaded = True
                        image.last_error = None
                        downloaded_count += 1
                    else:
                        image.last_error = error or 'Download failed for an unknown reason.'
                        logger.error(f"Failed to download image {image.id}: {image.last_error}")

                except Exception as e:
                    image.last_error = f"Unexpected error: {e}"
                    logger.error(f"Error downloading image {image.id}: {e}")
                    continue
            
            db.session.commit()
            logger.info(f"Downloaded {downloaded_count} images for game {game_uuid}.")
            return downloaded_count
            
    except Exception as e:
        logger.error(f"Error downloading images for game {game_uuid}: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return 0


def download_single_image_worker(image, app, title=None):
    """Worker function to download a single image - designed for parallel execution."""
    try:
        if not image.download_url:
            return {'success': False, 'image_id': image.id, 'error': 'No download URL on record for this image.'}

        save_path = os.path.join(app.config['IMAGE_SAVE_PATH'], image.url)

        success, error = download_image(
            image.download_url,
            save_path,
            image_type=image.image_type,
            title=title,
        )

        if not success:
            return {'success': False, 'image_id': image.id, 'error': error or 'Download failed for an unknown reason.'}

        return {
            'success': True, 
            'image_id': image.id, 
            'game_uuid': image.game_uuid,
            'image_type': image.image_type,
            'url': image.url
        }
        
    except Exception as e:
        return {'success': False, 'image_id': image.id, 'error': str(e)}


def turbo_download_images(batch_size=100, max_workers=5, app=None):
    """MAXIMUM SPEED parallel image downloading with multiple threads."""
    if app is None:
        app = _current_app()._get_current_object()
    max_workers = clamp_image_download_threads(max_workers)
    batch_size = clamp_image_download_batch(batch_size)

    try:
        with app.app_context():
            # Get pending images
            pending_images = db.session.execute(select(Image).filter_by(is_downloaded=False).limit(batch_size)).scalars().all()
            
            if not pending_images:
                return {'downloaded': 0, 'failed': 0, 'message': 'No pending images'}
            
            downloaded_count = 0
            failed_count = 0
            successful_images = []
            failed_images = {}
            now = datetime.now(UTC)
            
            titles = {
                g.uuid: g.name
                for g in db.session.execute(
                    select(Game).filter(
                        Game.uuid.in_({img.game_uuid for img in pending_images})
                    )
                ).scalars()
            }

            # Create thread pool and submit all download tasks
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all download jobs
                future_to_image = {
                    executor.submit(
                        download_single_image_worker,
                        image,
                        app,
                        titles.get(image.game_uuid),
                    ): image
                    for image in pending_images
                }
                
                # Process completed downloads as they finish
                for future in as_completed(future_to_image):
                    image = future_to_image[future]
                    try:
                        result = future.result()
                        
                        if result['success']:
                            successful_images.append(image.id)
                            downloaded_count += 1
                        else:
                            failed_count += 1
                            failed_images[image.id] = result.get('error') or 'Download failed for an unknown reason.'
                            logger.error(f"❌ Failed to download image {result['image_id']}: {result['error']}")
                            
                    except Exception as e:
                        failed_count += 1
                        failed_images[image.id] = str(e)
                        logger.error(f"❌ Exception downloading image {image.id}: {e}")
            
            # Update database - mark successful downloads as completed
            if successful_images:
                db.session.execute(
                    update(Image).filter(Image.id.in_(successful_images)).values(
                        is_downloaded=True, last_error=None, last_attempt_at=now
                    )
                )
            for image_id, error in failed_images.items():
                db.session.execute(
                    update(Image).filter(Image.id == image_id).values(last_error=error, last_attempt_at=now)
                )
            if successful_images or failed_images:
                db.session.commit()
            
            result_message = f"🚀 Downloaded {downloaded_count} images ({failed_count} failed)" if failed_count > 0 else f"🚀 Downloaded {downloaded_count} images"
            if downloaded_count > 0:
                logger.info(result_message)
            
            return {
                'downloaded': downloaded_count,
                'failed': failed_count,
                'message': result_message
            }
            
    except Exception as e:
        logger.error(f"Error in turbo download: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return {'downloaded': 0, 'failed': 0, 'message': f'Error: {str(e)}'}


def start_turbo_background_downloader(interval_seconds=30, max_workers=4, batch_size=50):
    """Start a HIGH SPEED background downloader with parallel processing."""
    app = _current_app()._get_current_object()
    max_workers = clamp_image_download_threads(max_workers)
    batch_size = clamp_image_download_batch(batch_size)

    def turbo_background_worker():
        from oneirodex.utils.shutdown import should_continue_processing, sleep_interruptible
        logger.info(f"🔥 TURBO BACKGROUND DOWNLOADER STARTED - {max_workers} workers, {batch_size} batch, {interval_seconds}s interval")
        while should_continue_processing():
            try:
                result = turbo_download_images(batch_size=batch_size, max_workers=max_workers, app=app)
                if result['downloaded'] > 0:
                    logger.info(f"🚀 Background turbo download: {result['message']}")
                # Use interruptible sleep to allow quick shutdown
                if not sleep_interruptible(interval_seconds):
                    break  # Shutdown requested during sleep
            except Exception as e:
                logger.error(f"Turbo background downloader error: {e}")
                if not sleep_interruptible(interval_seconds):
                    break  # Shutdown requested during error sleep
        logger.warning("🛑 Turbo background downloader stopped due to shutdown request")
    
    thread = threading.Thread(target=turbo_background_worker, daemon=True)
    thread.start()
    logger.info("🔥 TURBO BACKGROUND DOWNLOADER LAUNCHED!")
    return thread


def find_missing_images_for_library(library_uuid=None, app=None):
    """
    Find all images that have URLs in the database but are missing from disk.
    
    Parameters:
    - library_uuid: UUID of library to check (optional, checks all games if None)
    - app: Flask app context (optional)
    
    Returns:
    - Dictionary with statistics and list of missing images
    """
    if app is None:
        app = _current_app()._get_current_object()
    
    try:
        with app.app_context():
            # Build query based on library filter
            if library_uuid:
                images_query = select(Image).join(Game).filter(Game.library_uuid == library_uuid)
                logger.info(f"🔍 Checking for missing images in library {library_uuid}")
            else:
                images_query = select(Image)
                logger.info("🔍 Checking for missing images across all libraries")
            
            # Get all images with download URLs
            all_images = db.session.execute(images_query.filter(Image.download_url.isnot(None))).scalars().all()
            
            if not all_images:
                logger.info("No images with download URLs found in database.")
                return {
                    'total_checked': 0,
                    'missing_count': 0,
                    'missing_images': [],
                    'already_queued': 0
                }
            
            logger.info(f"📊 Found {len(all_images)} images to check")
            
            missing_images = []
            already_queued_count = 0
            
            for image in all_images:
                try:
                    # Check if image is already marked as not downloaded (already in queue)
                    if not image.is_downloaded:
                        already_queued_count += 1
                        continue
                    
                    # Build expected file path
                    image_save_path = os.path.join(app.config['IMAGE_SAVE_PATH'], image.url)
                    
                    # Check if file exists on disk
                    if not os.path.exists(image_save_path):
                        missing_images.append({
                            'id': image.id,
                            'game_uuid': image.game_uuid,
                            'image_type': image.image_type,
                            'url': image.url,
                            'download_url': image.download_url,
                            'file_path': image_save_path
                        })
                        logger.error(f"❌ Missing: {image.image_type} for game {image.game_uuid}: {image.url}")
                    
                except Exception as e:
                    logger.error(f"Error checking image {image.id}: {e}")
                    continue
            
            result = {
                'total_checked': len(all_images),
                'missing_count': len(missing_images),
                'missing_images': missing_images,
                'already_queued': already_queued_count
            }
            
            logger.info(f"📈 Missing images summary: {len(missing_images)} missing, {already_queued_count} already queued, {len(all_images)} total checked")
            return result
            
    except Exception as e:
        logger.error(f"Error in find_missing_images_for_library: {e}")
        return {
            'total_checked': 0,
            'missing_count': 0,
            'missing_images': [],
            'already_queued': 0,
            'error': str(e)
        }


def queue_missing_images_for_download(missing_images_list, app=None):
    """
    Mark missing images as not downloaded so they get picked up by the download queue.
    
    Parameters:
    - missing_images_list: List of missing image dictionaries from find_missing_images_for_library
    - app: Flask app context (optional)
    
    Returns:
    - Number of images successfully queued
    """
    if app is None:
        app = _current_app()._get_current_object()
    
    if not missing_images_list:
        logger.info("No missing images to queue.")
        return 0
    
    try:
        with app.app_context():
            queued_count = 0
            image_ids = [img['id'] for img in missing_images_list]
            
            # Update images to mark them as not downloaded (queued for download)
            db.session.execute(
                update(Image).filter(Image.id.in_(image_ids)).values(is_downloaded=False)
            )
            updated_count = len(image_ids)
            
            db.session.commit()
            queued_count = updated_count
            
            logger.info(f"📥 Successfully queued {queued_count} missing images for download")
            
            # Trigger immediate download if turbo mode is enabled
            settings = global_settings_row()
            if settings and settings.use_turbo_image_downloads:
                logger.info("🚀 Turbo mode enabled - triggering immediate download")
                # Run a small batch download to start processing immediately
                download_result = turbo_download_images(
                    batch_size=min(20, queued_count),
                    max_workers=clamp_image_download_threads(
                        settings.turbo_download_threads or 4
                    ),
                    app=app
                )
                logger.info(f"⚡ Quick download result: {download_result.get('message', 'Download initiated')}")
            
            return queued_count
            
    except Exception as e:
        logger.error(f"Error queuing missing images: {e}")
        try:
            db.session.rollback()
        except:
            pass
        return 0


def process_missing_images_for_scan(library_uuid=None, app=None):
    """
    Complete workflow to find and queue missing images for download during scan.
    
    Parameters:
    - library_uuid: UUID of library to process (optional, processes all if None)
    - app: Flask app context (optional)
    
    Returns:
    - Dictionary with results summary
    """
    if app is None:
        app = _current_app()._get_current_object()
    
    logger.info(f"🔍 Starting missing images processing for library: {library_uuid or 'ALL'}")
    
    # Step 1: Find missing images
    missing_result = find_missing_images_for_library(library_uuid, app)
    
    if missing_result.get('error'):
        return {
            'success': False,
            'error': missing_result['error'],
            'found': 0,
            'queued': 0
        }
    
    # Step 2: Queue missing images if any found
    queued_count = 0
    if missing_result['missing_count'] > 0:
        queued_count = queue_missing_images_for_download(missing_result['missing_images'], app)
    
    result = {
        'success': True,
        'total_checked': missing_result['total_checked'],
        'found': missing_result['missing_count'],
        'queued': queued_count,
        'already_queued': missing_result['already_queued'],
        'message': f"Found {missing_result['missing_count']} missing images, queued {queued_count} for download"
    }
    
    logger.info(f"✅ Missing images processing complete: {result['message']}")
    return result
