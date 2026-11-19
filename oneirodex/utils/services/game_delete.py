"""Library game removal + hard delete.

Bodies moved verbatim from ``oneirodex/utils/game_core.py`` in wave A2.3.
"""
import uuid
from sqlalchemy import delete, func, select, update
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, GameURL, Image, ScanJob, game_developer_association
from oneirodex.utils.helpers.counts import delete_associations_for_game
from oneirodex.utils.user_deletion import enqueue_game_image_cleanup, process_pending_file_jobs
from oneirodex.utils.event_logging import log_system_event
import logging

logger = logging.getLogger(__name__)

__all__ = ["remove_from_lib", "delete_game"]


def remove_from_lib(game_uuid, *, config=None, scan_job_id=None):
    """Boolean-returning scan adapter for the shared atomic delete."""
    try:
        delete_game(game_uuid, config=config, scan_job_id=scan_job_id)
    except Exception:
        logger.exception("Could not remove game %s", game_uuid)
        return False
    try:
        log_system_event(f'Game deleted (UUID: {game_uuid})', event_type='game', event_level='information')
    except Exception:
        logger.warning("Could not record completed game deletion", exc_info=True)
    return True


def delete_game(game_identifier, *, config=None, scan_job_id=None):
    """Delete a game by UUID or Game object.""" 
    game_to_delete = None
    if isinstance(game_identifier, Game):
        game_to_delete = game_identifier
        game_uuid_str = game_to_delete.uuid
    else:
        try:
            # Parse without forcing version=4: uuid.UUID(x, version=4) rewrites the
            # version/variant bits, so a non-v4 UUID would be looked up under a
            # different string and never be found.
            game_uuid_str = str(uuid.UUID(game_identifier))
        except (ValueError, AttributeError, TypeError):
            logger.info(f"Invalid UUID format: {game_identifier}")
            from werkzeug.exceptions import NotFound
            raise NotFound()
        game_to_delete = db.session.execute(select(Game).filter_by(uuid=game_uuid_str)).scalar_one_or_none()
        if game_to_delete is None:
            logger.info(f"No game found with UUID {game_uuid_str}")
            from werkzeug.exceptions import NotFound
            raise NotFound()

    try:
        logger.info(f"Found game to delete: {game_to_delete}")
        db.session.execute(delete(GameURL).filter_by(game_uuid=game_uuid_str))
        delete_associations_for_game(game_to_delete)
        # game_developer_association has a FK to games but no relationship on the
        # Game model, so the ORM never clears it. Rows left here (from older
        # schema versions) block the delete with a FK violation.
        db.session.execute(
            game_developer_association.delete().where(
                game_developer_association.c.game_id == game_to_delete.id
            )
        )
        urls = list(db.session.scalars(select(Image.url).where(Image.game_uuid == game_uuid_str)))
        if game_to_delete.cover:
            urls.append(game_to_delete.cover)
        db.session.execute(delete(Image).where(Image.game_uuid == game_uuid_str))
        db.session.delete(game_to_delete)
        db.session.flush()
        if urls:
            if config is None:
                from oneirodex.utils.runtime_config import get_runtime_config
                config = get_runtime_config()
            enqueue_game_image_cleanup(db.session, urls, config['IMAGE_SAVE_PATH'])
        if scan_job_id is not None:
            counted = db.session.execute(
                update(ScanJob).where(ScanJob.id == scan_job_id, ScanJob.status == 'Running',
                                      ScanJob.is_enabled.is_(True))
                .values(removed_count=func.coalesce(ScanJob.removed_count, 0) + 1)
            )
            if counted.rowcount != 1:
                raise RuntimeError('Scan cancelled before removal')
        db.session.commit()
        logger.info(f'Deleted game with UUID: {game_uuid_str}')
    except Exception as e:
        db.session.rollback()
        logger.error(f'Error deleting game with UUID {game_uuid_str}: {e}')
        try:
            from flask import flash, has_request_context

            if has_request_context():
                flash(f'Error deleting game: {e}', 'error')
        except ImportError:
            pass
        # Re-raise so the caller reports the real failure. Swallowing this made
        # /delete_game return "success" while the game was still in the library.
        raise
    if urls:
        try:
            process_pending_file_jobs(db.session)
        except Exception:
            db.session.rollback()
            logger.warning("Game was deleted; artwork cleanup will be retried", exc_info=True)
