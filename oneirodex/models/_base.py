"""Shared model primitives: the JSON TypeDecorator and cross-domain
association tables that both :mod:`catalog` and :mod:`users` reference."""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.types import TypeDecorator, TEXT

from oneirodex.models.orm import db

logger = logging.getLogger(__name__)


class JSONEncodedDict(TypeDecorator):
    """JSON stored as TEXT (serialised in Python, not by the database).

    The previous version ``print()``-ed on a (de)serialisation error and then
    handed back a silent ``None`` / ``{}``, so a bad write looked like a
    successful one and a corrupt row read as empty. It now logs at ERROR with
    the offending value's type; a serialisation failure on write re-raises
    rather than persisting NULL in place of the caller's data. A malformed
    value already in the column still degrades to ``{}`` on read (loudly), so
    one bad row cannot take a page down.
    """

    impl = TEXT

    def process_bind_param(self, value, dialect):
        if value is not None:
            try:
                return json.dumps(value)
            except (TypeError, ValueError):
                logger.error(
                    "JSONEncodedDict: could not serialise value of type %s",
                    type(value).__name__,
                    exc_info=True,
                )
                raise
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                return json.loads(value)
            except (TypeError, ValueError):
                logger.error(
                    "JSONEncodedDict: could not deserialise stored value of "
                    "type %s; returning empty dict",
                    type(value).__name__,
                    exc_info=True,
                )
                return {}
        return value

user_favorites = db.Table('user_favorites',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('game_uuid', db.String(36), db.ForeignKey('games.uuid'), primary_key=True),
    db.Column('created_at', db.DateTime, default=lambda: datetime.now(timezone.utc))
)

user_game_status = db.Table('user_game_status',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('game_uuid', db.String(36), db.ForeignKey('games.uuid'), primary_key=True),
    db.Column('status', db.String(20), nullable=False),  # 'unplayed', 'unfinished', 'beaten', 'completed', 'null'
    db.Column('updated_at', db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
)


__all__ = [
    "JSONEncodedDict",
    "user_favorites",
    "user_game_status",
]
