"""User domain: accounts, per-user preferences and layout presets, access
control rows, personal access tokens, client devices and invites."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from oneirodex import db
from oneirodex.models._base import JSONEncodedDict

ph = PasswordHasher()

class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = (
        db.Index('ux_users_oidc_issuer_subject', 'oidc_issuer_url', 'oidc_subject', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    favorites = db.relationship('Game', secondary='user_favorites', back_populates='favorited_by')
    game_statuses = db.relationship('Game', secondary='user_game_status', back_populates='status_users')
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(64), nullable=False)
    state = db.Column(db.Boolean, default=True)
    about = db.Column(db.String(256), unique=True, nullable=True)
    created = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    lastlogin = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid4()))
    avatarpath = db.Column(db.String(256), default='newstyle/avatars/default.svg')
    is_email_verified = db.Column(db.Boolean, default=False)
    email_verification_token = db.Column(db.String(256), nullable=True)
    password_reset_token = db.Column(db.String(256), nullable=True)
    # OIDC subjects are unique only inside one issuer. Existing subject-only
    # links have NULL issuer until a verified email or operator review binds them.
    oidc_issuer_url = db.Column(db.String(512), nullable=True)
    oidc_subject = db.Column(db.String(255), nullable=True)

    preferences = db.relationship(
        'UserPreference',
        back_populates='user',
        uselist=False,
        cascade='all, delete-orphan'
    )
    token_creation_time = db.Column(db.DateTime, nullable=True)
    invite_quota = db.Column(db.Integer, default=0) 
    
    def set_password(self, password):
        # Now using Argon2 to hash new passwords
        self.password_hash = ph.hash(password)

    def check_password(self, password):
        # Only use Argon2 for password verification
        try:
            return ph.verify(self.password_hash, password)
        except VerifyMismatchError:
            return False
        

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        # A disabled account (state False) is not an active one; None predates the column.
        return self.state is not False

    @property
    def is_anonymous(self):
        return False

    def session_fingerprint(self) -> str:
        """Changes whenever the password does, so every session and remember
        cookie issued before a password change stops working."""
        import hashlib
        return hashlib.sha256((self.password_hash or '').encode('utf-8')).hexdigest()[:16]

    def get_id(self):
        # Stored in the session and the remember cookie; see utils/auth.load_user.
        return f'{self.id}:{self.session_fingerprint()}'

    @staticmethod
    def is_username_reserved(username):
        """Check if a username is reserved"""
        reserved_names = {'system'}
        return username.lower() in reserved_names

    def __repr__(self):
        return f"<User id={self.id}, name={self.name}, email={self.email}>"

class UserLibraryAccess(db.Model):
    """Allow-list of libraries a restricted user (typically child) may see."""

    __tablename__ = 'user_library_access'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    library_uuid = db.Column(
        db.String(36),
        db.ForeignKey('libraries.uuid', ondelete='CASCADE'),
        primary_key=True,
    )

    user = db.relationship('User', backref=db.backref('library_access', cascade='all, delete-orphan'))
    library = db.relationship('Library')

    def __repr__(self):
        return f'<UserLibraryAccess user_id={self.user_id} library_uuid={self.library_uuid}>'

class UserContentFilter(db.Model):
    """Deny-list of genre/theme names for restricted users (typically child)."""

    __tablename__ = 'user_content_filters'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    filter_type = db.Column(db.String(16), primary_key=True)
    name = db.Column(db.String(50), primary_key=True)

    user = db.relationship('User', backref=db.backref('content_filters', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<UserContentFilter user_id={self.user_id} filter_type={self.filter_type} name={self.name}>'

class ApiToken(db.Model):
    """Personal access tokens for OpenAPI / companion clients."""

    __tablename__ = 'api_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    token_prefix = db.Column(db.String(16), nullable=False, index=True)
    token_hash = db.Column(db.String(255), nullable=False)
    scopes = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    # NULL means "never expires" — every token issued before this column existed
    # is NULL, and a live companion must not be logged out by an upgrade.
    expires_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('api_tokens', lazy='dynamic', cascade='all, delete-orphan'))

    def is_expired(self, now=None):
        if self.expires_at is None:
            return False
        moment = now or datetime.now(timezone.utc)
        expires = self.expires_at
        # Postgres hands these back naive; compare in UTC either way.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires <= moment

    def is_active(self):
        return self.revoked_at is None and not self.is_expired()

    def has_scope(self, scope: str) -> bool:
        scopes = self.scopes or []
        if 'admin' in scopes:
            return True
        return scope in scopes

    def to_public_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'token_prefix': self.token_prefix,
            'scopes': self.scopes or [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'revoked': self.revoked_at is not None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'expired': self.is_expired(),
        }

class ClientDevice(db.Model):
    """Companion client presence tracked via heartbeat."""

    __tablename__ = 'client_devices'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'device_id', name='uq_client_devices_user_device'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    device_id = db.Column(db.String(64), nullable=False)
    device_kind = db.Column(db.String(16), nullable=False, default='companion')
    device_name = db.Column(db.String(128), nullable=True)
    client_version = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    last_seen_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = db.relationship(
        'User',
        backref=db.backref('client_devices', lazy='dynamic', cascade='all, delete-orphan'),
    )

    def to_dict(self):
        return {
            'device_id': self.device_id,
            'device_kind': self.device_kind or 'companion',
            'device_name': self.device_name,
            'client_version': self.client_version,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
        }

class Whitelist(db.Model):
    __tablename__ = 'whitelist'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)

class UserPreference(db.Model):
    __tablename__ = 'user_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False
    )
    items_per_page = db.Column(db.Integer, default=50, server_default='50')
    default_sort = db.Column(db.String(50), default='name')
    default_sort_order = db.Column(db.String(4), default='asc')
    theme = db.Column(db.String(50), default='default')
    icon_pack = db.Column(db.String(50), default='outline')
    # Theme font id from utils.theme_fonts (orthogonal to theme and icon pack,
    # exactly like icon_pack is).
    font = db.Column(db.String(64), default='system-ui')
    locale = db.Column(db.String(10), default='en')
    preferred_game_locale = db.Column(db.String(16), default='en-US', nullable=False)
    tile_size = db.Column(db.String(8), default='50', nullable=False)
    # Title strip under each catalog cover. On by default: box art alone is a
    # weak identifier across a ROM library, where many titles in a series share
    # one piece of art. Members who want the plain art wall can switch it off.
    show_tile_titles = db.Column(db.Boolean, default=True, server_default='true', nullable=False)
    # Browser play engine this member asked for (`webretro` / `emulatorjs`).
    # NULL means "whatever the admin set as the default". Only honoured when
    # the admin allows member choice and the engine is installed on this box —
    # utils.browser_player resolves it, nothing reads the column directly.
    browser_player_engine = db.Column(db.String(16), nullable=True)
    # RetroAchievements username, for reading this member's progress on a
    # matched set (public data on the site). Never a password or key.
    ra_username = db.Column(db.String(64), nullable=True)
    notify_friend_requests = db.Column(db.Boolean, default=True, nullable=False)
    notify_activity = db.Column(db.Boolean, default=True, nullable=False)
    notify_mentions = db.Column(db.Boolean, default=True, nullable=False)
    notify_chat = db.Column(db.Boolean, default=True, nullable=False)
    notify_support = db.Column(db.Boolean, default=True, nullable=False)
    notify_free_games = db.Column(db.Boolean, default=True, nullable=False)
    # Whether accepted friends see what this member is playing (the Discover
    # "Friends are playing" row and nothing wider). Defaults on because the
    # common install is a household, but scoped to friends only — never
    # server-wide — and every member can switch themselves off.
    share_activity = db.Column(db.Boolean, default=True, nullable=False)
    # Discover rows this member pinned to the top, in their order. A JSON list
    # of row identifiers rather than a table, matching how `detail_layout`
    # stores its arrangement. Validated against the live rows on read: a pinned
    # row is allowed to stop existing, which is not an error.
    discover_pins = db.Column(JSONEncodedDict, nullable=True)
    # Discover rows this member excluded from their own feed. Same storage and
    # the same forgiving read as `discover_pins`: a JSON list of identifiers,
    # validated against the live rows, and an entry that no longer resolves is
    # dropped rather than raised.
    #
    # Hiding is a member preference, not an admin one — it never changes what
    # anyone else sees, and `DiscoverySection.is_visible` remains the only thing
    # that can remove a row for everybody.
    discover_hidden = db.Column(JSONEncodedDict, nullable=True)
    # Opt-in: email for @mentions + DMs when SMTP is configured (default off).
    email_notify_social = db.Column(db.Boolean, default=True, nullable=False)
    # Opt-in: batched email of unread mentions/DMs/free games (default off).
    email_digest_daily = db.Column(db.Boolean, default=False, nullable=False)
    email_digest_last_sent_at = db.Column(db.DateTime, nullable=True)

    # Per-member game-details layout. NULL means "follow the install default"
    # rather than "empty layout" — the two are different, and a member who has
    # never touched this should keep tracking whatever the admin sets rather
    # than being frozen at whatever it happened to be on their first visit.
    detail_layout = db.Column(JSONEncodedDict, nullable=True)

    user = db.relationship('User', back_populates='preferences')

class DetailLayoutPreset(db.Model):
    """A member's saved, named game-details arrangement.

    The layout editor could already produce exactly one arrangement, stored on
    GlobalSettings and therefore shared by everyone. Naming them makes the
    obvious use case possible — a dense layout at a desk, a sparse one on a
    couch display — and per-user ownership means one member re-arranging their
    details page no longer changes it for the whole household.
    """

    __tablename__ = 'detail_layout_presets'
    __table_args__ = (
        # Names are how a member picks one, so they have to be unique per
        # member — two "Couch" presets would make the picker a coin toss.
        db.UniqueConstraint('user_id', 'name', name='uq_detail_preset_user_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(64), nullable=False)
    layout = db.Column(JSONEncodedDict, nullable=False)
    created = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='detail_layout_presets')

    def __repr__(self):
        return f"<DetailLayoutPreset {self.user_id}:{self.name}>"

class SavedFilter(db.Model):
    """A member's named filter: a nested AND/OR tree over the chip vocabulary.

    The chip row can only mean *and*, so a question like "VR titles that are
    behind, or anything imported this fortnight" had no expression at all. The
    tree gives it one (see ``utils/filter_tree.py``), and naming it is what
    makes it worth building twice -- a saved filter is also what a smart
    collection is made of (INSP-29).

    Per-member by design: one household member narrowing their own view should
    not change what anyone else sees, which is the mistake the shared detail
    layout made before presets were named.
    """

    __tablename__ = 'saved_filters'
    __table_args__ = (
        # The name is how a member picks one, so two of the same name would
        # make the picker a coin toss.
        db.UniqueConstraint('user_id', 'name', name='uq_saved_filter_user_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(64), nullable=False)
    tree = db.Column(JSONEncodedDict, nullable=False)
    # A saved filter becomes a smart collection when it is worth a tile of its
    # own; the flag lives here rather than in a second table because the row is
    # the same row either way (INSP-29).
    is_collection = db.Column(db.Boolean, nullable=False, default=False)
    created = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship('User', backref='saved_filters')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'tree': self.tree,
            'is_collection': bool(self.is_collection),
            'created': self.created.isoformat() if self.created else None,
            'updated': self.updated.isoformat() if self.updated else None,
        }

    def __repr__(self):
        return f"<SavedFilter {self.user_id}:{self.name}>"

class InviteToken(db.Model):
    __tablename__ = 'invite_tokens'

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(256), nullable=False, unique=True)
    creator_user_id = db.Column(db.String(36), db.ForeignKey('users.user_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc) + timedelta(days=2), nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    recipient_email = db.Column(db.String(120), nullable=True)
    used_by = db.Column(db.String(36), db.ForeignKey('users.user_id'), nullable=True)
    used_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship('User', foreign_keys=[creator_user_id], backref='created_invites')
    used_by_user = db.relationship('User', foreign_keys=[used_by], backref='used_invites')

    def __repr__(self):
        return f'<InviteToken {self.token}, Creator: {self.creator_user_id}, Expires: {self.expires_at}, Used: {self.used}>'

class UserAttractModeSettings(db.Model):
    __tablename__ = 'user_attract_mode_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.user_id'), nullable=False, unique=True)
    has_customized = db.Column(db.Boolean, default=False)
    filter_settings = db.Column(JSONEncodedDict)  # JSON: platform, genres, themes, date_range
    autoplay_settings = db.Column(JSONEncodedDict)  # JSON: enabled, skipFirst, skipAfter
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', backref=db.backref('attract_mode_settings', uselist=False, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<UserAttractModeSettings user_id={self.user_id}, customized={self.has_customized}>'


__all__ = [
    "ph",
    "User",
    "UserLibraryAccess",
    "UserContentFilter",
    "ApiToken",
    "ClientDevice",
    "Whitelist",
    "UserPreference",
    "DetailLayoutPreset",
    "SavedFilter",
    "InviteToken",
    "UserAttractModeSettings",
]
