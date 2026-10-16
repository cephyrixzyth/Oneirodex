"""Library game removal + hard delete.

Bodies moved verbatim from ``oneirodex/utils/game_core.py`` in wave A2.3.
"""
import uuid
from sqlalchemy import select, delete
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, GameURL, game_developer_association
from oneirodex.utils.helpers.counts import delete_associations_for_game
from oneirodex.utils.scanning import delete_game_images
from oneirodex.utils.event_logging import log_system_event
import logging

logger = logging.getLogger(__name__)

__all__ = ["remove_from_lib", "delete_game"]


def remove_from_lib(game_uuid, *, config=None):
    """
    Remove a game from the library and clean up associated files.
    
    Args:
        game_uuid (str): UUID of the game to remove
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get the game
        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
        if not game:
            logger.warning(f"Game with UUID {game_uuid} not found")
            return False
            
        # Delete associated images from disk
        # Scan workers in the Flask-free ASGI runtime already have the active
        # native database scope, but no Flask application context. Passing the
        # runtime config keeps image cleanup on the same context-free path.
        delete_game_images(game_uuid, config=config)
        
        # Delete the game (cascade will handle related records)
        db.session.delete(game)
        db.session.commit()
        
        log_system_event(f"Game deleted: {game.name} (UUID: {game_uuid})", event_type='game', event_level='information')
        logger.info(f"Successfully removed game {game.name} (UUID: {game_uuid}) from library")
        return True
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error removing game from library: {str(e)}")
        return False
    

def delete_game(game_identifier, *, config=None):
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
        delete_game_images(game_uuid_str, config=config)
        db.session.delete(game_to_delete)
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
