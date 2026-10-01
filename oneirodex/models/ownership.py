"""Ownership domain: linked external store accounts and register-only records
of titles a member owns elsewhere (browse-badge matching; never downloads)."""
from datetime import datetime, timezone

from oneirodex import db

class StoreAccount(db.Model):
    """Linked external store account for register-only ownership sync (no downloads)."""

    __tablename__ = 'store_accounts'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'store', name='uq_store_account_user_store'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    store = db.Column(db.String(16), nullable=False)  # steam|gog|epic|amazon|playnite
    external_account_id = db.Column(db.String(64), nullable=True)
    # Refresh / device-auth secret for live GOG/Epic/Amazon sync. Never returned in to_dict.
    credential = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    # Last time the member submitted connect details (first link or reconnect).
    # A token refreshed during a sync does not move it. Status uses it to tell a
    # failure that predates a reconnect from one that still applies.
    updated_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship(
        'User',
        backref=db.backref('store_accounts', lazy='dynamic', cascade='all, delete-orphan'),
    )

    def to_dict(self):
        return {
            'store': self.store,
            'external_account_id': self.external_account_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class UserOwnedTitle(db.Model):
    """
    Register-only record of a title the user owns on an external store.
    Never triggers downloads or DRM retrieval — used for browse badge matching only.
    """

    __tablename__ = 'user_owned_titles'
    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'store', 'external_app_id',
            name='uq_user_owned_title',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    store = db.Column(db.String(16), nullable=False)
    # 128, not 32: Xbox package family names and Amazon product IDs are longer.
    external_app_id = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(255), nullable=True)
    matched_game_uuid = db.Column(
        db.String(36),
        db.ForeignKey('games.uuid', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    last_synced_at = db.Column(db.DateTime, nullable=True)
    match_revision = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    match_reviewed = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    user = db.relationship(
        'User',
        backref=db.backref('owned_titles', lazy='dynamic', cascade='all, delete-orphan'),
    )
    matched_game = db.relationship('Game')

    def to_dict(self):
        return {
            'store': self.store,
            'external_app_id': self.external_app_id,
            'name': self.name,
            'matched_game_uuid': self.matched_game_uuid,
            'match_revision': self.match_revision,
            'match_reviewed': self.match_reviewed,
            'last_synced_at': (
                self.last_synced_at.isoformat() if self.last_synced_at else None
            ),
        }


class OwnershipMatchDecision(db.Model):
    """Member decisions only; no credentials, retained until entitlement deletion."""

    __tablename__ = 'ownership_match_decisions'
    __table_args__ = (db.UniqueConstraint('title_id', 'revision', name='uq_ownership_match_revision'),)
    id = db.Column(db.Integer, primary_key=True)
    title_id = db.Column(db.Integer, db.ForeignKey('user_owned_titles.id', ondelete='CASCADE'), nullable=False, index=True)
    revision = db.Column(db.Integer, nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    before_uuid = db.Column(db.String(36), nullable=True)
    after_uuid = db.Column(db.String(36), nullable=True)
    before_reviewed = db.Column(db.Boolean, nullable=False)
    action = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class StoreSyncJob(db.Model):
    """One live ownership sync attempt (LIB-04). Holds a redacted reason code,
    never exception text, upstream data or credentials.

    At most one ``running`` row per member and store; the partial unique index
    is the guard two concurrent sync requests race against.
    """

    __tablename__ = 'store_sync_jobs'
    __table_args__ = (
        db.Index('ix_store_sync_jobs_user_store', 'user_id', 'store', 'id'),
        db.Index(
            'uq_store_sync_jobs_running', 'user_id', 'store', unique=True,
            postgresql_where=db.text("status = 'running'"),
            sqlite_where=db.text("status = 'running'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    store = db.Column(db.String(16), nullable=False)
    trigger = db.Column(db.String(16), nullable=False)  # member | schedule | admin
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(16), nullable=False)  # running | succeeded | partial | failed | cancelled
    reason = db.Column(db.String(32), nullable=True)
    cancellable = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    cancel_requested = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    pages = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    items_seen = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    synced = db.Column(db.Integer, nullable=True)
    matched = db.Column(db.Integer, nullable=True)
    started_at = db.Column(db.DateTime, nullable=False)
    heartbeat_at = db.Column(db.DateTime, nullable=False)
    finished_at = db.Column(db.DateTime, nullable=True)


__all__ = [
    "StoreAccount",
    "UserOwnedTitle",
    "OwnershipMatchDecision",
    "StoreSyncJob",
]
