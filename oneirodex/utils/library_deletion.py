"""Background library-deletion worker and shared progress state."""
from __future__ import annotations

import logging

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Library, ScanJob
from oneirodex.utils.background import run_in_background

logger = logging.getLogger(__name__)
deletion_progress = {}

def delete_library_background(library_uuid, job_id, *, app=None, database_scope=None):
    """Background task for deleting a library with progress updates.

    Runs in its own application context, and therefore its own session. It used
    to run in a copy of the caller's request context, sharing the request's
    session while deleting every game in the library — the longest-running and
    most destructive of the workers that did that. Only the two ids cross into
    the thread; the library is re-fetched below.
    """
    def delete_task():
        import time
        from oneirodex.utils.services.game_delete import delete_game
        try:
            library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalar_one_or_none()
            if not library:
                deletion_progress[job_id] = {
                    'status': 'error',
                    'message': 'Library not found',
                    'current': 0,
                    'total': 0
                }
                return

            logger.info(f"Background deletion of library: {library.name}")

            # Update progress - starting (give UI time to connect)
            deletion_progress[job_id].update({
                'status': 'starting',
                'message': f'Preparing to delete library "{library.name}"...',
                'current': 0,
                'total': 0
            })

            # Small delay to allow EventSource to connect
            time.sleep(0.5)

            # Safety check: Cancel any running scan jobs for this library first
            running_scan_jobs = db.session.execute(
                select(ScanJob).filter_by(library_uuid=library.uuid, status='Running')
            ).scalars().all()

            for running_job in running_scan_jobs:
                running_job.status = 'Failed'
                running_job.error_message = 'Scan cancelled due to library deletion'
                running_job.is_enabled = False
                logger.info(f"Cancelled running scan job: {running_job.id}")

            if running_scan_jobs:
                db.session.commit()  # Commit the cancellation first
                logger.info(f"Cancelled {len(running_scan_jobs)} running scan jobs before library deletion")

            # Get all games to delete
            games_to_delete = db.session.execute(select(Game).filter_by(library_uuid=library.uuid)).scalars().all()
            total_games = len(games_to_delete)
            games_deleted = 0
            games_failed = 0

            deletion_progress[job_id].update({
                'status': 'deleting_games',
                'total': total_games,
                'current': 0
            })

            # Delete games with progress updates
            for i, game in enumerate(games_to_delete, 1):
                try:
                    # Update progress
                    deletion_progress[job_id].update({
                        'current': i,
                        'message': f'Deleting game {i}/{total_games}',
                        'current_game': game.name
                    })

                    # Use the existing delete_game function which handles all related data
                    delete_game(game.uuid, config=app.config)
                    games_deleted += 1
                    logger.info(f'Successfully deleted game: {game.name}')

                except FileNotFoundError as fnfe:
                    logger.warning(f'File not found for game {game.name} (UUID: {game.uuid}): {fnfe}')
                    games_deleted += 1  # Still count as deleted since it's not blocking
                except Exception as e:
                    logger.error(f'Error deleting game {game.name} (UUID: {game.uuid}): {e}')
                    games_failed += 1
                    # Continue with other games instead of stopping

            # Update progress - cleaning up
            deletion_progress[job_id].update({
                'status': 'cleanup',
                'message': 'Cleaning up scan jobs and library data...',
                'current': total_games,
                'total': total_games
            })

            # Delete scan jobs related to this library
            scan_jobs = db.session.execute(select(ScanJob).filter_by(library_uuid=library.uuid)).scalars().all()
            for scan_job in scan_jobs:
                try:
                    db.session.delete(scan_job)
                    logger.info(f'Deleted scan job: {scan_job.id}')
                except Exception as e:
                    logger.error(f'Error deleting scan job {scan_job.id}: {e}')

            # Finally delete the library itself
            library_name = library.name
            db.session.delete(library)

            # Commit all changes
            db.session.commit()

            # Update progress - completed
            if games_failed == 0:
                message = f'Library "{library_name}" and all {games_deleted} games have been deleted successfully.'
            else:
                message = f'Library "{library_name}" deleted. {games_deleted} games deleted successfully, {games_failed} failed.'

            deletion_progress[job_id] = {
                'status': 'completed',
                'message': message,
                'current': total_games,
                'total': total_games,
                'games_deleted': games_deleted,
                'games_failed': games_failed,
                'library_name': library_name
            }

        except Exception as e:
            db.session.rollback()
            error_msg = f"Error during library deletion: {str(e)}"
            logger.error(error_msg)
            deletion_progress[job_id] = {
                'status': 'error',
                'message': error_msg,
                'current': 0,
                'total': 0
            }

    # Start the background task
    if app is None and database_scope is None:
        from flask import current_app

        app = current_app._get_current_object()
    return run_in_background(
        app,
        delete_task,
        name=f'oneirodex-delete-library-{str(library_uuid)[:8]}',
        database_scope=database_scope,
    )


def start_library_delete_job(
    library, *, app=None, worker=None, progress=None, database_scope=None,
):
    """Initialize progress and launch the established delete worker."""
    from uuid import uuid4

    worker = worker or delete_library_background
    progress = deletion_progress if progress is None else progress
    job_id = str(uuid4())
    progress[job_id] = {
        'status': 'initializing',
        'message': f'Preparing to delete library "{library.name}"...',
        'current': 0,
        'total': 0,
        'library_name': library.name,
        'library_uuid': library.uuid,
    }
    if app is None:
        worker(library.uuid, job_id, database_scope=database_scope)
    else:
        worker(library.uuid, job_id, app=app, database_scope=database_scope)
    return job_id
