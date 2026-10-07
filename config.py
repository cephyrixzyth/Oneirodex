import os, sys

from dotenv import load_dotenv

from product_env import getenv_product

# Populate os.environ from a repo-root .env before Config reads it. This is
# idempotent: init_manager.py (operator boot) and conftest.py (tests) also call
# load_dotenv(), and python-dotenv defaults to override=False, so an already-set
# process env var always wins. Without this, importing Config off a bare
# ``python -c "from oneirodex import create_app"`` (no .env pre-loaded) ran on
# defaults only and _load_secret_key() would raise.
load_dotenv()


def keep_psycopg2_for_plain_postgresql_urls() -> None:
    """Keep ``postgresql://`` URLs on psycopg2.

    SQLAlchemy 2.1 made psycopg (v3) the driver for a URL without ``+driver``.
    The app, its tests, Alembic and every operator's ``DATABASE_URL`` use the
    plain form with psycopg2 installed, so without this each of them failed
    with ``No module named 'psycopg'``. Explicit ``postgresql+psycopg://`` URLs
    are untouched. Harmless on SQLAlchemy 2.0, where this is the default.
    """
    from sqlalchemy.dialects import registry

    registry.register('postgresql', 'sqlalchemy.dialects.postgresql.psycopg2', 'PGDialect_psycopg2')


keep_psycopg2_for_plain_postgresql_urls()


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean env var.

    Returns ``default`` when the var is unset; otherwise true iff the value is
    one of ``1 / true / yes / on`` (case-insensitive, surrounding whitespace
    ignored). Replaces the ~40 near-identical getenv/lower/compare parses that
    used to fill this file. Each flag keeps its previous effective default: a
    former ``'true'`` default becomes ``_env_bool('NAME', True)``.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name: str, default: int = 0) -> int:
    """Parse a non-negative integer env var; ``default`` when unset or invalid.

    For limits where 0 means "the built-in default": a typo such as ``256MB``
    used to raise out of ``import config`` without naming the variable, so the
    app did not start. It now logs which variable was ignored and carries on.
    """
    raw = (os.getenv(name) or '').strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        import logging

        logging.getLogger(__name__).warning(
            '%s=%r is not a whole number of bytes; using the default', name, raw
        )
        return default
    return value


def _load_secret_key():
    """Load SECRET_KEY from env. Fail loudly if unset outside of test runs."""
    key = os.getenv('SECRET_KEY')
    if key and key != 'put_your_own_secret_string_here_32617432':
        return key
    # Allow pytest runs to proceed with a generated key; never silently used in prod.
    if 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ:
        import secrets
        return secrets.token_urlsafe(64)
    raise RuntimeError(
        "SECRET_KEY environment variable is not set (or still has the example value). "
        "Generate a strong random value (e.g. `python -c 'import secrets; print(secrets.token_urlsafe(64))'`) "
        "and set it in your .env file before starting the application."
    )

def _parse_library_roots(raw):
    """Parse ONEIRODEX_LIBRARY_ROOTS at import time so app.config carries the list.

    The parser is imported lazily to keep config.py free of package imports at
    module scope; a failure here must leave the app booting with no extra
    roots rather than not booting at all.
    """
    try:
        from oneirodex.utils.library_roots import parse_library_roots
    except Exception:  # pragma: no cover - defensive, keeps boot resilient
        return []
    return parse_library_roots(raw)


class Config(object):
    # Set Database connection string here or in your .env file, when using docker set the hostname to 'db'
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/oneirodex')

    # Host path to on-disk game files (Compose mounts to /storage in the container)
    DATA_FOLDER_GAMES = os.getenv('DATA_FOLDER_GAMES', r'Z:\gamez')

    # OS-specific base folder paths
    if os.name == 'nt':  # Windows
        BASE_FOLDER_WINDOWS = os.getenv('BASE_FOLDER_WINDOWS', 'Z:\\')
    else:  # POSIX (Linux, Unix, MacOS, etc.)
        BASE_FOLDER_POSIX = os.getenv('BASE_FOLDER_POSIX', '/storage')

    # Extra scan locations beyond the single base folder above: NAS shares, a
    # second internal disk, additional Docker binds. Entries are separated by
    # "|" and may carry a display label:
    #   ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=/mnt/nas/roms|Archive=/mnt/archive/games
    # Mounting the share stays the operator's job — this only tells Oneirodex
    # which mounts are libraries. See docs/runbooks/remote-scan-locations.md.
    LIBRARY_ROOTS = _parse_library_roots(getenv_product('LIBRARY_ROOTS'))

    # YOU CAN LEAVE ALL THESE SETTINGS AT DEFAULT:
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'oneirodex/static/library')
    SECRET_KEY = _load_secret_key()
    IMAGE_SAVE_PATH = os.path.join(os.path.dirname(__file__), 'oneirodex/static/library/images')
    IGDB_API_ENDPOINT = os.getenv('IGDB_API_ENDPOINT', 'https://api.igdb.com/v4/games')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session/remember-me cookie hardening. Defaults are safe for HTTPS deployments;
    # Set both cookie Secure flags false only when deliberately using direct HTTP.
    SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
    REMEMBER_COOKIE_SECURE = _env_bool('REMEMBER_COOKIE_SECURE', True)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = os.getenv('REMEMBER_COOKIE_SAMESITE', 'Lax')

    # HTTP security response headers — see oneirodex/utils/security_headers.py.
    # CSP enforces by default. Classic onclick= is gone; WebRetro WASM is a
    # native /static/* document with baseline headers only (no CSP), so Flask
    # pages do not need 'unsafe-eval'. Set CSP_ENFORCE=false to report-only.
    CSP_ENABLED = _env_bool('CSP_ENABLED', True)
    CSP_ENFORCE = _env_bool('CSP_ENFORCE', True)
    # Only sent when SESSION_COOKIE_SECURE is on — HSTS on a LAN box reached by
    # IP over plain HTTP is a lockout, not a hardening.
    HSTS_SECONDS = int(os.getenv('HSTS_SECONDS', '31536000') or '31536000')

    # Firmware upload ceiling. utils/emulator_bios.py already reads this from
    # config and documents the override, but nothing ever populated it, so the
    # env var silently did nothing and the 64MB default always won.
    EMULATOR_BIOS_MAX_BYTES = _env_int('EMULATOR_BIOS_MAX_BYTES')

    # Total .cht storage across every game (0 = the built-in 256 MB). Each game
    # is separately capped at 200 files of 1 MB; this is the bound on the sum.
    CHEAT_STORAGE_MAX_BYTES = _env_int('CHEAT_STORAGE_MAX_BYTES')

    # Total retained chat-attachment storage. Zero/unset keeps the bounded
    # 1 GiB default; operators can raise the cap to match their library volume.
    CHAT_ATTACHMENT_STORAGE_MAX_BYTES = (
        _env_int('CHAT_ATTACHMENT_STORAGE_MAX_BYTES') or (1024 * 1024 * 1024)
    )
    # Maximum regular files retained across all chat channels and users.
    # Zero/unset keeps the bounded 10,000-file default.
    CHAT_ATTACHMENT_STORAGE_MAX_FILES = (
        max(1, _env_int('CHAT_ATTACHMENT_STORAGE_MAX_FILES') or 10_000)
    )

    # Global request-body ceiling. Every upload route already has its own,
    # tighter limit (firmware at 64MB is the largest); without this one, none of
    # them applied until after Werkzeug had buffered the whole body. Default
    # keeps headroom over the firmware cap so raising that alone cannot wedge
    # uploads behind a lower global limit.
    _bios_mb = (EMULATOR_BIOS_MAX_BYTES or (64 * 1024 * 1024)) // (1024 * 1024)
    MAX_UPLOAD_MB = int(
        os.getenv('MAX_UPLOAD_MB', '') or max(128, _bios_mb + 16)
    )
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024

    # Zipstream configuration for streaming ZIP downloads
    ZIPSTREAM_CHUNK_SIZE = int(os.getenv('ZIPSTREAM_CHUNK_SIZE', 65536))  # 64KB chunks for memory efficiency
    ZIPSTREAM_COMPRESSION_LEVEL = int(os.getenv('ZIPSTREAM_COMPRESSION_LEVEL', 0))  # ZIP_STORED for compatibility
    ZIPSTREAM_ENABLE_ZIP64 = _env_bool('ZIPSTREAM_ENABLE_ZIP64', True)  # Support large games

    # Development mode - forces theme files to be recopied on startup (helpful for theme development)
    DEV_MODE = _env_bool('DEV_MODE', False)

    # Reverse proxy / HTTPS termination — number of trusted proxy hops (0 = disabled).
    # Set to 1 when Oneirodex sits behind a single reverse proxy (nginx, Caddy, Traefik)
    # so X-Forwarded-Proto/Host are honored for OIDC redirects and external URLs.
    TRUSTED_PROXIES = int(os.getenv('TRUSTED_PROXIES', '0') or '0')

    # Hosts allowed to become the origin of an emailed link (password reset,
    # invite). Empty = trust private/LAN hosts only, which is what a household
    # install reached by IP needs. Set it when Oneirodex is published on a public
    # hostname. Comma separated, port optional: "games.example.com,10.0.0.5:5006".
    #
    # Deliberately NOT named TRUSTED_HOSTS: Werkzeug (pinned werkzeug==3.1.8 in
    # requirements.txt) reads that key itself and rejects any unlisted Host with a
    # 400 before a route runs. It also expects a list — handing it this comma
    # string would iterate per character and lock the install out entirely.
    # tests/test_trusted_host.py caught exactly that. If you bump Werkzeug, re-read
    # its TRUSTED_HOSTS handling before assuming this separation still holds.
    # Operators who want that stricter app-wide enforcement set Flask's
    # TRUSTED_HOSTS to a real list; this key only governs email links.
    TRUSTED_LINK_HOSTS = os.getenv('TRUSTED_LINK_HOSTS', '')

    # Product modules default ON — disable via env, setup wizard, or Admin → Features.
    # Auth (OIDC) stays off by default elsewhere. Destructive auto-apply stays gated.
    ENABLE_ARR_MODULE = _env_bool('ENABLE_ARR_MODULE', True)

    # Emulator save-state sync (WebRetro / companion)
    ENABLE_EMULATOR_SAVE_SYNC = _env_bool('ENABLE_EMULATOR_SAVE_SYNC', True)
    ENCRYPT_EMULATOR_SAVES = _env_bool('ENCRYPT_EMULATOR_SAVES', False)
    # Optional private BIOS/firmware dir (operator upload or host volume). Never vendor blobs.
    # When unset, bios_root() falls back to static/library/bios.
    EMULATOR_BIOS_PATH = os.getenv('EMULATOR_BIOS_PATH') or None

    # Ollama AI assist (suggestions on; silent rename stays off)
    ENABLE_AI_ASSIST = _env_bool('ENABLE_AI_ASSIST', True)
    ENABLE_AI_AUTO_APPLY = _env_bool('ENABLE_AI_AUTO_APPLY', False)

    # Generated cover art (FEAT-D3). Off by default: this is the only feature
    # that talks to an endpoint outside the process, so it stays opt-in and
    # self-hosted-first. Engine speaks the A1111 API (AUTOMATIC1111 / SD.Next /
    # Forge all implement it).
    # FEAT-D1: check version / updates / DLC after a library scan. Opt-in —
    # each check is store HTTP traffic, so a scan must not start doing it
    # without being asked.
    SCAN_CHECK_FRESHNESS = _env_bool('SCAN_CHECK_FRESHNESS', False)
    SCAN_FRESHNESS_LIMIT = int(os.getenv('SCAN_FRESHNESS_LIMIT', '50'))

    ENABLE_AI_ARTWORK = _env_bool('ENABLE_AI_ARTWORK', False)
    AI_ARTWORK_URL = os.getenv('AI_ARTWORK_URL', '')
    AI_ARTWORK_ENGINE = os.getenv('AI_ARTWORK_ENGINE', 'a1111')
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')

    # UIR-1 two-bar chrome. Default flipped to **true** (W27-A3): the migration
    # this flag was waiting on is finished. All eleven member pages carry the
    # branch, and the shell stopped being optional when TopNav.jsx was deleted
    # and SideRail/TopBar became the only chrome App.jsx renders.
    #
    # Left off, the flag produced the exact half-migrated layout it existed to
    # prevent — the new bar naming the page, and every page still drawing its
    # own title card underneath it.
    #
    # Still not an admin Features toggle, for the original reason: it is a
    # build-out flag, and a switch in the admin UI that only half-changes the
    # layout would be its own lie.
    ENABLE_NEW_CHROME = _env_bool('ENABLE_NEW_CHROME', True)

    # Theme fonts. Empty FONT_PATH means the default under static/library/fonts,
    # which is what a Compose deploy wants (it already persists that volume).
    FONT_PATH = os.getenv('FONT_PATH', '')
    FONT_MAX_BYTES = int(os.getenv('FONT_MAX_BYTES', str(8 * 1024 * 1024)))
    # Install the built-in OFL faces on first boot rather than leaving them to a
    # script nobody knows to run — the picker offered five fonts and shipped
    # none. Runs in the background and never blocks or fails startup. Turn off
    # for air-gapped installs and use scripts/fetch-fonts.py --out instead.
    FETCH_FONTS_ON_BOOT = _env_bool('FETCH_FONTS_ON_BOOT', True)

    # WebRetro cores are provisioned, not vendored — they carry GPL and
    # non-commercial terms that make shipping them in the tree the wrong call.
    # Off means browser play stays dark until an operator runs
    # scripts/fetch-webretro-cores.sh (which also takes --from-dir for
    # air-gapped installs). Boot says so in the log rather than leaving it to be
    # discovered as "browser play is broken".
    FETCH_WEBRETRO_CORES_ON_BOOT = _env_bool('FETCH_WEBRETRO_CORES_ON_BOOT', True)

    # Point at a local firmware collection to have it imported on boot. Existing
    # files are never replaced, so this tops up what is missing and is safe to
    # leave set. Unset means no import.
    BIOS_IMPORT_SOURCE = os.getenv('BIOS_IMPORT_SOURCE', '') or None

    # Hardlink helpers on; filesystem apply remains a safety lock
    ENABLE_HARDLINK_HELPERS = _env_bool('ENABLE_HARDLINK_HELPERS', True)
    ALLOW_HARDLINK_APPLY = _env_bool('ALLOW_HARDLINK_APPLY', False)
    ENABLE_ARR_HARDLINK_PIPELINE = _env_bool('ENABLE_ARR_HARDLINK_PIPELINE', True)
    # Remote path mapping. The download client usually runs in its own
    # container and reports paths from *its* mounts, which do not exist here.
    # Format: "remote=>local" pairs joined by "|", e.g.
    #   /downloads=>/storage/downloads|/data/torrents=>/mnt/user/torrents
    # Empty (the default) means client and app share a filesystem view.
    ARR_REMOTE_PATH_MAP = os.getenv('ARR_REMOTE_PATH_MAP', '')

    # Mobile / Quest-browser VR catalog
    ENABLE_VR_BROWSE = _env_bool('ENABLE_VR_BROWSE', True)

    # BYO debrid + single-player assists
    ENABLE_DEBRID = _env_bool('ENABLE_DEBRID', True)
    ENABLE_GAME_ASSISTS = _env_bool('ENABLE_GAME_ASSISTS', True)
    REAL_DEBRID_TOKEN = os.getenv('REAL_DEBRID_TOKEN', '')
    ALLDEBRID_API_KEY = os.getenv('ALLDEBRID_API_KEY', '')
    PREMIUMIZE_API_KEY = os.getenv('PREMIUMIZE_API_KEY', '')
    TORBOX_API_KEY = os.getenv('TORBOX_API_KEY', '')

    # Browser play / mods / patches — on by default; degrade gracefully if tools missing
    ENABLE_PCDOS_BROWSER = _env_bool('ENABLE_PCDOS_BROWSER', True)
    ENABLE_MOD_TRACKING = _env_bool('ENABLE_MOD_TRACKING', True)
    ENABLE_ROM_PATCH_APPLY = _env_bool('ENABLE_ROM_PATCH_APPLY', True)
    # DAT unique-hash: open zip/7z/rar and hash inner dump when outer archive hash misses.
    # Default ON; set DAT_HASH_INNER_ARCHIVE=0 to skip (scan stays basename/outer-hash only).
    DAT_HASH_INNER_ARCHIVE = _env_bool('DAT_HASH_INNER_ARCHIVE', True)
    FLIPS_PATH = os.getenv('FLIPS_PATH', '')
    ENABLE_PATCH_CATALOG = _env_bool('ENABLE_PATCH_CATALOG', True)
    PATCH_CATALOG_PATH = os.getenv('PATCH_CATALOG_PATH', '')
    ENABLE_ROM_AI_TRANSLATE = _env_bool('ENABLE_ROM_AI_TRANSLATE', True)
    RETROARCH_AI_SERVICE_URL = os.getenv('RETROARCH_AI_SERVICE_URL', '')
    ENABLE_RUFFLE = _env_bool('ENABLE_RUFFLE', True)
    ENABLE_ACTIVITY_FEED = _env_bool('ENABLE_ACTIVITY_FEED', True)

    # Household voice (LiveKit) — flag on; UI degrades until LIVEKIT_* configured
    ENABLE_LIVEKIT = _env_bool('ENABLE_LIVEKIT', True)

    # BYO Sunshine / Wolf remote play (Moonlight) — off by default; operator-owned GPU host
    ENABLE_REMOTE_PLAY = _env_bool('ENABLE_REMOTE_PLAY', False)
    SUNSHINE_BASE_URL = os.getenv('SUNSHINE_BASE_URL', '')
    WOLF_BASE_URL = os.getenv('WOLF_BASE_URL', '')
    REMOTE_PLAY_PROVIDER = os.getenv('REMOTE_PLAY_PROVIDER', 'sunshine')
    REMOTE_PLAY_TOKEN = os.getenv('REMOTE_PLAY_TOKEN', '')
    REMOTE_PLAY_TOKEN_HINT = os.getenv('REMOTE_PLAY_TOKEN_HINT', '')
    REMOTE_PLAY_PIN_HINT = os.getenv('REMOTE_PLAY_PIN_HINT', '')
    REMOTE_PLAY_APP_HINT = os.getenv('REMOTE_PLAY_APP_HINT', '')
    REMOTE_PLAY_HOST_LABEL = os.getenv('REMOTE_PLAY_HOST_LABEL', '')

    # Archive / library malware scan (ClamAV when available + filename heuristics)
    ENABLE_MALWARE_SCAN = _env_bool('ENABLE_MALWARE_SCAN', True)
    CLAMAV_HOST = os.getenv('CLAMAV_HOST', '127.0.0.1')
    CLAMAV_PORT = int(os.getenv('CLAMAV_PORT', '3310') or '3310')
    CLAMAV_SOCKET = os.getenv('CLAMAV_SOCKET', '')
    MALWARE_SCAN_BLOCK_ON_HIT = _env_bool('MALWARE_SCAN_BLOCK_ON_HIT', True)

    # Wave 18 — free games feed (News + notifications)
    ENABLE_FREE_GAMES = _env_bool('ENABLE_FREE_GAMES', True)
    FREE_GAMES_POLL_HOURS = float(os.getenv('FREE_GAMES_POLL_HOURS', '3') or '3')
    # Look a giveaway's cover up on IGDB when the store has no portrait URL of
    # its own (GOG, itch, Humble, IndieGala, Epic via GamerPower). Results are
    # memoized for a month, so this is roughly one call per new title. Off
    # leaves those tiles on the aggregator's wide banner.
    ENABLE_FREE_GAMES_COVER_LOOKUP = _env_bool('ENABLE_FREE_GAMES_COVER_LOOKUP', True)
    # Discover's on-box recommender. Off means the rebuild daemon never starts;
    # Discover keeps working and the rows that depend on a profile stay empty.
    ENABLE_DISCOVER_ML = _env_bool('ENABLE_DISCOVER_ML', True)
    DISCOVER_ML_REBUILD_HOURS = float(
        os.getenv('DISCOVER_ML_REBUILD_HOURS', '24') or '24'
    )

    # Batched email digest (mentions / DMs / free games) — needs admin SMTP
    ENABLE_EMAIL_DIGEST = _env_bool('ENABLE_EMAIL_DIGEST', True)
    EMAIL_DIGEST_INTERVAL_HOURS = float(os.getenv('EMAIL_DIGEST_INTERVAL_HOURS', '24') or '24')

    # Auth rate limit (in-process; single-container default)
    ENABLE_LOGIN_RATE_LIMIT = _env_bool('ENABLE_LOGIN_RATE_LIMIT', True)
    LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv('LOGIN_RATE_LIMIT_ATTEMPTS', '10') or '10')
    LOGIN_RATE_LIMIT_WINDOW_SECONDS = float(os.getenv('LOGIN_RATE_LIMIT_WINDOW_SECONDS', '300') or '300')

    # BYO challenge / captcha solver sidecar (FlareSolverr-compatible TRAWL) — opt-in only.
    ENABLE_CHALLENGE_SOLVER = _env_bool('ENABLE_CHALLENGE_SOLVER', False)
    CHALLENGE_SOLVER_URL = os.getenv('CHALLENGE_SOLVER_URL', '')
    CHALLENGE_SOLVER_PROVIDER = os.getenv('CHALLENGE_SOLVER_PROVIDER', 'flaresolverr_compat')
    CHALLENGE_SOLVER_TIMEOUT_MS = int(os.getenv('CHALLENGE_SOLVER_TIMEOUT_MS', '60000') or '60000')
    CHALLENGE_SOLVER_MAX_TIER = int(os.getenv('CHALLENGE_SOLVER_MAX_TIER', '5') or '5')
    CHALLENGE_TOKEN_API_URL = os.getenv('CHALLENGE_TOKEN_API_URL', '')
    CHALLENGE_TOKEN_API_KEY = os.getenv('CHALLENGE_TOKEN_API_KEY', '')

    # Ambient lighting bridge (Hyperion.ng / Home Assistant) — opt-in only.
    ENABLE_AMBIENT_LIGHTING = _env_bool('ENABLE_AMBIENT_LIGHTING', False)
    LIGHTING_PROVIDER = os.getenv('LIGHTING_PROVIDER', 'off')
    HYPERION_URL = os.getenv('HYPERION_URL', '')
    HYPERION_TOKEN = os.getenv('HYPERION_TOKEN', '')
    HYPERION_PRIORITY = int(os.getenv('HYPERION_PRIORITY', '50') or '50')
    AMBIENT_ACCENT_COLOR = os.getenv('AMBIENT_ACCENT_COLOR', '255,128,32')
    HA_URL = os.getenv('HA_URL', os.getenv('HOME_ASSISTANT_URL', ''))
    HA_TOKEN = os.getenv('HA_TOKEN', os.getenv('HOME_ASSISTANT_TOKEN', ''))
    HA_LIGHT_ENTITIES = os.getenv('HA_LIGHT_ENTITIES', '')
    HA_PLAY_SCENE = os.getenv('HA_PLAY_SCENE', '')
    HA_STOP_SCENE = os.getenv('HA_STOP_SCENE', '')

    # Homelab SSRF policy — *arr / Ollama / connector URLs may target RFC1918 hosts.
    # Cloud metadata (169.254.169.254) stays blocked. Default on for Unraid/NAS installs.
    ALLOW_PRIVATE_LAN_URLS = _env_bool('ALLOW_PRIVATE_LAN_URLS', True)

    # When true (default), OIDC JIT updates never overwrite an existing user's role.
    OIDC_LOCK_ROLES = _env_bool('OIDC_LOCK_ROLES', True)
    # Link an existing account by email even when the provider does not mark
    # the address verified. Only for a provider whose admins set users' emails.
    OIDC_TRUST_PROVIDER_EMAIL = _env_bool('OIDC_TRUST_PROVIDER_EMAIL', False)

    # AGPL §13: a user interacting with this over a network must be offered the
    # Corresponding Source. README states the obligation; this is what actually
    # discharges it in the running app.
    #
    # Configurable precisely because §13 is about *this* deployment: if you
    # modify Oneirodex and run it for others, you owe them **your** source, not
    # upstream's. Point this at your fork before you deploy a modified build.
    ONEIRODEX_SOURCE_URL = getenv_product(
        'SOURCE_URL', 'https://github.com/cephyrixzyth/oneirodex'
    )

    # In-app support → GitHub Issues (optional; tickets still save without a token)
    SUPPORT_GITHUB_TOKEN = os.getenv('SUPPORT_GITHUB_TOKEN', '')
    SUPPORT_GITHUB_REPO = os.getenv('SUPPORT_GITHUB_REPO', 'cephyrixzyth/oneirodex')

    # Optional *arr connector defaults (overridden by Admin → Arr config)
    PROWLARR_URL = os.getenv('PROWLARR_URL', '')
    PROWLARR_API_KEY = os.getenv('PROWLARR_API_KEY', '')
    JACKETT_URL = os.getenv('JACKETT_URL', '')
    JACKETT_API_KEY = os.getenv('JACKETT_API_KEY', '')
    QBITTORRENT_URL = os.getenv('QBITTORRENT_URL', '')
    QBITTORRENT_USERNAME = os.getenv('QBITTORRENT_USERNAME', 'admin')
    QBITTORRENT_PASSWORD = os.getenv('QBITTORRENT_PASSWORD', '')
    TRANSMISSION_URL = os.getenv('TRANSMISSION_URL', '')
    TRANSMISSION_USERNAME = os.getenv('TRANSMISSION_USERNAME', '')
    TRANSMISSION_PASSWORD = os.getenv('TRANSMISSION_PASSWORD', '')
    DELUGE_URL = os.getenv('DELUGE_URL', '')
    DELUGE_PASSWORD = os.getenv('DELUGE_PASSWORD', '')
    SABNZBD_URL = os.getenv('SABNZBD_URL', '')
    SABNZBD_API_KEY = os.getenv('SABNZBD_API_KEY', '')

    # Flask-Babel / i18n
    BABEL_DEFAULT_LOCALE = os.getenv('BABEL_DEFAULT_LOCALE', 'en')
    BABEL_SUPPORTED_LOCALES = ['en', 'es']


class ProdConfig(Config):
    """Explicit production profile — what create_app() selects outside pytest.

    Config already holds production-safe values; this names the profile so the
    selection in create_app() is symmetric and any future prod-only override
    has an obvious home.
    """

    DEBUG = False
    TESTING = False


class TestConfig(Config):
    """Test profile. create_app() selects this automatically under pytest.

    Carries what conftest.py's ``app`` fixture and oneirodex/__init__.py's
    pytest branch used to set on the instance *after* construction (wave
    A2.6):

    * ``TESTING`` / CSRF off so the test client skips token plumbing.
    * ``SERVER_NAME`` / ``APPLICATION_ROOT`` / ``PREFERRED_URL_SCHEME`` so
      ``url_for(..., _external=True)`` works outside a request context — Flask
      raises "Unable to build URLs outside an active request without
      SERVER_NAME" otherwise. A real ``SERVER_NAME`` in ``Config`` would start
      rejecting requests whose Host header does not match, which is why it
      lives here and not there.
    * the test database URI, taken explicitly from ``TEST_DATABASE_URL`` (with
      the ``DATABASE_URL`` override conftest also sets as a fallback).
    """

    TESTING = True
    DEBUG = False
    WTF_CSRF_ENABLED = False
    SERVER_NAME = 'localhost'
    APPLICATION_ROOT = '/'
    PREFERRED_URL_SCHEME = 'http'
    # Stable across app instances within a run — matches the value conftest
    # used to force on the instance. _load_secret_key() would otherwise hand
    # each create_app() a fresh ephemeral key.
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = (
        os.getenv('TEST_DATABASE_URL')
        or os.getenv('DATABASE_URL')
        or Config.SQLALCHEMY_DATABASE_URI
    )
