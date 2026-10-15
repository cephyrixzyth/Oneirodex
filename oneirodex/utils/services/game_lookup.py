"""Game existence lookups by path / igdb id / uuid.

Bodies moved verbatim from ``oneirodex/utils/game_core.py`` in wave A2.3.
"""
from sqlalchemy import select
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game
from oneirodex.utils.event_logging import log_system_event
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "check_existing_game_by_path",
    "check_existing_game_by_igdb_id",
    "get_game_by_uuid",
]


def check_existing_game_by_path(full_disk_path):
    """
    Checks if a game already exists in the library by its disk path.

    Parameters:
    - full_disk_path: The full disk path of the game to check.

    Returns:
    - The existing Game object if found, None otherwise.
    """
    existing_game_by_path = db.session.execute(select(Game).filter_by(full_disk_path=full_disk_path)).scalar_one_or_none()
    if existing_game_by_path:
        logger.warning(f"Skipping {existing_game_by_path.name} on {full_disk_path} (path already in library).")
        return existing_game_by_path 
    return None

def check_existing_game_by_igdb_id(igdb_id):
    return db.session.execute(select(Game).filter_by(igdb_id=igdb_id)).scalar_one_or_none()


def get_game_by_uuid(game_uuid):
    log_system_event(
        f"Searching for game UUID: {game_uuid[:8]}...",
        event_type='game',
        event_level='debug'
    )
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none()
    if game:
        log_system_event(
            f"Game '{game.name}' (ID: {game.id}, IGDB: {game.igdb_id}) found for UUID search",
            event_type='game',
            event_level='debug'
        )
        return game
    else:
        log_system_event(
            f"Game not found for UUID: {game_uuid[:8]}...",
            event_type='game',
            event_level='debug'
        )
        return None
