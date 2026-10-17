"""Native FastAPI handlers for the authenticated trailer read APIs.

Authentication is resolved through the shared Flask-compatible request auth
boundary. The default data adapter runs its existing SQLAlchemy queries inside
the caller-provided native session scope, without a Flask app context.
"""
from __future__ import annotations

import logging
import random
import re
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .request_auth import RequestAuthContext, request_auth_context
from .response_compat import add_vary_header, flask_redirect_response


@dataclass(frozen=True)
class TrailerAuthCallbacks:
    """Persistence hooks required by ``request_auth_context``."""

    find_user: Callable[[int], Any | None]
    find_token: Callable[[str], Any | None]
    commit_token_touch: Callable[[Any], None]
    load_user_id: Callable[[str], Any | None] | None = None
    login_manager: Any | None = None


class FlaskContextTrailerData:
    """Existing SQLAlchemy trailer reads, scoped to the native request session.

    The legacy class name is retained for adapter/test compatibility; this
    adapter no longer pushes a Flask application context.
    """

    def __init__(self, flask_app):
        self.flask_app = flask_app

    def filters(self, user) -> dict:
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Genre, Library, Theme

        libraries = db.session.execute(
            select(Library).order_by(Library.display_order, Library.name)
        ).scalars().all()
        genres = db.session.execute(select(Genre).order_by(Genre.name)).scalars().all()
        themes = db.session.execute(select(Theme).order_by(Theme.name)).scalars().all()
        date_range = db.session.execute(
            select(func.min(Game.first_release_date), func.max(Game.first_release_date)).filter(
                Game.video_urls.isnot(None),
                Game.video_urls != '',
                Game.first_release_date.isnot(None),
            )
        ).first()

        return {
            'libraries': [{'uuid': str(lib.uuid), 'name': lib.name} for lib in libraries],
            'genres': [{'id': genre.id, 'name': genre.name} for genre in genres],
            'themes': [{'id': theme.id, 'name': theme.name} for theme in themes],
            'date_range': {
                'min_year': date_range[0].year if date_range and date_range[0] else None,
                'max_year': date_range[1].year if date_range and date_range[1] else None,
            },
        }

    def random_game_ids(self, user, params) -> list[int]:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Genre, Theme
        from oneirodex.utils.library_acl import apply_game_access_filters

        query = select(Game.id).filter(
            Game.video_urls.isnot(None), Game.video_urls != ''
        )
        query = apply_game_access_filters(query, user)

        library_uuid = params.get('library_uuid')
        if library_uuid:
            query = query.filter(Game.library_uuid == library_uuid)
        for param_name, relationship in (('genres', Game.genres), ('themes', Game.themes)):
            values = parse_integer_list(params.get(param_name))
            if values:
                model = Genre if param_name == 'genres' else Theme
                query = query.join(relationship).filter(model.id.in_(values))

        date_from = parse_year(params.get('date_from'), 1, 1)
        if date_from is not None:
            query = query.filter(Game.first_release_date >= date_from)
        date_to = parse_year(params.get('date_to'), 12, 31)
        if date_to is not None:
            query = query.filter(Game.first_release_date <= date_to)

        return db.session.execute(query.distinct()).scalars().all()

    def game(self, game_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.get(Game, game_id)


def create_trailers_router(
    flask_app,
    *,
    auth: TrailerAuthCallbacks,
    data_access=None,
    choose: Callable[[list], Any] = random.choice,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    """Build the two native GET endpoints; callers mount this router in FastAPI."""
    router = APIRouter()
    data = data_access if data_access is not None else FlaskContextTrailerData(flask_app)
    logger = logging.getLogger('oneirodex.runtime_native.trailers')

    def decorate_response(response, request: Request):
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    def resolve_auth(request: Request) -> RequestAuthContext:
        return request_auth_context(
            request,
            flask_app.config,
            find_user=auth.find_user,
            find_token=auth.find_token,
            commit_token_touch=auth.commit_token_touch,
            load_user_id=auth.load_user_id,
            login_manager=auth.login_manager,
        )

    @router.api_route('/api/trailers/filters', methods=['GET', 'HEAD'])
    def get_filter_options(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            context = resolve_auth(request)
            if context.user is None:
                return decorate_response(
                    _login_redirect(flask_app, request, auth.login_manager, context), request
                )
            try:
                return decorate_response(_api_ok(data.filters(context.user)), request)
            except Exception:
                logger.warning('Error fetching trailer filters', exc_info=True)
                return decorate_response(
                    _api_error('Failed to fetch filter options', 'internal', 500), request
                )

    @router.api_route('/api/trailers/random', methods=['GET', 'HEAD'])
    def get_random_trailer(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            context = resolve_auth(request)
            if context.user is None:
                return decorate_response(
                    _login_redirect(flask_app, request, auth.login_manager, context), request
                )
            try:
                # Validate comma-separated IDs at the HTTP boundary, matching the
                # legacy handler's ValueError-to-safe-internal-envelope behavior.
                parse_integer_list(request.query_params.get('genres'))
                parse_integer_list(request.query_params.get('themes'))
                ids = data.random_game_ids(context.user, request.query_params)
                if not ids:
                    return decorate_response(_api_ok(_empty_payload(
                        'no_trailers', 'No games with trailers found matching your filters'
                    )), request)

                game = data.game(choose(ids))
                if not game or not game.video_urls:
                    return decorate_response(
                        _api_ok(_empty_payload('no_valid_urls', 'No valid video URLs found')),
                        request,
                    )

                video_urls = [url.strip() for url in _split_video_urls(game.video_urls) if url.strip()]
                if not video_urls:
                    return decorate_response(
                        _api_ok(_empty_payload('no_valid_urls', 'No valid video URLs found')),
                        request,
                    )

                selected_video = choose(video_urls)
                return decorate_response(_api_ok({
                    'has_videos': True,
                    'game_uuid': game.uuid,
                    'game_name': game.name,
                    'video_url': convert_to_embed_url(selected_video),
                }), request)
            except Exception:
                logger.warning('Error fetching random trailer', exc_info=True)
                return decorate_response(_api_error(
                    'Error fetching trailer', 'internal', 500, has_videos=False, empty=False
                ), request)

    return router


def mount_trailers_routes(app: FastAPI, flask_app, *, auth: TrailerAuthCallbacks, **kwargs):
    """Convenience integration contract for the default ASGI application."""
    app.include_router(create_trailers_router(flask_app, auth=auth, **kwargs))
    return app


def parse_integer_list(value: str | None) -> list[int]:
    """Match legacy comma-separated IDs; malformed nonempty IDs raise ValueError."""
    if not value:
        return []
    return [int(item) for item in value.split(',') if item.strip()]


def parse_year(value: str | None, month: int, day: int) -> datetime | None:
    """Parse an optional year; legacy behavior ignores invalid date values."""
    if not value:
        return None
    try:
        return datetime(int(value), month, day)
    except (ValueError, TypeError, OverflowError):
        return None


def _split_video_urls(value):
    if isinstance(value, str):
        return value.split(',')
    if isinstance(value, (list, tuple)):
        return value
    return []


def convert_to_embed_url(video_url: str) -> str:
    """Keep the existing trailer YouTube embed/autoplay transformation."""
    patterns = (
        r'youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
        r'youtube\.com/embed/([a-zA-Z0-9_-]+)',
        r'youtu\.be/([a-zA-Z0-9_-]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, video_url)
        if match:
            return f'https://www.youtube.com/embed/{match.group(1)}?autoplay=1&rel=0'
    if 'autoplay' not in video_url:
        separator = '&' if '?' in video_url else '?'
        return f'{video_url}{separator}autoplay=1&rel=0'
    return video_url


def _empty_payload(code: str, message: str) -> dict:
    return {
        'has_videos': False,
        'empty': True,
        'code': code,
        'message': message,
        'cta': {
            'id': 'add_library',
            'label': 'Add games to your library',
            'href': '/admin/library/add',
        },
    }


def _login_redirect(flask_app, request: Request, login_manager, auth_context):
    """Mirror Flask-Login's default unauthorized redirect and ``next`` value."""
    from oneirodex.utils.security_headers import security_header_values

    if login_manager:
        blueprint_views = getattr(login_manager, 'blueprint_login_views', {}) or {}
        login_view = blueprint_views.get('site') or getattr(login_manager, 'login_view', None)
    else:
        login_view = None
    if not login_view:
        return Response(status_code=401)

    login_view_url = str(login_view)
    parsed_login = urlsplit(login_view_url)
    if parsed_login.scheme or parsed_login.netloc or login_view_url.startswith('/'):
        target = login_view_url
    else:
        rule = next(iter(flask_app.url_map.iter_rules(login_view_url)), None)
        target = rule.rule if rule is not None else '/login'

    if not (parsed_login.scheme or parsed_login.netloc) and not target.startswith('/'):
        # A named view should resolve through the Flask URL map above; retain a
        # safe path fallback for malformed configuration.
        target = '/login'

    current_url = str(request.url)
    parsed_target = urlsplit(target)
    parsed_current = urlsplit(current_url)
    same_origin = (
        (not parsed_target.scheme or parsed_target.scheme == parsed_current.scheme)
        and (not parsed_target.netloc or parsed_target.netloc == parsed_current.netloc)
    )
    if same_origin:
        next_url = urlunsplit(('', '', parsed_current.path, parsed_current.query, ''))
    else:
        next_url = current_url
    query_params = parse_qs(parsed_target.query, keep_blank_values=True)
    query_params['next'] = [next_url]
    query = urlencode(query_params, doseq=True)
    force_host = flask_app.config.get('FORCE_HOST_FOR_REDIRECTS')
    if force_host:
        parsed_target = parsed_target._replace(netloc=force_host)
    location = urlunsplit(parsed_target._replace(query=query))
    response = flask_redirect_response(location)

    # Flask-Login's default unauthorized handler flashes before redirecting.
    login_message = getattr(login_manager, 'login_message', None)
    if login_message:
        localize = getattr(login_manager, 'localize_callback', None)
        if localize is not None:
            login_message = localize(login_message)
        flashes = list(auth_context.session_data.get('_flashes') or [])
        flashes.append((getattr(login_manager, 'login_message_category', 'message'), login_message))
        auth_context.session_data['_flashes'] = flashes

    if login_message or auth_context.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth_context)

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response


def _set_session_cookie(response, flask_app, auth_context):
    from oneirodex.runtime_native.session_compat import dump_session_cookie

    config = flask_app.config
    secret_key = config.get('SECRET_KEY')
    if not secret_key:
        return
    session_data = auth_context.session_data
    cookie_name = config.get('SESSION_COOKIE_NAME', 'session')
    cookie_path = config.get('SESSION_COOKIE_PATH') or config.get('APPLICATION_ROOT') or '/'
    lifetime = config.get('PERMANENT_SESSION_LIFETIME')
    expires = datetime.now(timezone.utc) + lifetime if session_data.get('_permanent') and lifetime else None
    samesite = config.get('SESSION_COOKIE_SAMESITE')
    response.set_cookie(
        cookie_name,
        dump_session_cookie(
            session_data,
            secret_key,
            fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
        ),
        expires=expires,
        path=cookie_path,
        domain=config.get('SESSION_COOKIE_DOMAIN'),
        secure=bool(config.get('SESSION_COOKIE_SECURE', False)),
        httponly=bool(config.get('SESSION_COOKIE_HTTPONLY', True)),
        samesite=str(samesite).lower() if samesite else None,
        partitioned=bool(config.get('SESSION_COOKIE_PARTITIONED', False)),
    )
    add_vary_header(response, 'Cookie')


def _api_ok(payload: dict) -> JSONResponse:
    body = dict(payload)
    body.update({'ok': True, 'error': None, 'error_code': None})
    body.setdefault('success', True)
    return JSONResponse(body)


def _api_error(message: str, code: str, status: int, **extra) -> JSONResponse:
    body = dict(extra)
    body.update({
        'ok': False,
        'error': message,
        'error_code': code,
        'message': message,
        'success': False,
    })
    return JSONResponse(body, status_code=status)
