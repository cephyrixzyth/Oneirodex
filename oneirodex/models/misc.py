"""Leftovers that do not warrant their own module: newsletters, announcements,
support tickets, the singleton GlobalSettings row, curated collections, wishlist
requests, free-game offers, and small operator lookup tables."""
from datetime import datetime, timezone
from uuid import uuid4

from oneirodex import db
from oneirodex.models._base import JSONEncodedDict

class ReleaseGroup(db.Model):
    __tablename__ = 'filters'

    id = db.Column(db.Integer, primary_key=True)
    filter_pattern = db.Column(db.String, nullable=True)
    case_sensitive = db.Column(db.String, nullable=True)

    def __repr__(self):
        return f"<ReleaseGroup id={self.id}, filter_pattern={self.filter_pattern}, case_sensitive={self.case_sensitive}>"

class Newsletter(db.Model):
    __tablename__ = 'newsletters'
    
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sent_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    recipient_count = db.Column(db.Integer, default=0)
    recipients = db.Column(db.JSON)
    status = db.Column(db.String(20), default='pending')  # pending, sent, failed
    error_message = db.Column(db.Text, nullable=True)
    
    sender = db.relationship('User', backref='sent_newsletters')

class GlobalSettings(db.Model):
    __tablename__ = 'global_settings'

    # This table holds exactly one row, and until now that was true only by
    # convention — roughly two dozen code paths create a row when they find
    # none, so a race on first boot or a restore that merged two dumps could
    # leave several. Duplicates are the quiet kind of broken: a write lands on
    # the row nobody reads and the setting simply does not take effect.
    #
    # A unique index on a constant is how "at most one row" is expressed, since
    # the constraint is on the table's cardinality rather than on any column.
    # Declared here so create_all() emits it for fresh installs and tests;
    # existing databases get the same index from
    # cleanup_duplicate_global_settings in updateschema.py, which must collapse
    # duplicates first.
    __table_args__ = (
        db.Index('global_settings_singleton', db.text('(true)'), unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    settings = db.Column(JSONEncodedDict)  # Store all settings in a single JSON-encoded column
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    # SMTP Settings
    smtp_server = db.Column(db.String(255), nullable=True)
    smtp_port = db.Column(db.Integer, nullable=True)
    smtp_username = db.Column(db.String(255), nullable=True)
    smtp_password = db.Column(db.String(255), nullable=True)
    smtp_use_tls = db.Column(db.Boolean, default=True)
    smtp_default_sender = db.Column(db.String(255), nullable=True)
    smtp_last_tested = db.Column(db.DateTime, nullable=True)
    smtp_enabled = db.Column(db.Boolean, default=False)
    enable_delete_game_on_disk = db.Column(db.Boolean, default=True)
    # IGDB Settings
    igdb_client_id = db.Column(db.String(255), nullable=True)
    igdb_client_secret = db.Column(db.String(255), nullable=True)
    igdb_last_tested = db.Column(db.DateTime, nullable=True)
    enable_game_updates = db.Column(db.Boolean, default=True)
    update_folder_name = db.Column(db.String(255), default='updates')
    enable_game_extras = db.Column(db.Boolean, default=True)
    extras_folder_name = db.Column(db.String(255), default='extras')
    site_url = db.Column(db.String(255), default='http://127.0.0.1')
    # Image Download Settings (Unraid-safe defaults; runtime also hard-capped in worker_caps)
    use_turbo_image_downloads = db.Column(db.Boolean, default=True)
    turbo_download_threads = db.Column(db.Integer, default=4)
    turbo_download_batch_size = db.Column(db.Integer, default=100)
    # Scan Thread Settings (default 1 for shared NAS CPUs; hard max via worker_caps)
    scan_thread_count = db.Column(db.Integer, default=1)
    # Setup State Tracking
    setup_in_progress = db.Column(db.Boolean, default=False)
    setup_current_step = db.Column(db.Integer, default=1)
    setup_completed = db.Column(db.Boolean, default=False)
    # Attract Mode Settings
    attract_mode_enabled = db.Column(db.Boolean, default=True)
    attract_mode_idle_timeout = db.Column(db.Integer, default=60)  # seconds, range 10-300
    attract_mode_settings = db.Column(JSONEncodedDict)  # JSON: filters, autoplay settings
    # HowLongToBeat Settings
    enable_hltb_integration = db.Column(db.Boolean, default=True)
    hltb_rate_limit_delay = db.Column(db.Float, default=2.0)  # seconds between HLTB requests
    # Local Metadata Settings
    use_local_metadata = db.Column(db.Boolean, default=False)
    write_local_metadata = db.Column(db.Boolean, default=False)
    use_local_images = db.Column(db.Boolean, default=False)
    local_metadata_filename = db.Column(db.String(50), default='oneirodex.json')
    # Scan Behavior Settings
    propose_only_scan = db.Column(db.Boolean, default=False)
    # OIDC / SSO Settings
    oidc_enabled = db.Column(db.Boolean, default=False)
    oidc_issuer_url = db.Column(db.String(512), nullable=True)
    oidc_client_id = db.Column(db.String(255), nullable=True)
    oidc_client_secret = db.Column(db.String(512), nullable=True)
    oidc_redirect_uri = db.Column(db.String(512), nullable=True)
    oidc_scopes = db.Column(db.String(255), default='openid email profile')
    oidc_role_claim = db.Column(db.String(64), default='groups')
    oidc_role_map = db.Column(JSONEncodedDict, nullable=True)
    oidc_display_name = db.Column(db.String(120), default='Sign in with SSO')
    # Store ownership sync (register-only; never downloads from stores)
    enable_store_ownership_sync = db.Column(db.Boolean, default=True)
    steam_web_api_key = db.Column(db.String(255), nullable=True)
    steamgriddb_api_key = db.Column(db.String(255), nullable=True)
    # Emulator profiles: { "NES": "nestopia", ... } preferred WebRetro cores
    emulator_profiles = db.Column(JSONEncodedDict, nullable=True)
    # Optional *arr automation module (feature-flagged)
    enable_arr_module = db.Column(db.Boolean, default=True)
    arr_settings = db.Column(JSONEncodedDict, nullable=True)
    # Opt-in WebRetro / companion save-state sync
    enable_emulator_save_sync = db.Column(db.Boolean, default=True)
    # Whether children may join the household voice lobby. Defaults to False,
    # which is the behaviour that already shipped — households that want the
    # lobby to be genuinely household-wide can turn it on.
    allow_children_in_household_lobby = db.Column(db.Boolean, default=False)
    encrypt_emulator_saves = db.Column(db.Boolean, default=False)
    # GiantBomb metadata key (optional)
    giantbomb_api_key = db.Column(db.String(255), nullable=True)
    # MobyGames identify search key (optional — empty search when unset)
    mobygames_api_key = db.Column(db.String(255), nullable=True)
    # TheGamesDB identify search key (optional — empty search when unset)
    thegamesdb_api_key = db.Column(db.String(255), nullable=True)
    # RetroAchievements household account used for set matching / member progress
    retroachievements_username = db.Column(db.String(64), nullable=True)
    retroachievements_api_key = db.Column(db.String(512), nullable=True)
    # Preferred release groups / size bands for *arr scoring
    quality_profiles = db.Column(JSONEncodedDict, nullable=True)
    # Game details section order/visibility
    detail_layout = db.Column(JSONEncodedDict, nullable=True)
    # Optional Ollama AI assist
    enable_ai_assist = db.Column(db.Boolean, default=True)
    enable_malware_scan = db.Column(db.Boolean, default=True)
    ollama_base_url = db.Column(db.String(512), nullable=True)
    ollama_model = db.Column(db.String(120), nullable=True)
    # BYO community chat (Stoat / Matrix invite) — deep-link only
    community_chat_url = db.Column(db.String(512), nullable=True)
    community_chat_label = db.Column(db.String(120), nullable=True)
    # In-app admin alerts (replaces former external chat webhooks)
    admin_notify_new_games = db.Column(db.Boolean, default=True)
    admin_notify_game_updates = db.Column(db.Boolean, default=False)
    admin_notify_game_extras = db.Column(db.Boolean, default=False)
    admin_notify_downloads = db.Column(db.Boolean, default=False)
    admin_notify_support = db.Column(db.Boolean, default=True)
    # BYO Sunshine / Wolf remote play (Moonlight clients) — off by default
    enable_remote_play = db.Column(db.Boolean, default=False)
    remote_play_settings = db.Column(JSONEncodedDict, nullable=True)
    # Loading icon: rotate catalogue vs lock to one id (member/admin loading UIs)
    loading_icon_mode = db.Column(db.String(16), default='rotate')
    loading_icon_id = db.Column(db.String(64), nullable=True)

    def __repr__(self):
        return f'<GlobalSettings id={self.id}, last_updated={self.last_updated}>'

class GameCollection(db.Model):
    """Admin or user curated collection / shelf."""

    __tablename__ = 'game_collections'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    is_public = db.Column(db.Boolean, default=True, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    items = db.relationship(
        'GameCollectionItem',
        back_populates='collection',
        cascade='all, delete-orphan',
        order_by='GameCollectionItem.position',
    )

    def to_dict(self, include_items=False):
        data = {
            'id': self.id,
            'uuid': self.uuid,
            'name': self.name,
            'description': self.description,
            'owner_user_id': self.owner_user_id,
            'is_public': self.is_public,
            'is_system': self.is_system,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_items:
            data['items'] = [i.to_dict() for i in self.items]
        return data

class GameCollectionItem(db.Model):
    __tablename__ = 'game_collection_items'
    __table_args__ = (
        db.UniqueConstraint('collection_id', 'game_uuid', name='uq_collection_game'),
    )

    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('game_collections.id', ondelete='CASCADE'), nullable=False)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)

    collection = db.relationship('GameCollection', back_populates='items')
    game = db.relationship('Game')

    def to_dict(self):
        library_platform = None
        if self.game is not None and self.game.library is not None and self.game.library.platform is not None:
            library_platform = self.game.library.platform.name
        return {
            'id': self.id,
            'collection_id': self.collection_id,
            'game_uuid': self.game_uuid,
            'game_name': self.game.name if self.game else None,
            'library_platform': library_platform,
            'position': self.position,
        }

class Announcement(db.Model):
    """Admin news / announcements for store-grade browse."""

    __tablename__ = 'announcements'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    published = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    author_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    def to_dict(self):
        body = self.body or ''
        return {
            'id': self.id,
            'title': self.title,
            'body': body,
            # Compact preview for News / overhaul cards (full body still present).
            'body_preview': body[:280],
            'published': self.published,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'author_user_id': self.author_user_id,
        }

class FreeGameOffer(db.Model):
    """Cached free / giveaway offers from store APIs + GamerPower (Wave 18)."""

    __tablename__ = 'free_game_offers'
    __table_args__ = (
        db.UniqueConstraint('store', 'external_id', name='uq_free_game_offer_store_ext'),
    )

    id = db.Column(db.Integer, primary_key=True)
    store = db.Column(db.String(16), nullable=False, index=True)
    external_id = db.Column(db.String(64), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    image_url = db.Column(db.String(1024), nullable=True)
    claim_url = db.Column(db.String(1024), nullable=True)
    store_url = db.Column(db.String(1024), nullable=True)
    worth = db.Column(db.String(64), nullable=True)
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    source = db.Column(db.String(32), nullable=False, default='gamerpower', index=True)
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    first_seen_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

class GameRequest(db.Model):
    """User wishlist / request queue."""

    __tablename__ = 'game_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), default='pending', nullable=False)  # pending|approved|rejected|fulfilled
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    linked_game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid', ondelete='SET NULL'), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'notes': self.notes,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolved_by_user_id': self.resolved_by_user_id,
            'linked_game_uuid': self.linked_game_uuid,
        }

class SupportTicket(db.Model):
    """In-app teammate support reports → GitHub Issues (no external chat SaaS)."""

    __tablename__ = 'support_tickets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    area = db.Column(db.String(64), nullable=True)
    # What kind of report this is. "Report issue" collected both bug reports and
    # feature requests into one undifferentiated pile, so triage had to read
    # every title to find out which it was — and a request filed as a bug reads
    # as a broken product. issue|enhancement.
    kind = db.Column(db.String(16), default='issue', nullable=False)
    severity = db.Column(db.String(8), default='P2', nullable=False)
    role_at_submit = db.Column(db.String(32), nullable=True)
    deploy_hint = db.Column(db.String(64), nullable=True)
    client_hint = db.Column(db.String(120), nullable=True)
    url_hint = db.Column(db.String(512), nullable=True)
    logs = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), default='open', nullable=False)  # open|resolved|closed
    github_issue_number = db.Column(db.Integer, nullable=True)
    github_issue_url = db.Column(db.String(512), nullable=True)
    github_sync = db.Column(db.String(32), default='pending', nullable=False)  # pending|synced|skipped|error
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    def to_dict(self, *, compact: bool = False):
        body = self.body or ''
        logs = self.logs or ''
        payload = {
            'id': self.id,
            'user_id': self.user_id,
            'kind': self.kind or 'issue',
            'title': self.title,
            'body': body,
            'area': self.area,
            'severity': self.severity,
            'role_at_submit': self.role_at_submit,
            'deploy_hint': self.deploy_hint,
            'client_hint': self.client_hint,
            'url_hint': self.url_hint,
            'logs': logs or None,
            'has_logs': bool(logs.strip()),
            'status': self.status,
            'github_issue_number': self.github_issue_number,
            'github_issue_url': self.github_issue_url,
            'github_sync': self.github_sync,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolved_by_user_id': self.resolved_by_user_id,
        }
        if compact:
            # List/inbox cards: short symptom, no log blob.
            payload['body'] = body[:280]
            payload['body_truncated'] = len(body) > 280
            payload['body_preview'] = payload['body']
            payload['logs'] = None
        return payload

class AllowedFileType(db.Model):
    __tablename__ = 'allowed_file_types'
    
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(10), unique=True, nullable=False)

    def __repr__(self):
        return f'<AllowedFileType {self.value}>'

class IgnoredFileType(db.Model):
    __tablename__ = 'ignored_file_types'
    
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(10), unique=True, nullable=False)

    def __repr__(self):
        return f'<IgnoredFileType {self.value}>'

class SystemEvents(db.Model):
    __tablename__ = 'system_events'
    
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(32), default='log')
    event_text = db.Column(db.String(256), nullable=False)
    event_level = db.Column(db.String(32), default='information')
    audit_user = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    user = db.relationship('User', backref='system_events')

    def __repr__(self):
        return f"<SystemEvent {self.event_type}: {self.event_text}>"


__all__ = [
    "ReleaseGroup",
    "Newsletter",
    "GlobalSettings",
    "GameCollection",
    "GameCollectionItem",
    "Announcement",
    "FreeGameOffer",
    "GameRequest",
    "SupportTicket",
    "AllowedFileType",
    "IgnoredFileType",
    "SystemEvents",
]
