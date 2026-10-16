#/oneirodex/__init__.py
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask
from flask_wtf.csrf import CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session as FlaskSQLAlchemySession
from flask_login import LoginManager
from urllib.parse import urlparse
from oneirodex.utils.db import check_postgres_port_open
from oneirodex.utils.proxy import apply_proxy_fix
from oneirodex.utils.security_headers import apply_security_headers
from oneirodex.product import PRODUCT_NAME
from oneirodex.runtime_native.db_session import current_native_engine, native_session_scope_key
from flask_sqlalchemy.session import _app_ctx_id
from oneirodex.utils.cache import cache
from oneirodex.runtime_info import app_start_time, app_version
import logging

logger = logging.getLogger(__name__)

class OneirodexSession(FlaskSQLAlchemySession):
    """Use a context-local engine for FastAPI requests, Flask's engine otherwise."""

    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):
        native_engine = current_native_engine()
        if native_engine is not None:
            return native_engine
        return super().get_bind(mapper=mapper, clause=clause, bind=bind, **kwargs)


from oneirodex.models.orm import ModelBase

db = SQLAlchemy(model_class=ModelBase, session_options={
    'class_': OneirodexSession,
    'scopefunc': lambda: native_session_scope_key() or ('flask', _app_ctx_id()),
})
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_object=None):
    """Build the Flask app.

    ``config_object`` defaults to :class:`config.Config` (production), or
    :class:`config.TestConfig` when running under pytest. Pass an explicit
    class to override — scripts and the ASGI entrypoint rely on the default.
    """
    # Keep the import name stable after extracting the legacy app factory into
    # this module; Flask uses it for endpoint/static-root metadata.
    app = Flask('oneirodex')
    from oneirodex.runtime_native.app_config import build_runtime_config
    app.config.from_mapping(build_runtime_config(config_object, package_root=app.root_path))

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
    from oneirodex.utils.library_paths import relocated_library_dir
    if relocated_library_dir():
        # Standalone install (ADR 0011): runtime files live in the data folder,
        # still served at /static/library/.
        from oneirodex.utils.static_files import serve_relocated_static
        serve_relocated_static(app)

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
            # Steps 2-6 need the admin from step 1 signed in; an admin who lost
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
    from oneirodex.routes_apis import wanted as wanted_api

    # These handlers validate CSRF themselves for browser sessions so that a
    # scoped Bearer token can use the API without a browser token.
    csrf.exempt(wanted_api.updates_wanted_add)
    csrf.exempt(wanted_api.updates_wanted_fulfill)

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
