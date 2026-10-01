#/oneirodex/__init__.py
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
from config import Config
from datetime import datetime
from urllib.parse import urlparse
from flask_caching import Cache
from oneirodex.utils.db import check_postgres_port_open
from oneirodex.utils.proxy import apply_proxy_fix
from oneirodex.utils.security_headers import apply_security_headers
from oneirodex.utils.icon_themes import icon_pack_css_url, icon_pack_previews_css_url
from oneirodex.product import PRODUCT_NAME
from oneirodex.utils.preset_themes import era_for_theme, theme_picker_groups
import logging

logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()
cache = Cache(config={'CACHE_TYPE': 'SimpleCache'})
csrf = CSRFProtect()
app_start_time = datetime.now()


def _read_version() -> str:
    """The product version, from the tracked ``VERSION`` file at the repo root.

    It used to be a literal here while ``VERSION`` sat beside it holding the
    same string and nothing read it -- two sources that agreed only as long as
    somebody remembered to change both. The literal stays as the fallback for a
    checkout or image that lost the file; ``tests/test_build_identity.py``
    asserts the two agree so they cannot drift again.
    """
    try:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'VERSION')
        with open(path, encoding='utf-8') as handle:
            text = handle.read().strip()
        return text or '1.0.0'
    except OSError:
        return '1.0.0'


app_version = _read_version()


def create_app(config_object=None):
    """Build the Flask app.

    ``config_object`` defaults to :class:`config.Config` (production), or
    :class:`config.TestConfig` when running under pytest. Pass an explicit
    class to override — scripts and the ASGI entrypoint rely on the default.
    """
    app = Flask(__name__)
    if config_object is None:
        if 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ:
            from config import TestConfig
            config_object = TestConfig
        else:
            config_object = Config
    app.config.from_object(config_object)

    # Wire stdlib logging before anything else logs. Level from
    # ONEIRODEX_LOG_LEVEL (default INFO), JSON via ONEIRODEX_LOG_JSON=1.
    from oneirodex.utils.logging_setup import configure_logging
    configure_logging(app)

    # SAFETY CHECK: Prevent production database access during tests
    if 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ:
        from database_test_guard import validate_test_database_url
        test_db_url = validate_test_database_url(os.getenv('TEST_DATABASE_URL'))
        if app.config.get('SQLALCHEMY_DATABASE_URI') != test_db_url:
            raise RuntimeError('CRITICAL: App test database configuration mismatch; connection details withheld.')
        logger.info('PYTEST MODE: validated test database configuration')
    
    csrf.init_app(app)
    apply_proxy_fix(app)
    apply_security_headers(app)
    from oneirodex.utils.library_paths import library_dir, relocated_library_dir
    app.config['UPLOAD_FOLDER'] = library_dir(app.root_path)
    if relocated_library_dir():
        # Standalone install (ADR 0011): runtime files live in the data folder,
        # still served at /static/library/.
        from oneirodex.utils.static_files import serve_relocated_static
        app.config['IMAGE_SAVE_PATH'] = os.path.join(app.config['UPLOAD_FOLDER'], 'images')
        serve_relocated_static(app)

    from oneirodex.utils.i18n import init_babel
    init_babel(app)
    logger.info('Connecting to configured PostgreSQL database')

    parsed_url = urlparse(app.config['SQLALCHEMY_DATABASE_URI'])
    # Wait on the port the URL names: a standalone install runs its bundled
    # PostgreSQL on its own port (ADR 0011), and probing 5432 there stalled
    # boot for two minutes. No host (a socket URL) means nothing to probe.
    if parsed_url.hostname:
        check_postgres_port_open(parsed_url.hostname, parsed_url.port or 5432, 60, 2)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login.login'
    cache.init_app(app)

    from werkzeug.exceptions import HTTPException
    from oneirodex.utils.api_response import api_error
    from oneirodex.utils.error_envelope import http_error_code, wants_json_error

    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle file upload size limit exceeded errors.

        Two fixes over the previous version. It quoted a flat "10MB" that was
        never the real limit — and could not have been, because
        MAX_CONTENT_LENGTH was unset, so Flask never raised this at all. And it
        redirected unconditionally, which answered an XHR upload with an HTML
        page the caller could not read. API callers now get the envelope.
        """
        from flask import flash, redirect, request

        limit_mb = app.config.get('MAX_UPLOAD_MB', 0)
        message = f'The file you tried to upload is too large. Maximum size is {limit_mb}MB.'

        if wants_json_error(request):
            return api_error(message, code='payload_too_large')

        flash(message, 'error')
        return redirect(request.url)

    @app.errorhandler(HTTPException)
    def _http_exception_envelope(error):
        """Render any 4xx/5xx as the JSON envelope for API / XHR callers.

        Flask answers every HTTPException with an HTML page. For an ``/api/``
        caller that is an unreadable body with the wrong content type, and the
        SPA's shared error surface (``PageStatus``) has nothing to branch on.
        HTML routes keep Flask's default page. The status code is preserved
        exactly — only the body shape changes.
        """
        from flask import request

        if not wants_json_error(request):
            return error.get_response()

        return api_error(
            error.description or error.name or 'Request failed',
            code=http_error_code(error.code),
            status=error.code or 500,
        )

    @app.errorhandler(Exception)
    def _uncaught_exception_envelope(error):
        """Last resort: an uncaught error in an ``/api/`` route must not reach
        the browser as an HTML 500 with no envelope — the one crash path
        ``utils/api_response.py`` did not already cover.

        The client message is fixed text. ``str(error)`` routinely carries
        filesystem paths, SQL fragments, or upstream secrets, and this is the
        same "no secrets in ``detail``" rule the rest of the codebase follows.
        The real exception is logged server-side with a traceback.
        """
        from flask import request

        # A registered HTTPException handler already wins the dispatch, but keep
        # the guard so a future Flask internals change can't route an abort()
        # through the generic 500 message.
        if isinstance(error, HTTPException):
            return _http_exception_envelope(error)

        app.logger.exception(
            'Unhandled exception during %s %s', request.method, request.path
        )

        if not wants_json_error(request):
            raise error

        return api_error(
            'Something went wrong on our end. The error has been logged.',
            code='internal',
            status=500,
        )

    @app.context_processor
    def inject_current_theme():
        """Injects the current user's theme and icon pack into all templates."""
        current_theme = 'default'
        current_icon_pack = 'outline'
        icon_pack_css = None
        icon_pack_previews_css = None
        if current_user.is_authenticated and hasattr(current_user, 'preferences') and current_user.preferences:
            current_theme = current_user.preferences.theme or 'default'
            current_icon_pack = getattr(current_user.preferences, 'icon_pack', None) or 'outline'
        try:
            icon_pack_css = icon_pack_css_url(current_icon_pack)
            icon_pack_previews_css = icon_pack_previews_css_url()
        except Exception:
            icon_pack_css = None
            icon_pack_previews_css = None
        return dict(
            current_theme=current_theme,
            current_era=era_for_theme(current_theme),
            current_icon_pack=current_icon_pack,
            icon_pack_css=icon_pack_css,
            icon_pack_previews_css=icon_pack_previews_css,
        )

    @app.template_filter('theme_picker_groups')
    def theme_picker_groups_filter(choices):
        return theme_picker_groups(choices)

    # Theme-asset Jinja helpers (verify_file global; dist_asset / avatar_url /
    # theme_asset filters). App-level, extracted from routes.py in wave A2.1e.
    from oneirodex.routes_theme import register_theme_helpers
    register_theme_helpers(app)

    @app.context_processor
    def inject_feature_flags():
        return {
            'enable_vr_browse': bool(app.config.get('ENABLE_VR_BROWSE')),
            # Default on: the Activity surface predates its toggle, so an
            # unset flag must not silently hide a feature people already use.
            'enable_activity_feed': bool(
                app.config.get('ENABLE_ACTIVITY_FEED', True)
            ),
            # UIR-1: two-bar chrome. Default flipped **on** (W27-A3).
            #
            # The old comment said "off until the pages adopt it, so this ships
            # dark rather than half-applied". The pages did adopt it — all
            # eleven carry the branch — and the shell stopped being optional
            # when TopNav.jsx was deleted and SideRail/TopBar became the only
            # chrome App.jsx renders. So an unset flag produced exactly the
            # half-applied state it was meant to prevent, just the other way
            # round: the new shell naming the page in bar one, with every page
            # still rendering its own title card underneath.
            #
            # Operators can still set ENABLE_NEW_CHROME=false to get the old
            # page headers back, but there is no longer an old shell to pair
            # them with, so that is a stopgap rather than a supported look.
            'enable_new_chrome': bool(app.config.get('ENABLE_NEW_CHROME', True)),
            # AGPL §13 source offer — every template gets it, so member SPA and
            # admin can both surface it without threading it through each view.
            'source_url': app.config.get('ONEIRODEX_SOURCE_URL', ''),
            'app_version': app_version,
            'product_name': PRODUCT_NAME,
        }

    @app.before_request
    def guard_private_library_files():
        """The Flask twin of asgi.py's static guard (dev server, test client):
        members' private files under /static/library/ are never static, and
        BIOS needs a signed-in member."""
        from flask import abort, request
        from flask_login import current_user
        from pathlib import Path as _Path
        from oneirodex.utils.static_files import static_access

        if not request.path.startswith('/static/'):
            return None
        access = static_access(_Path(app.static_folder or ''), request.path)
        if access == 'private' or (access == 'member' and not current_user.is_authenticated):
            abort(404)
        return None

    @app.before_request
    def check_setup_status():
        """Check if setup is required and redirect accordingly."""
        from flask import request, redirect
        from oneirodex.utils.setup import should_redirect_to_setup, get_setup_redirect_url
        
        # Skip setup checks for certain endpoints
        exempt_endpoints = {
            'setup.setup', 'setup.setup_submit', 'setup.setup_smtp', 'setup.setup_igdb',
            # Steps 2-4 need the admin from step 1 signed in; an admin who lost
            # that session must be able to sign in again mid-wizard.
            'login.login',
            'static', 'favicon', 'site.favicon',
            'info.pulse', 'info.awake',
        }
        
        # Skip setup checks for API endpoints (they should handle their own authentication)
        # and for unauthenticated health probes used by Docker / Unraid.
        if request.endpoint and (
            request.endpoint in exempt_endpoints or
            request.endpoint.startswith('apis.') or
            request.path.startswith('/api/') or
            request.path in ('/pulse', '/awake')
        ):
            return
        
        # Check if we need to redirect to setup
        if should_redirect_to_setup():
            setup_url = get_setup_redirect_url()
            if request.endpoint and request.path != setup_url:
                return redirect(setup_url)

    # Import models
    from . import models
    from oneirodex.context import register_context_processors
    from oneirodex.routes_site import site_bp
    from oneirodex.routes_member import member_bp
    from oneirodex.routes_library import library_bp
    from oneirodex.routes_setup import setup_bp
    from oneirodex.routes_settings import settings_bp
    from oneirodex.routes_login import login_bp
    from oneirodex.routes_discover import discover_bp
    from oneirodex.routes_downloads_ext import download_bp
    from oneirodex.routes_games_ext import games_bp
    from oneirodex.routes_smtp import smtp_bp
    from oneirodex.routes_info import info_bp
    from oneirodex.routes_admin_ext import admin2_bp
    from oneirodex.routes_apis import apis_bp
    from oneirodex.routes_arr import arr_bp

    # App-level template context processors (moved off the retired 'main'
    # blueprint in wave A2.1f).
    register_context_processors(app)

    # Register all blueprints
    app.register_blueprint(site_bp)
    app.register_blueprint(member_bp)
    app.register_blueprint(admin2_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(login_bp)
    app.register_blueprint(discover_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(smtp_bp)
    app.register_blueprint(info_bp)
    app.register_blueprint(apis_bp)
    app.register_blueprint(arr_bp)

    # Companion desktop uses Bearer tokens without a browser CSRF cookie.
    from oneirodex.routes_apis import client as client_api

    csrf.exempt(client_api.client_heartbeat)
    csrf.exempt(client_api.client_lifecycle_get)
    csrf.exempt(client_api.client_lifecycle_post)
    csrf.exempt(client_api.client_commands_get)
    csrf.exempt(client_api.client_commands_ack)
    csrf.exempt(client_api.client_commands_nack)

    # Background schedulers are no longer started here — that made app
    # construction spawn threads for every script that just wanted a configured
    # app, with no shutdown path. They now start from the ASGI lifespan handler
    # in asgi.py via oneirodex.background.start_background_workers(app).

    return app
