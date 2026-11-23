"""Member-scoped compare-and-swap storage for original room games."""
from datetime import datetime, timezone
import logging

from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from oneirodex.models.room_games import RoomGameProgress
from oneirodex.schemas.room_games import IMPLEMENTED_ROOM_GAMES

log = logging.getLogger(__name__)


class RoomProgressConflict(Exception):
    """Another request changed this member's progress."""


class RoomProgressUnavailable(Exception):
    """Storage failed; no driver detail is safe for an API response."""


class RoomGameProgressData:
    def __init__(self, session=None):
        self._session = session

    @property
    def session(self):
        if self._session is not None:
            return self._session
        from oneirodex.runtime_native.db_session import native_db
        return native_db.session

    @staticmethod
    def _payload(game_id, revision=0, state=None, updated_at=None):
        return {'game_id': game_id, 'revision': revision, 'state': state,
                'updated_at': updated_at.isoformat() if updated_at else None}

    @staticmethod
    def _game(game_id):
        if game_id not in IMPLEMENTED_ROOM_GAMES:
            raise ValueError('Unsupported room game')

    def read(self, user, game_id):
        self._game(game_id)
        try:
            row = self.session.get(RoomGameProgress, (user.id, game_id))
            return self._payload(game_id, row.revision, row.state, row.updated_at) if row else self._payload(game_id)
        except SQLAlchemyError as exc:
            self.session.rollback()
            log.error('Room progress read failed (%s)', type(exc).__name__)
            raise RoomProgressUnavailable() from None

    def write(self, user, game_id, revision, state):
        """Write a prevalidated payload, or clear it while retaining its CAS revision."""
        self._game(game_id)
        if not 0 <= revision < 2_000_000_000:
            raise RoomProgressConflict()
        try:
            if revision == 0 and state is None:
                if self.session.get(RoomGameProgress, (user.id, game_id)) is not None:
                    raise RoomProgressConflict()
                return self._payload(game_id)
            now = datetime.now(timezone.utc)
            values = {'revision': revision + 1, 'state': state, 'updated_at': now}
            if revision == 0:
                self.session.execute(insert(RoomGameProgress).values(user_id=user.id, game_id=game_id, **values))
            else:
                result = self.session.execute(update(RoomGameProgress).where(
                    RoomGameProgress.user_id == user.id,
                    RoomGameProgress.game_id == game_id,
                    RoomGameProgress.revision == revision,
                ).values(**values))
                if result.rowcount != 1:
                    self.session.rollback()
                    raise RoomProgressConflict()
            self.session.commit()
            return self._payload(game_id, revision + 1, state, now)
        except IntegrityError:
            self.session.rollback()
            raise RoomProgressConflict() from None
        except SQLAlchemyError as exc:
            self.session.rollback()
            log.error('Room progress write failed (%s)', type(exc).__name__)
            raise RoomProgressUnavailable() from None
