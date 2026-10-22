"""Catalog domain: games and their editions, artwork, related media, and the
taxonomy tables (genre / theme / mode / platform / company)."""
from datetime import datetime, timezone
from enum import Enum as PyEnum
from uuid import uuid4

from sqlalchemy import select

from oneirodex.models.orm import db

game_genre_association = db.Table('game_genre_association',
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True),
    db.Column('genre_id', db.Integer, db.ForeignKey('genres.id'), primary_key=True)
)

game_game_mode_association = db.Table('game_game_mode_association',
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True),
    db.Column('game_mode_id', db.Integer, db.ForeignKey('game_modes.id'), primary_key=True)
)

game_theme_association = db.Table(
    'game_theme_association',
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True),
    db.Column('theme_id', db.Integer, db.ForeignKey('themes.id'), primary_key=True)
)

game_platform_association = db.Table(
    'game_platform_association',
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True),
    db.Column('platform_id', db.Integer, db.ForeignKey('platforms.id'), primary_key=True)
)

game_multiplayer_mode_association = db.Table(
    'game_multiplayer_mode_association',
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True),
    db.Column('multiplayer_mode_id', db.Integer, db.ForeignKey('multiplayer_modes.id'), primary_key=True)
)

game_player_perspective_association = db.Table(
    'game_player_perspective_association',
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True),
    db.Column('player_perspective_id', db.Integer, db.ForeignKey('player_perspectives.id'), primary_key=True)
)

game_developer_association = db.Table(
    'game_developer_association',
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True),
    db.Column('developer_id', db.Integer, db.ForeignKey('developers.id'), primary_key=True)
)

class Category(PyEnum):
    MAIN_GAME = "Main Game"
    DLC_ADDON = "DLC/Add-on"
    EXPANSION = "Expansion"
    BUNDLE = "Bundle"
    STANDALONE_EXPANSION = "Standalone Expansion"
    MOD = "Mod"
    EPISODE = "Episode"
    SEASON = "Season"
    REMAKE = "Remake"
    REMASTER = "Remaster"
    EXPANDED_GAME = "Expanded Game"
    PORT = "Port"
    PACK = "Pack"
    UPDATE = "Update"

class Status(PyEnum):
    RELEASED = "Released"
    ALPHA = "Alpha"
    BETA = "Beta"
    EARLY_ACCESS = "Early Access"
    OFFLINE = "Offline"
    CANCELLED = "Cancelled"

class Game(db.Model):
    __tablename__ = 'games'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), default=lambda: str(uuid4()), unique=True, nullable=False)
    igdb_id = db.Column(db.Integer, unique=True, nullable=True)
    favorited_by = db.relationship('User', secondary='user_favorites', back_populates='favorites')
    status_users = db.relationship('User', secondary='user_game_status', back_populates='game_statuses')
    name = db.Column(db.String, nullable=False)
    summary = db.Column(db.Text, nullable=True)
    storyline = db.Column(db.Text, nullable=True)
    updates = db.relationship('GameUpdate', back_populates='game', cascade='all, delete-orphan')
    extras = db.relationship('GameExtra', back_populates='game', cascade='all, delete-orphan')
    aggregated_rating = db.Column(db.Float)
    aggregated_rating_count = db.Column(db.Integer)
    cover = db.Column(db.String)
    first_release_date = db.Column(db.DateTime)
    rating = db.Column(db.Float)
    rating_count = db.Column(db.Integer)
    slug = db.Column(db.String, unique=True)
    status = db.Column(db.Enum(Status))
    category = db.Column(db.Enum(Category))
    total_rating = db.Column(db.Float, default=1.0)
    total_rating_count = db.Column(db.Integer, default=1)
    url_igdb = db.Column(db.String)
    url = db.Column(db.String)
    video_urls = db.Column(db.String, nullable=True)
    full_disk_path = db.Column(db.String, nullable=True)
    # Disk presence signal from scan/identify (nullable = never checked).
    # Values: ok | missing | empty — Ops health counts empty path + path_status=missing
    # without live path.exists on every poll.
    path_status = db.Column(db.String(16), nullable=True)
    # ROM file hashes for DAT set-completion matching (optional; filled on scan/rehash).
    file_crc = db.Column(db.String(16), nullable=True, index=True)
    file_md5 = db.Column(db.String(32), nullable=True, index=True)
    file_sha1 = db.Column(db.String(40), nullable=True, index=True)
    # RetroAchievements (R1/R2): the hash *their* rules produce for this ROM
    # (not file_md5 — headers stripped, N64 byte order normalised), the set it
    # matched, and how many achievements that set carries. `ra_game_id` with a
    # zero count is a matched set that promises nothing; supports_achievements
    # is false for it on purpose.
    ra_hash = db.Column(db.String(32), nullable=True)
    ra_game_id = db.Column(db.Integer, nullable=True, index=True)
    ra_achievements = db.Column(db.Integer, nullable=True)
    # Rider R3 (v11 H-T): how this title is played in VR, beside the derived
    # `is_vr`. NULL = unknown; native_vr | injector_profile | flat. Catalogue
    # data for the ways-to-play rows -- never a shim, an installer or a path.
    vr_compat = db.Column(db.String(24), nullable=True)
    # INSP-43 -- how the cabinet was driven: joystick | spinner | lightgun |
    # trackball. The companion maps it to a RetroArch input remap so a spinner
    # game does not launch bound like a stick game. NULL = unknown.
    input_family = db.Column(db.String(16), nullable=True)
    date_created = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    date_identified = db.Column(db.DateTime, nullable=True)
    steam_url = db.Column(db.String, nullable=True)
    times_downloaded = db.Column(db.Integer, default=0)
    nfo_content = db.Column(db.Text, nullable=True)
    # HowLongToBeat integration fields
    hltb_id = db.Column(db.Integer, nullable=True)
    hltb_main_story = db.Column(db.Float, nullable=True)
    hltb_main_extra = db.Column(db.Float, nullable=True)
    hltb_completionist = db.Column(db.Float, nullable=True)
    hltb_all_styles = db.Column(db.Float, nullable=True)
    hltb_last_updated = db.Column(db.DateTime, nullable=True)
    images = db.relationship("Image", backref="game", lazy='dynamic')
    genres = db.relationship('Genre', secondary=game_genre_association, back_populates='games')
    game_modes = db.relationship("GameMode", secondary=game_game_mode_association, back_populates="games")
    themes = db.relationship("Theme", secondary=game_theme_association, back_populates="games")
    platforms = db.relationship("Platform", secondary=game_platform_association, back_populates="games")
    player_perspectives = db.relationship("PlayerPerspective", secondary=game_player_perspective_association, back_populates="games")
    developer_id = db.Column(db.Integer, db.ForeignKey('developers.id'), nullable=True)
    developer = db.relationship("Developer", back_populates="games")
    publisher = db.relationship("Publisher", back_populates="games")
    publisher_id = db.Column(db.Integer, db.ForeignKey('publishers.id'), nullable=True)
    download_requests = db.relationship('DownloadRequest', back_populates='game', lazy='dynamic', cascade='delete')
    multiplayer_modes = db.relationship("MultiplayerMode", secondary=game_multiplayer_mode_association, back_populates="games")
    urls = db.relationship('GameURL', cascade='all, delete-orphan')
    file_type = db.Column(db.String, nullable=True)
    library_uuid = db.Column(db.String(36), db.ForeignKey('libraries.uuid'), nullable=False)
    size = db.Column(db.BigInteger, nullable=False, default=0)
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Store / freshness (local vs Steam/GOG/Epic)
    steam_app_id = db.Column(db.Integer, nullable=True)
    local_version = db.Column(db.String(100), nullable=True)
    remote_version_summary = db.Column(db.String(255), nullable=True)
    freshness_status = db.Column(db.String(32), nullable=True)
    freshness_confidence = db.Column(db.String(16), nullable=True)
    freshness_checked_at = db.Column(db.DateTime, nullable=True)
    freshness_payload = db.Column(db.JSON, nullable=True)

    # ROM region / language (parsed from No-Intro-style filenames)
    rom_region = db.Column(db.String(16), nullable=True)
    rom_languages = db.Column(db.String(64), nullable=True)  # CSV: en,ja,fr
    has_english = db.Column(db.Boolean, nullable=True)

    # Multi-disc set (BE-DET-5): primary path disc index + known disc count.
    # Sibling discs attach as GameExtra(extra_kind='disc', disc_index=N).
    disc_index = db.Column(db.Integer, nullable=True)
    disc_count = db.Column(db.Integer, nullable=True)

    # Fill-only Steam extras: system requirements + languages matrix.
    # Never prices. Never invented for ROM-only titles.
    store_specs = db.Column(db.JSON, nullable=True)

    # Library item kind (orthogonal to LibraryPlatform / IGDB Category):
    # game | experience | emulator | tool — default game for existing rows.
    item_kind = db.Column(db.String(16), nullable=False, default='game', server_default='game')

    def __repr__(self):
        return f"<Game id={self.id}, name={self.name}>"

class GameUpdate(db.Model):
    __tablename__ = 'game_updates'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), default=lambda: str(uuid4()), unique=True, nullable=False)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid'), nullable=False)
    times_downloaded = db.Column(db.Integer, default=0)
    nfo_content = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    game = db.relationship('Game', back_populates='updates')

    def __repr__(self):
        return f"<GameUpdate id={self.id}, uuid={self.uuid}, game_uuid={self.game_uuid}>"

class GameExtra(db.Model):
    __tablename__ = 'game_extras'

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), default=lambda: str(uuid4()), unique=True, nullable=False)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid'), nullable=False)
    times_downloaded = db.Column(db.Integer, default=0)
    nfo_content = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # Optional typing for translation patches / manuals (O-ROM phase 2)
    extra_kind = db.Column(db.String(32), nullable=True)  # translation_patch | manual | disc | None
    patch_format = db.Column(db.String(8), nullable=True)  # ips | bps | ups
    target_language = db.Column(db.String(16), nullable=True)
    source_url = db.Column(db.String(512), nullable=True)
    # BE-DET-5 — disc sibling index when extra_kind='disc'
    disc_index = db.Column(db.Integer, nullable=True)

    game = db.relationship('Game', back_populates='extras')

    def __repr__(self):
        return f"<GameExtra id={self.id}, uuid={self.uuid}, game_uuid={self.game_uuid}>"

class GameURL(db.Model):
    __tablename__ = 'game_urls'

    id = db.Column(db.Integer, primary_key=True)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid'), nullable=False)
    url_type = db.Column(db.String, nullable=False)
    url = db.Column(db.String, nullable=False)

    game = db.relationship('Game', back_populates='urls')

    def __repr__(self):
        return f"<GameURL id={self.id}, game_uuid={self.game_uuid}, url_type={self.url_type}, url={self.url}>"

class Image(db.Model):
    """Game artwork row. ``image_type`` is the kind enum (BE-DET-10):
    cover | screenshot | box | cart | disc | logo | hero | fanart.
    """
    __tablename__ = 'images'

    id = db.Column(db.Integer, primary_key=True)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid'), nullable=False)
    image_type = db.Column(db.String, nullable=False)  # kind — see image_kinds.IMAGE_KINDS
    url = db.Column(db.String, nullable=False)
    igdb_image_id = db.Column(db.String, nullable=True)  # IGDB image ID for reference
    download_url = db.Column(db.String, nullable=True)  # Full IGDB URL to download from
    is_downloaded = db.Column(db.Boolean, default=False, nullable=False)  # Download status
    # FEAT-D3: generated art is labelled so it can be found and replaced later
    # rather than passing as real cover art. `generated_by` records the engine.
    is_generated = db.Column(db.Boolean, default=False, nullable=False)
    generated_by = db.Column(db.String(32), nullable=True)
    last_error = db.Column(db.String(500), nullable=True)  # Most recent download failure reason, if any
    last_attempt_at = db.Column(db.DateTime, nullable=True)  # When the download was last attempted
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Image id={self.id}, game_uuid={self.game_uuid}, image_type={self.image_type}, url={self.url}, downloaded={self.is_downloaded}>"

class GameRelatedMedia(db.Model):
    """Other media attached to a game — adaptations, tie-ins, soundtracks.

    Deliberately **not** media tracking. A film exists here only because it is
    the adaptation of this game; nothing is rated, progressed or watched. It is
    context on the game's page with a link out, which is what keeps this inside
    the product's scope rather than turning Oneirodex into a media tracker.
    """

    __tablename__ = 'game_related_media'

    id = db.Column(db.Integer, primary_key=True)
    game_uuid = db.Column(
        db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # film | series | anime | book | comic | music | podcast
    media_kind = db.Column(db.String(16), nullable=False)
    # adaptation | tie_in | soundtrack | novelisation | documentary | inspired_by
    relation = db.Column(db.String(20), nullable=False, default='tie_in')
    title = db.Column(db.String(240), nullable=False)
    creator = db.Column(db.String(160), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    summary = db.Column(db.String(1000), nullable=True)
    # Where to go to actually watch/read/listen. Never a download link.
    external_url = db.Column(db.String(500), nullable=True)
    cover_url = db.Column(db.String(500), nullable=True)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True,
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'game_uuid': self.game_uuid,
            'media_kind': self.media_kind,
            'relation': self.relation,
            'title': self.title,
            'creator': self.creator,
            'year': self.year,
            'summary': self.summary,
            'external_url': self.external_url,
            'cover_url': self.cover_url,
            'display_order': self.display_order or 0,
        }

class PcCheat(db.Model):
    """Operator-authored cheat notes for installed PC games (FEAT-D2).

    Deliberately **notes, not a trainer**: rows record what to change and how
    (console command, config edit, save-editor field), and Oneirodex never
    writes to a game binary or injects into a running process. That keeps the
    feature on the right side of the anti-cheat line and matches the patch
    catalog stance — the data is operator-owned, not scraped from third-party
    trainer sites.
    """

    __tablename__ = 'pc_cheats'

    id = db.Column(db.Integer, primary_key=True)
    game_uuid = db.Column(
        db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # console | config | save | launch_flag | note
    method = db.Column(db.String(16), nullable=False, default='note')
    label = db.Column(db.String(160), nullable=False)
    # The thing to type / set. Kept verbatim so it can be copied exactly.
    payload = db.Column(db.Text, nullable=True)
    notes = db.Column(db.String(1000), nullable=True)
    # Single-player only by default — multiplayer cheating is out of scope and
    # a good way to get an account banned.
    single_player_only = db.Column(db.Boolean, default=True, nullable=False)
    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True,
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        created_at = self.created_at
        if created_at is not None and created_at.tzinfo is not None:
            # This column has no timezone and the v1.1.8 API exposes its UTC
            # value as a naive ISO timestamp. Match that representation on
            # create responses too; a later database read is already naive.
            created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
        return {
            'id': self.id,
            'game_uuid': self.game_uuid,
            'method': self.method,
            'label': self.label,
            'payload': self.payload,
            'notes': self.notes,
            'single_player_only': bool(self.single_player_only),
            'created_at': created_at.isoformat() if created_at else None,
        }

class GameMode(db.Model):
    __tablename__ = 'game_modes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    games = db.relationship("Game", secondary="game_game_mode_association", back_populates="game_modes")

class Theme(db.Model):
    __tablename__ = 'themes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    games = db.relationship("Game", secondary="game_theme_association", back_populates="themes")

class Genre(db.Model):
    __tablename__ = 'genres'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    games = db.relationship("Game", secondary="game_genre_association", back_populates="genres")

class Developer(db.Model):
    __tablename__ = 'developers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True)
    games = db.relationship("Game", back_populates="developer")

class Publisher(db.Model):
    __tablename__ = 'publishers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True)
    games = db.relationship("Game", back_populates="publisher")

class Platform(db.Model):
    __tablename__ = 'platforms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    games = db.relationship("Game", secondary="game_platform_association", back_populates="platforms")

class PlayerPerspective(db.Model):
    __tablename__ = 'player_perspectives'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    games = db.relationship("Game", secondary="game_player_perspective_association", back_populates="player_perspectives")

class MultiplayerMode(db.Model):
    __tablename__ = 'multiplayer_modes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)
    games = db.relationship("Game", secondary="game_multiplayer_mode_association", back_populates="multiplayer_modes")

def genre_choices():
    return db.session.execute(select(Genre)).scalars().all()

def game_mode_choices():
    return db.session.execute(select(GameMode)).scalars().all()

def theme_choices():
    return db.session.execute(select(Theme)).scalars().all()

def platform_choices():
    return db.session.execute(select(Platform)).scalars().all()

def player_perspective_choices():
    return db.session.execute(select(PlayerPerspective)).scalars().all()

def developer_choices():
    return db.session.execute(select(Developer)).scalars().all()

def publisher_choices():
    return db.session.execute(select(Publisher)).scalars().all()

class ReferenceSet(db.Model):
    """Operator-uploaded No-Intro/Redump DAT for ROM set completeness."""

    __tablename__ = 'reference_sets'
    __table_args__ = (
        db.UniqueConstraint(
            'library_platform',
            'region',
            name='uq_reference_set_platform_region',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    library_platform = db.Column(db.String(32), nullable=False, index=True)
    region = db.Column(db.String(16), nullable=False, index=True)
    source = db.Column(db.String(16), nullable=False, default='nointro')
    name = db.Column(db.String(255), nullable=False, default='')
    entry_count = db.Column(db.Integer, nullable=False, default=0)
    uploaded_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    uploaded_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    entries = db.relationship(
        'ReferenceSetEntry',
        back_populates='reference_set',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'library_platform': self.library_platform,
            'region': self.region,
            'source': self.source,
            'name': self.name,
            'entry_count': self.entry_count,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }

class RetroAchievementsIndexEntry(db.Model):
    """One (console, hash) row of the RetroAchievements game list.

    Refreshed per console from `API_GetGameList.php?h=1&f=1` (games that carry
    achievements, with every hash they accept). A game appears once per hash.
    """

    __tablename__ = 'retroachievements_index'
    __table_args__ = (
        db.Index('ix_ra_index_console_md5', 'console_id', 'md5'),
    )

    id = db.Column(db.Integer, primary_key=True)
    console_id = db.Column(db.Integer, nullable=False, index=True)
    ra_game_id = db.Column(db.Integer, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False, default='', server_default='')
    image_icon = db.Column(db.String(255), nullable=True)
    num_achievements = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    points = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    md5 = db.Column(db.String(32), nullable=False)
    fetched_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class GameVrProfile(db.Model):
    """How one title is played in a headset, as a record (INSP-40, v11 H3a).

    One row per (game, kind): ``native`` (ships a VR mode), ``injector`` (a
    community profile exists -- ``profile_url`` is *its page*), ``flat`` (no
    VR; stream it). ``runtime`` names the OpenXR / OpenVR side when known.
    Catalogue data and a deep link only: nothing here is a shim, an
    installer or a path on disk. ``Game.vr_compat`` derives from these rows
    when a librarian did not set it directly.
    """

    __tablename__ = 'game_vr_profiles'
    __table_args__ = (
        db.UniqueConstraint('game_uuid', 'kind', name='uq_game_vr_profiles_game_kind'),
    )

    id = db.Column(db.Integer, primary_key=True)
    game_uuid = db.Column(db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'), nullable=False, index=True)
    kind = db.Column(db.String(16), nullable=False)  # native | injector | flat
    runtime = db.Column(db.String(16), nullable=True)  # openxr | openvr
    profile_url = db.Column(db.String(2048), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(32), nullable=False, default='librarian', server_default='librarian')  # librarian | community
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    game = db.relationship('Game', backref=db.backref('vr_profiles', lazy='selectin', cascade='all, delete-orphan'))

    def to_dict(self) -> dict:
        return {
            'kind': self.kind,
            'runtime': self.runtime,
            'profile_url': self.profile_url,
            'notes': self.notes or '',
            'source': self.source or 'librarian',
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ReferenceSetEntry(db.Model):
    """One game/ROM row from a reference DAT."""

    __tablename__ = 'reference_set_entries'
    __table_args__ = (
        db.Index('ix_reference_set_entries_set_norm', 'set_id', 'normalized_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    set_id = db.Column(
        db.Integer,
        db.ForeignKey('reference_sets.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(512), nullable=False)
    normalized_name = db.Column(db.String(512), nullable=False)
    # 1G1R (INSP-5): the parent set this entry is a clone of (`cloneof`), else
    # NULL. "One game, one ROM" = entries with no parent.
    parent_name = db.Column(db.String(512), nullable=True)
    crc = db.Column(db.String(16), nullable=True)
    md5 = db.Column(db.String(32), nullable=True)
    sha1 = db.Column(db.String(40), nullable=True)
    size = db.Column(db.BigInteger, nullable=True)
    serial = db.Column(db.String(64), nullable=True)

    reference_set = db.relationship('ReferenceSet', back_populates='entries')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'normalized_name': self.normalized_name,
            'crc': self.crc,
            'md5': self.md5,
            'sha1': self.sha1,
            'size': self.size,
            'serial': self.serial,
        }

class IgdbPlatformRelease(db.Model):
    """Cached IGDB release_dates row for a library platform + region."""

    __tablename__ = 'igdb_platform_releases'
    __table_args__ = (
        db.UniqueConstraint(
            'library_platform',
            'igdb_game_id',
            'region_code',
            name='uq_igdb_platform_release',
        ),
        db.Index(
            'ix_igdb_platform_releases_platform_region',
            'library_platform',
            'region_code',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    library_platform = db.Column(db.String(32), nullable=False, index=True)
    igdb_game_id = db.Column(db.Integer, nullable=False, index=True)
    igdb_platform_id = db.Column(db.Integer, nullable=True)
    region_code = db.Column(db.String(16), nullable=False)
    igdb_region = db.Column(db.Integer, nullable=True)
    name = db.Column(db.String(512), nullable=False, default='')
    released_at = db.Column(db.DateTime, nullable=True)
    fetched_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self) -> dict:
        return {
            'library_platform': self.library_platform,
            'igdb_game_id': self.igdb_game_id,
            'igdb_platform_id': self.igdb_platform_id,
            'region_code': self.region_code,
            'igdb_region': self.igdb_region,
            'name': self.name,
            'released_at': self.released_at.isoformat() if self.released_at else None,
            'fetched_at': self.fetched_at.isoformat() if self.fetched_at else None,
        }

# Helper function for game completion status
def get_status_info(status):
    """
    Returns icon and color information for game completion status

    Args:
        status: str - One of 'unplayed', 'unfinished', 'beaten', 'completed', 'null', or None

    Returns:
        dict with 'icon', 'color', 'label' keys
    """
    status_map = {
        'unplayed': {
            'icon': 'fa-box',
            'color': '#808080',  # gray
            'label': 'Unplayed'
        },
        'unfinished': {
            'icon': 'fa-gamepad',
            'color': '#4A90E2',  # blue
            'label': 'Unfinished'
        },
        'beaten': {
            'icon': 'fa-flag-checkered',
            'color': '#50C878',  # green
            'label': 'Beaten'
        },
        'completed': {
            'icon': 'fa-trophy',
            'color': '#FFD700',  # gold
            'label': 'Completed'
        },
        'null': {
            'icon': 'fa-ban',
            'color': '#DC3545',  # red
            'label': "Won't Play"
        }
    }

    # Return empty icon for no status
    if not status:
        return {
            'icon': 'fa-circle',
            'color': '#808080',
            'label': 'No Status',
            'empty': True
        }

    return status_map.get(status, status_map['unplayed'])


__all__ = [
    "game_genre_association",
    "game_game_mode_association",
    "game_theme_association",
    "game_platform_association",
    "game_multiplayer_mode_association",
    "game_player_perspective_association",
    "game_developer_association",
    "Category",
    "Status",
    "Game",
    "GameUpdate",
    "GameExtra",
    "GameURL",
    "Image",
    "GameRelatedMedia",
    "PcCheat",
    "GameMode",
    "Theme",
    "Genre",
    "Developer",
    "Publisher",
    "Platform",
    "PlayerPerspective",
    "MultiplayerMode",
    "genre_choices",
    "game_mode_choices",
    "theme_choices",
    "platform_choices",
    "player_perspective_choices",
    "developer_choices",
    "publisher_choices",
    "ReferenceSet",
    "ReferenceSetEntry",
    "GameVrProfile",
    "RetroAchievementsIndexEntry",
    "IgdbPlatformRelease",
    "get_status_info",
]
