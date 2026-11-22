"""Private original-room-game progress, removed with its member account."""
from datetime import datetime, timezone

from oneirodex.models.orm import db

__all__ = ['RoomGameProgress']


class RoomGameProgress(db.Model):
    __tablename__ = 'room_game_progress'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    game_id = db.Column(db.String(64), primary_key=True)
    revision = db.Column(db.Integer, nullable=False, default=1)
    # A reset removes the entire payload but preserves a revision to reject stale writes.
    state = db.Column(db.JSON(none_as_null=True), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
