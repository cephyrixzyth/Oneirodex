"""Reversible FastAPI admin shell with Flask-owned configuration and DB.

The shell pages and runtime bootstrap use FastAPI request/auth handling and
Flask-compatible session codecs. The host still constructs Flask for legacy
routes and the configured SQLAlchemy extension; this is not the final
zero-Flask runtime.
"""
from __future__ import annotations

from html import escape
import inspect
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Request
from starlette.responses import Response

from . import ADMIN_STATIC_ROUTES, ADMIN_BOOTSTRAP_ROUTE


def legacy_chrome_fields(user) -> dict:
    """Build the same chrome projection from an explicitly resolved user."""
    return _native_legacy_chrome_fields(user)


def _native_legacy_chrome_fields(user) -> dict:
    """Build the same chrome payload without Flask request globals."""
    import os

    from oneirodex.utils.asset_urls import asset_version
    from oneirodex.utils.library_paths import library_dir
    from oneirodex.utils.preset_themes import canonical_theme_slug, era_for_theme

    prefs = getattr(user, 'preferences', None)
    theme = canonical_theme_slug(getattr(prefs, 'theme', None))
    icon_pack = getattr(prefs, 'icon_pack', None) or 'outline'
    library = Path(library_dir())
    theme_root = library / 'themes'

    def static(filename: str, version_path: Path | None = None) -> str:
        value = '/static/' + quote(filename.lstrip('/'), safe='/')
        if version_path is not None:
            value += '?' + urlencode({'v': asset_version(version_path)})
        return value

    def theme_asset(path: str) -> str:
        candidate = theme_root / theme / path
        selected_theme = theme
        if not candidate.is_file():
            candidate = theme_root / 'default' / path
            selected_theme = 'default'
        return static(
            f'library/themes/{selected_theme}/{path}', candidate
        )

    paths = [
        'od-tokens.css', 'od-primitives.css', 'od-bootstrap-bridge.css',
        'od-density.css', 'od-shell.css', 'od-appbar.css', 'base.css',
        'modal-components.css', 'form-components.css', 'table-components.css',
        'admin-components.css', 'components.css', 'od-loading-motifs.css',
        'admin/admin-pages.css',
    ]
    styles = [static('vendor/bootstrap/5.3.2/css/bootstrap.min.css')]
    styles.extend(theme_asset(f'css/{path}') for path in paths)
    previews = library / 'icon-themes' / 'previews.css'
    if previews.is_file():
        styles.append(static('library/icon-themes/previews.css'))
    pack_css = library / 'icon-themes' / icon_pack / 'pack.css'
    if not pack_css.is_file():
        icon_pack = 'outline'
        pack_css = library / 'icon-themes' / icon_pack / 'pack.css'
    if pack_css.is_file() or icon_pack == 'outline':
        styles.append(static(f'library/icon-themes/{icon_pack}/pack.css'))
    styles.extend([
        '/api/theme/fonts.css',
        theme_asset('css/admin/admin-shell.css'),
        theme_asset('css/od-era.css'),
    ])
    scripts = [static(path) for path in (
        'vendor/jquery/3.7.1/jquery.min.js',
        'vendor/bootstrap/5.3.2/js/bootstrap.bundle.min.js',
        'vendor/notify/0.4.2/notify.min.js', 'js/od_toast.js',
        'js/od_pwa_install.js', 'js/od_dom_actions.js',
    )]
    scripts.extend(theme_asset(f'js/{path}') for path in (
        'csrf-utils.js', 'od_loading_motifs.js', 'od_sortable_table.js',
        'od_modal_stack.js', 'preferences_modal.js',
    ))

    avatarpath = getattr(user, 'avatarpath', None) or 'newstyle/avatars/default.svg'
    avatar_url = static(avatarpath)
    if avatarpath.startswith('newstyle/avatars/'):
        name = os.path.basename(avatarpath)
        if avatarpath.endswith('default.jpg'):
            name = 'default.svg'
        for candidate_theme in (theme, 'default'):
            themed_avatar = theme_root / candidate_theme / 'avatars' / name
            if themed_avatar.is_file():
                avatar_url = static(
                    f'library/themes/{candidate_theme}/avatars/{name}'
                )
                break
    return {
        'avatar_url': avatar_url,
        'preferences_url': '/settings_panel',
        'theme': {
            'name': theme,
            'era': era_for_theme(theme),
            'icon_pack': icon_pack,
            'stylesheets': styles,
            'scripts': scripts,
        },
    }


def create_admin_pilot(
    flask_app,
    *,
    shell_path: Path,
    chrome_fields: Callable[..., dict] | None = None,
    database_scope: Callable[[Any], Any] | None = None,
    shell_entity_exists: Callable[[Request], bool] | None = None,
) -> FastAPI:
    """Create a local pilot; callers own routing, lifecycle and static assets.

    ``shell_path`` is a trusted deploy-time artifact, never request input. The
    artifact must contain one ``</head>`` and the admin React mount point. CSS,
    scripts and theme initialization must be external, under the existing CSP.
    ``chrome_fields`` resolves theme/style URLs, avatar and preferences URL for
    the authenticated native user. Frontends must refuse to mount
    when these configuration fields are absent.
    """
    from oneirodex.utils.role_catalog import normalize_role

    shell = Path(shell_path).read_text(encoding='utf-8')
    if shell.count('</head>') != 1 or 'id="admin-app-root"' not in shell:
        raise ValueError('Pilot requires a built admin static shell')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    # Exact static and numeric route matching must reject trailing-slash aliases.
    app.router.redirect_slashes = False

    def open_database_scope():
        if database_scope is not None:
            return database_scope(flask_app)
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.runtime_native.db_session import native_session_scope

        return native_session_scope(flask_app, db)

    def admin_shell(request: Request):
        from .acquire_status import _login_redirect, _set_session_cookie
        from .request_auth import request_auth_context
        from .response_compat import flask_redirect_response
        from oneirodex.utils.security_headers import security_header_values

        with open_database_scope():
            find_user, find_token, commit_token_touch = _native_auth_backend(flask_app)
            manager = getattr(flask_app, 'login_manager', None)
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                login_manager=manager,
            )
            flashes = []
            if auth.user is None:
                response = _login_redirect(flask_app, request, manager, auth)
            elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                flashes = list(auth.session_data.get('_flashes') or [])
                flashes.append(('danger', 'You must be an admin to access this page.'))
                auth.session_data['_flashes'] = flashes
                response = flask_redirect_response('/login', status_code=302)
            elif not auth.has_scope('admin'):
                response = _native_json_error(
                    'This token does not have the admin scope', 'forbidden', 403,
                )
            else:
                flashes = list(auth.session_data.pop('_flashes', []) or [])
                response_shell = _shell_with_admin_flashes(shell, flashes)
                exists = (
                    shell_entity_exists(request)
                    if shell_entity_exists is not None
                    else _admin_shell_entity_exists(request)
                )
                response = Response(
                    response_shell,
                    status_code=200 if exists else 404,
                    media_type='text/html',
                )
            if auth.user is not None and (auth.should_set_session_cookie or flashes):
                _set_session_cookie(response, flask_app, auth)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    for route in ADMIN_STATIC_ROUTES:
        app.add_api_route(route, admin_shell, methods=['GET', 'HEAD'], response_class=Response)

    async def admin_manage_downloads_post(request: Request):
        from .csrf_compat import csrf_error_response, csrf_html_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie

        form = await request.form(max_files=0, max_fields=8, max_part_size=16 * 1024)
        cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
        session = load_session_cookie(
            request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
            max_age=_lifetime_seconds(
                flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
            ),
            fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
        )
        csrf_response = csrf_error_response(
            request, session, flask_app.config,
            token=str(form.get('csrf_token') or ''),
        )
        if csrf_response is not None:
            csrf_response = csrf_html_error_response(csrf_response)
            from oneirodex.utils.security_headers import security_header_values

            csrf_response.headers.setdefault('Cache-Control', 'no-store')
            for key, value in security_header_values(flask_app.config).items():
                csrf_response.headers.setdefault(key, value)
            return csrf_response
        return admin_shell(request)

    app.add_api_route(
        '/admin/manage-downloads', admin_manage_downloads_post,
        methods=['POST'], response_class=Response,
    )
    app.add_api_route('/admin/newsletter/{newsletter_id:int}', admin_shell, methods=['GET', 'HEAD'], response_class=Response)
    app.add_api_route('/game_edit/{game_uuid}', admin_shell, methods=['GET', 'HEAD'], response_class=Response)
    app.add_api_route('/edit_game_images/{game_uuid}', admin_shell, methods=['GET', 'HEAD'], response_class=Response)
    app.add_api_route('/admin/library/edit/{library_uuid}', admin_shell, methods=['GET', 'HEAD'], response_class=Response)

    @app.api_route(ADMIN_BOOTSTRAP_ROUTE, methods=['GET', 'HEAD'], response_class=Response)
    def admin_bootstrap(request: Request):
        return native_admin_bootstrap(request)

    def native_admin_bootstrap(request: Request):
        import logging

        from werkzeug.exceptions import HTTPException
        from oneirodex.utils.error_envelope import http_error_code
        from oneirodex.utils.logging_setup import new_request_id

        request_id = new_request_id()
        try:
            response = _native_admin_bootstrap_impl(request)
        except HTTPException as error:
            status = error.code or 500
            response = _native_json_error(
                error.description or error.name or 'Request failed',
                http_error_code(status),
                status,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                'Unhandled native admin bootstrap error request_id=%s path=%s',
                request_id,
                request.url.path,
            )
            response = _native_json_error(
                'Something went wrong on our end. The error has been logged.',
                'internal',
                500,
            )
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Request-ID'] = request_id
        from oneirodex.utils.security_headers import security_header_values

        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    def _native_admin_bootstrap_impl(request: Request):
        from datetime import datetime, timedelta, timezone

        from starlette.responses import JSONResponse
        from oneirodex.runtime_native.request_auth import request_auth_context
        from oneirodex.runtime_native.session_compat import (
            dump_session_cookie,
            generate_csrf_token,
        )
        from oneirodex.utils.security_headers import security_header_values
        config = flask_app.config
        secret_key = config.get('SECRET_KEY')
        if not secret_key:
            return _native_json_error('Admin bootstrap is unavailable.', 'unavailable', 503)

        with open_database_scope():
            find_user, find_token, commit_token_touch = _native_auth_backend(flask_app)

            manager = getattr(flask_app, 'login_manager', None)
            auth = request_auth_context(
                request,
                config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                now=datetime.now(timezone.utc),
                login_manager=manager,
            )
            session_data = auth.session_data
            original_session = auth.original_session
            cookie_name = auth.session_cookie_name

            user = auth.user
            if user is None or not getattr(user, 'is_active', False):
                response = _native_json_error('Sign in required', 'unauthorized', 401)
            elif (
                normalize_role(getattr(user, 'role', None)) != 'admin'
                or not auth.has_scope('admin')
            ):
                response = _native_json_error('Admin access required', 'forbidden', 403)
            else:
                csrf_token = generate_csrf_token(
                    session_data,
                    config.get('WTF_CSRF_SECRET_KEY') or secret_key,
                    field_name=config.get('WTF_CSRF_FIELD_NAME', 'csrf_token'),
                )
                if chrome_fields is None:
                    fields = _native_legacy_chrome_fields(user)
                else:
                    try:
                        accepts_user = 'user' in inspect.signature(chrome_fields).parameters
                    except (TypeError, ValueError):
                        accepts_user = False
                    fields = chrome_fields(user=user) if accepts_user else chrome_fields()
                response = JSONResponse({
                    'ok': True,
                    'error': None,
                    'error_code': None,
                    'success': True,
                    'csrf_token': csrf_token,
                    'user': {
                        'id': user.id,
                        'name': user.name,
                        'role': 'admin',
                        'avatar_url': fields.get('avatar_url'),
                    },
                    'theme': fields.get('theme'),
                    'preferences_url': fields.get('preferences_url'),
                    'runtime': 'fastapi-session-compat-pilot',
                })

        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(config).items():
            response.headers.setdefault(key, value)

        remember_action = session_data.pop('_remember', None)
        if remember_action == 'clear':
            response.delete_cookie(
                config.get('REMEMBER_COOKIE_NAME', 'remember_token'),
                path=config.get('REMEMBER_COOKIE_PATH') or '/',
                domain=config.get('REMEMBER_COOKIE_DOMAIN'),
            )
        elif remember_action == 'set' and session_data.get('_user_id'):
            from oneirodex.runtime_native.auth_resolver import encode_remember_cookie

            remember_duration = config.get('REMEMBER_COOKIE_DURATION')
            seconds = session_data.pop('_remember_seconds', None)
            expires = datetime.now(timezone.utc) + (
                timedelta(seconds=seconds) if seconds is not None
                else remember_duration or timedelta(days=365)
            )
            response.set_cookie(
                config.get('REMEMBER_COOKIE_NAME', 'remember_token'),
                encode_remember_cookie(str(session_data['_user_id']), secret_key),
                expires=expires,
                path=config.get('REMEMBER_COOKIE_PATH') or '/',
                domain=config.get('REMEMBER_COOKIE_DOMAIN'),
                secure=bool(config.get('REMEMBER_COOKIE_SECURE', False)),
                httponly=bool(config.get('REMEMBER_COOKIE_HTTPONLY', True)),
                samesite=config.get('REMEMBER_COOKIE_SAMESITE'),
            )
        session_modified = session_data != original_session
        if session_modified or (session_data.get('_permanent') and config.get('SESSION_REFRESH_EACH_REQUEST', True)):
            cookie_value = dump_session_cookie(
                session_data,
                secret_key,
                fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
            )
            lifetime = config['PERMANENT_SESSION_LIFETIME']
            expires = datetime.now(timezone.utc) + lifetime if session_data.get('_permanent') else None
            response.set_cookie(
                cookie_name,
                cookie_value,
                expires=expires,
                path=config.get('SESSION_COOKIE_PATH') or config.get('APPLICATION_ROOT') or '/',
                domain=config.get('SESSION_COOKIE_DOMAIN'),
                secure=bool(config.get('SESSION_COOKIE_SECURE', False)),
                httponly=bool(config.get('SESSION_COOKIE_HTTPONLY', True)),
                samesite=str(config.get('SESSION_COOKIE_SAMESITE')).lower()
                if config.get('SESSION_COOKIE_SAMESITE') else None,
                partitioned=bool(config.get('SESSION_COOKIE_PARTITIONED', False)),
            )
        return response

    return app


def _admin_shell_entity_exists(request: Request) -> bool:
    """Preserve legacy 404 status for dynamic editor shells with missing rows."""
    import re

    path = request.url.path
    newsletter = re.fullmatch(r'/admin/newsletter/([0-9]+)', path)
    library = re.fullmatch(r'/admin/library/edit/([^/]+)', path)
    game = re.fullmatch(r'/(?:game_edit|edit_game_images)/([^/]+)', path)
    if not any((newsletter, library, game)):
        return True

    from sqlalchemy import select
    from oneirodex.models import Game, Library, Newsletter
    from oneirodex.runtime_native.db_session import native_db as db

    if newsletter:
        return db.session.get(Newsletter, int(newsletter.group(1))) is not None
    if library:
        return db.session.execute(
            select(Library).filter_by(uuid=library.group(1))
        ).scalar_one_or_none() is not None
    return db.session.execute(
        select(Game).filter_by(uuid=game.group(1))
    ).scalar_one_or_none() is not None


def _shell_with_admin_flashes(shell: str, flashes) -> str:
    """Render queued legacy flash notices into the React-owned admin shell."""
    if not flashes:
        return shell
    notices = []
    for item in flashes:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        category, message = item
        category = str(category or 'info').lower()
        is_error = category in {'danger', 'error', 'warning'}
        class_name = 'od-page-status--error' if is_error else 'od-page-status--empty'
        role = 'alert' if is_error else 'status'
        notices.append(
            f'<div class="od-page-status {class_name}" role="{role}">'
            f'<p class="od-page-status__message">{escape(str(message))}</p></div>'
        )
    root_marker = '<div id="admin-app-root"'
    root_offset = shell.find(root_marker)
    if root_offset < 0 or not notices:
        return shell
    container = '<div class="od-admin-session-flashes">' + ''.join(notices) + '</div>\n'
    return shell[:root_offset] + container + shell[root_offset:]


def _native_json_error(message: str, code: str, status: int) -> Response:
    from starlette.responses import JSONResponse

    return JSONResponse({
        'ok': False,
        'error': message,
        'error_code': code,
        'message': message,
        'success': False,
    }, status_code=status)


def _native_auth_backend(flask_app):
    """Bind auth persistence callbacks to the app's scoped SQLAlchemy session."""
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import ApiToken, User
    from sqlalchemy import select

    def find_user(user_id):
        return db.session.get(User, user_id)

    def find_token(prefix):
        return db.session.execute(
            select(ApiToken).filter_by(token_prefix=prefix, revoked_at=None)
        ).scalars().first()

    def commit_token_touch(_token):
        db.session.commit()

    # Flask-SQLAlchemy removes this scoped session when the surrounding app
    # context exits, matching its normal teardown lifecycle.
    return find_user, find_token, commit_token_touch
