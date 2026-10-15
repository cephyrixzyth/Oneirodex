"""Library domain: libraries and their scan/unmatched records, download
requests, play sessions and aggregated progress, emulator saves, game servers."""
import uuid
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship

from oneirodex.models.orm import db
from oneirodex.models._base import JSONEncodedDict
from oneirodex.platform import LibraryPlatform

class Library(db.Model):
    __tablename__ = 'libraries'
    
    uuid = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    name = db.Column(db.String(255), nullable=False)
    image_url = db.Column(db.String(255), nullable=True)
    platform = db.Column(db.Enum(LibraryPlatform), nullable=False)
    display_order = db.Column(db.Integer, default=0)
    # 1 = immediate children are games; 2 = unwrap letter buckets (_a…_z, _#)
    scan_depth = db.Column(db.Integer, default=1, nullable=False)
    # Last successful scan root (used by refresh-all / scheduled scans)
    last_scan_folder = db.Column(db.String(512), nullable=True)
    # Incremental watch intent under ONEIRODEX_LIBRARY_WATCH master switch.
    # null = follow global (watch when env on); False = opt-out; True = prefer watch.
    watch_enabled = db.Column(db.Boolean, nullable=True, default=None)
    # Optional operator grouping (hidden in the table until any library uses it).
    group_name = db.Column(db.String(80), nullable=True, index=True)
    games = db.relationship('Game', backref='library', lazy=True)
    unmatched_folders = relationship("UnmatchedFolder", backref='library', cascade="all, delete-orphan")

class DownloadRequest(db.Model):
    __tablename__ = 'download_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(50), default='pending')
    zip_file_path = db.Column(db.String, nullable=True)
    request_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completion_time = db.Column(db.DateTime, nullable=True)
    download_size = db.Column(db.Float, nullable=False, default=0.0)
    game = db.relationship('Game', foreign_keys=[game_uuid], back_populates='download_requests')
    file_location = db.Column(db.String, nullable=True)

class ScanJob(db.Model):
    __tablename__ = 'scan_jobs'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    folders = db.Column(JSONEncodedDict)
    content_type = db.Column(db.Enum('Games', name='content_type_enum'))
    schedule = db.Column(db.Enum('8_hours', '24_hours', '48_hours', name='schedule_enum'))
    # Additive schedule fields (Wave 2): keep legacy enum for presets; interval/cron
    # live here so cross-system deploys do not rewrite the enum type.
    schedule_kind = db.Column(db.String(16), nullable=True)  # once|preset|interval|cron
    schedule_interval_minutes = db.Column(db.Integer, nullable=True)
    schedule_cron = db.Column(db.String(64), nullable=True)
    is_enabled = db.Column(db.Boolean, default=True)
    status = db.Column(db.Enum(
        'Scheduled', 'Queued', 'Running', 'Stopping', 'Completed', 'Failed', 'Cancelled',
        name='status_enum',
    ))
    last_run = db.Column(db.DateTime, nullable=True)
    next_run = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text)
    total_folders = db.Column(db.Integer, default=0)
    folders_success = db.Column(db.Integer, default=0)
    folders_failed = db.Column(db.Integer, default=0)
    library_uuid = db.Column(db.String(36), db.ForeignKey('libraries.uuid'), nullable=True)
    library = db.relationship('Library', backref=db.backref('scan_jobs', lazy=True))
    removed_count = db.Column(db.Integer, default=0)
    scan_folder = db.Column(db.String(512), nullable=True)
    setting_remove = db.Column(db.Boolean, default=False)
    setting_filefolder = db.Column(db.Boolean, default=False)
    setting_download_missing_images = db.Column(db.Boolean, default=False)
    setting_force_updates_extras = db.Column(db.Boolean, default=False)
    current_processing = db.Column(db.String(255), nullable=True)  # "Processing: Game Name (450/1000)"
    last_progress_update = db.Column(db.DateTime, nullable=True)
    # Which process owns the worker thread while this job is Running/Stopping.
    #
    # A scan runs on a daemon Thread inside one process, so a job is only really
    # in progress while that process is alive. Without this, a job orphaned by a
    # restart or a kill stays 'Running' in the database and is_scan_busy() keeps
    # returning True — every later scan queues behind a job that no thread is
    # working on. Time alone cannot tell the two apart, which is why the stale
    # sweep had to wait STALE_RUNNING_SECONDS (6h) before touching a Running row.
    #
    # Format is "<boot_id>:<pid>" (see scan_queue.PROCESS_TOKEN). The boot id is
    # what makes a recycled pid safe to judge: same pid + different boot id is a
    # different process, not the original owner. NULL means a job written before
    # this column existed, which the reclaim sweep treats as unowned.
    owner_token = db.Column(db.String(80), nullable=True)

class UnmatchedFolder(db.Model):
    __tablename__ = 'unmatched_folders'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    library_uuid = db.Column(db.String(36), ForeignKey('libraries.uuid', ondelete="CASCADE"), nullable=True)
    scan_job_id = db.Column(db.String(36), db.ForeignKey('scan_jobs.id'))
    folder_path = db.Column(db.String)
    failed_time = db.Column(db.DateTime)
    content_type = db.Column(db.Enum('Games', name='unmatched_folder_content_type_enum'))
    status = db.Column(db.Enum('Pending', 'Ignore', 'Duplicate', 'Unmatched', name='unmatched_folder_status_enum'))
    # Wave 2a: how this row was matched when status=Duplicate (queryable glance)
    matched_game_uuid = db.Column(db.String(36), nullable=True, index=True)
    match_reason = db.Column(db.String(64), nullable=True)
    match_score = db.Column(db.Float, nullable=True)
    # Wave 4: denormalized from proposal sidecar at propose/log time (list API — no N+1)
    suggested_kind = db.Column(db.String(16), nullable=True)
    suggested_candidate_name = db.Column(db.String(255), nullable=True)
    # W21-BE-2b: Stage E propose-only hints denormalized from proposal sidecar (list — no N+1)
    stage_e_candidates = db.Column(db.JSON, nullable=True)
    stage_e = db.Column(db.JSON, nullable=True)
    # Wave 17: soft librarian naming (no disk rename / folder_path change)
    search_name = db.Column(db.String(255), nullable=True)
    display_name = db.Column(db.String(255), nullable=True)
    # UX-C5: operator feedback that a proposed match is wrong. Kept apart from
    # `match_reason`, which is the matcher explaining itself — this is a human
    # contradicting it, and conflating the two would lose that distinction.
    bad_match_reason = db.Column(db.String(32), nullable=True)
    bad_match_note = db.Column(db.String(500), nullable=True)
    bad_match_at = db.Column(db.DateTime, nullable=True)
    bad_match_by_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True,
    )

class DuplicateFixLog(db.Model):
    """Queryable admin/dev log of duplicate triage actions (merge/keep/ignore)."""

    __tablename__ = 'duplicate_fix_logs'

    id = db.Column(db.Integer, primary_key=True)
    unmatched_folder_id = db.Column(db.String(36), nullable=True, index=True)
    folder_path = db.Column(db.String(1024), nullable=False)
    matched_game_uuid = db.Column(db.String(36), nullable=True, index=True)
    match_reason = db.Column(db.String(64), nullable=True)
    match_score = db.Column(db.Float, nullable=True)
    action = db.Column(db.String(32), nullable=False)  # merge | keep | ignore
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    notes = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    actor = db.relationship('User', backref='duplicate_fix_logs')

    def __repr__(self):
        return f"<DuplicateFixLog {self.action} path={self.folder_path!r}>"

class EmulatorSave(db.Model):
    """Per-user emulator save-state blob metadata (opt-in cloud sync)."""

    __tablename__ = 'emulator_saves'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'game_uuid', 'slot_name', name='uq_emulator_save_slot'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    game_uuid = db.Column(
        db.String(36),
        db.ForeignKey('games.uuid', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    slot_name = db.Column(db.String(64), nullable=False, default='slot1')
    filename = db.Column(db.String(255), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    storage_path = db.Column(db.String(1024), nullable=False)
    encrypted = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self):
        return {
            'id': self.id,
            'game_uuid': self.game_uuid,
            'slot_name': self.slot_name,
            'filename': self.filename,
            'size_bytes': self.size_bytes,
            'encrypted': bool(self.encrypted),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

class PlaySession(db.Model):
    """Authoritative play session with heartbeat TTL."""

    __tablename__ = 'play_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'), nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_heartbeat_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_seconds = db.Column(db.Integer, default=0, nullable=False)
    client = db.Column(db.String(64), nullable=True)  # web | desktop | etc.
    status = db.Column(db.String(16), default='active', nullable=False)  # active | ended | orphaned

    user = db.relationship('User', backref=db.backref('play_sessions', lazy='dynamic'))
    game = db.relationship('Game', backref=db.backref('play_sessions', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'game_uuid': self.game_uuid,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'last_heartbeat_at': self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'duration_seconds': self.duration_seconds,
            'client': self.client,
            'status': self.status,
        }

class GameServer(db.Model):
    """Admin-managed household game server join metadata."""

    __tablename__ = 'game_servers'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), default=lambda: str(uuid4()), unique=True, nullable=False)
    display_name = db.Column(db.String(255), nullable=False)
    connect_string = db.Column(db.String(512), nullable=False)
    game_uuid = db.Column(
        db.String(36),
        db.ForeignKey('games.uuid', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    health_url = db.Column(db.String(512), nullable=True)
    compose_project = db.Column(db.String(128), nullable=True)
    container_id = db.Column(db.String(128), nullable=True)
    invite_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    game = db.relationship('Game', foreign_keys=[game_uuid])

    def to_dict(self, *, admin: bool = False) -> dict:
        payload = {
            'uuid': self.uuid,
            'display_name': self.display_name,
            'connect_string': self.connect_string,
            'game_uuid': self.game_uuid,
            'invite_note': self.invite_note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if admin:
            payload.update({
                'id': self.id,
                'health_url': self.health_url,
                'compose_project': self.compose_project,
                'container_id': self.container_id,
            })
        return payload

class UserGameProgress(db.Model):
    """Aggregated playtime per user/game."""

    __tablename__ = 'user_game_progress'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'game_uuid', name='uq_user_game_progress'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'), nullable=False, index=True)
    total_seconds = db.Column(db.Integer, default=0, nullable=False)
    session_count = db.Column(db.Integer, default=0, nullable=False)
    last_played_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'user_id': self.user_id,
            'game_uuid': self.game_uuid,
            'total_seconds': self.total_seconds,
            'session_count': self.session_count,
            'last_played_at': self.last_played_at.isoformat() if self.last_played_at else None,
        }


__all__ = [
    "Library",
    "DownloadRequest",
    "ScanJob",
    "UnmatchedFolder",
    "DuplicateFixLog",
    "EmulatorSave",
    "PlaySession",
    "GameServer",
    "UserGameProgress",
]
