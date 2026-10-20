"""Native FastAPI handler for the member ``/browse_games`` read endpoint."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import Response
from werkzeug.datastructures import MultiDict

from .request_auth import RequestAuthContext, request_auth_context
from .response_compat import add_vary_header, flask_redirect_response


class BrowseDataAccess:
    """Adapter around existing browse services, called inside app context."""

    def query(self, args, user):
        from oneirodex.utils.browse_query import run_browse_query

        return run_browse_query(args, user)

    def payload(self, result):
        from oneirodex.utils.browse_payload import build_browse_payload

        return build_browse_payload(result)


def create_browse_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    """Build native GET/HEAD routes using the shared auth and browse services."""
    router = APIRouter()
    data = data_access or BrowseDataAccess()

    @router.api_route('/browse_games', methods=['GET', 'HEAD'])
    def browse_games(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            context = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if context.user is None:
                return _secure_response(
                    _login_redirect(flask_app, request, login_manager, context),
                    flask_app,
                    request,
                )

            # Werkzeug's MultiDict preserves the legacy Flask ``request.args``
            # API, including typed ``get(..., type=int)`` and first-value rules.
            args = MultiDict(request.query_params.multi_items())
            from oneirodex.utils.filter_tree import FilterTreeError

            try:
                result = data.query(args, context.user)
            except FilterTreeError as exc:
                body = {
                    'ok': False,
                    'error': str(exc),
                    'error_code': 'bad_request',
                    'detail': {'path': exc.path},
                    'message': str(exc),
                    'success': False,
                }
                return _secure_response(
                    _flask_json_response(flask_app, body, status=400), flask_app, request
                )

            payload = data.payload(result)
            return _secure_response(
                _flask_json_response(flask_app, payload), flask_app, request
            )

    return router


def mount_browse_routes(app: FastAPI, flask_app, **kwargs):
    """Convenience integration contract for the default ASGI application."""
    app.include_router(create_browse_router(flask_app, **kwargs))
    return app


def _flask_json_response(flask_app, payload: dict, *, status: int = 200) -> Response:
    """Serialize with Flask's configured JSON provider (UUID/date/Decimal parity)."""
    response = flask_app.json.response(payload)
    return Response(
        content=response.get_data(),
        status_code=status,
        headers={'Content-Type': response.headers.get('Content-Type', 'application/json')},
    )


def _secure_response(response: Response, flask_app, request: Request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
    return response


def _login_redirect(flask_app, request: Request, login_manager, auth_context: RequestAuthContext):
    """Mirror Flask-Login's default member-blueprint unauthorized behavior."""
    from oneirodex.utils.security_headers import security_header_values

    blueprint_views = getattr(login_manager, 'blueprint_login_views', {}) or {}
    login_view = blueprint_views.get('member') or getattr(login_manager, 'login_view', None)
    if not login_view:
        return Response(status_code=401)

    login_url = str(login_view)
    parsed_login = urlsplit(login_url)
    if not (parsed_login.scheme or parsed_login.netloc or login_url.startswith('/')):
        rule = next(iter(flask_app.url_map.iter_rules(login_url)), None)
        login_url = rule.rule if rule is not None else '/login'
        parsed_login = urlsplit(login_url)

    from .url_compat import request_url_iri

    current_url = request_url_iri(request)
    parsed_current = urlsplit(current_url)
    same_origin = (
        (not parsed_login.scheme or parsed_login.scheme == parsed_current.scheme)
        and (not parsed_login.netloc or parsed_login.netloc == parsed_current.netloc)
    )
    next_url = (
        urlunsplit(('', '', parsed_current.path, parsed_current.query, ''))
        if same_origin else current_url
    )
    query = parse_qs(parsed_login.query, keep_blank_values=True)
    query['next'] = [next_url]
    forced_host = flask_app.config.get('FORCE_HOST_FOR_REDIRECTS')
    if forced_host:
        parsed_login = parsed_login._replace(netloc=forced_host)
    location = urlunsplit(parsed_login._replace(query=urlencode(query, doseq=True)))
    response = flask_redirect_response(location)

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
    lifetime = config.get('PERMANENT_SESSION_LIFETIME')
    expires = datetime.now(timezone.utc) + lifetime if session_data.get('_permanent') and lifetime else None
    samesite = config.get('SESSION_COOKIE_SAMESITE')
    response.set_cookie(
        config.get('SESSION_COOKIE_NAME', 'session'),
        dump_session_cookie(
            session_data,
            secret_key,
            fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
        ),
        expires=expires,
        path=config.get('SESSION_COOKIE_PATH') or config.get('APPLICATION_ROOT') or '/',
        domain=config.get('SESSION_COOKIE_DOMAIN'),
        secure=bool(config.get('SESSION_COOKIE_SECURE', False)),
        httponly=bool(config.get('SESSION_COOKIE_HTTPONLY', True)),
        samesite=str(samesite).lower() if samesite else None,
        partitioned=bool(config.get('SESSION_COOKIE_PARTITIONED', False)),
    )
    add_vary_header(response, 'Cookie')
