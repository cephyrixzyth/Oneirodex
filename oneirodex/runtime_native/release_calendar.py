"""Native FastAPI handler for the authenticated release calendar API."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import RedirectResponse, Response

from .request_auth import RequestAuthContext, request_auth_context


def create_release_calendar_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    fetch_calendar: Callable[..., list[dict]] | None = None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    """Build the native GET/HEAD calendar endpoint with an injectable fetch."""
    router = APIRouter()
    if fetch_calendar is None:
        from oneirodex.utils.release_calendar import fetch_release_calendar

        fetch_calendar = fetch_release_calendar

    @router.api_route('/api/calendar', methods=['GET', 'HEAD'])
    def release_calendar(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                return _secure_response(
                    _login_redirect(flask_app, request, login_manager, auth),
                    flask_app,
                    request,
                )

            try:
                days_ahead = int(request.query_params.get('days_ahead') or 60)
                days_behind = int(request.query_params.get('days_behind') or 14)
                limit = int(request.query_params.get('limit') or 40)
            except (TypeError, ValueError):
                from oneirodex.utils.api_contract import api_error_payload

                payload, status = api_error_payload(
                    'Invalid query parameters', code='bad_request',
                )
                return _secure_response(
                    _json_response(payload, status=status), flask_app, request
                )

            days_ahead = max(1, min(days_ahead, 180))
            days_behind = max(0, min(days_behind, 90))
            limit = max(1, min(limit, 100))
            generated_at = datetime.now(timezone.utc).isoformat()
            status: dict = {}
            try:
                items = fetch_calendar(
                    days_ahead=days_ahead,
                    days_behind=days_behind,
                    limit=limit,
                    status=status,
                )
            except Exception:
                items = []
                reason = 'unavailable'
            else:
                reason = status.get('reason')

            payload = {
                'days_ahead': days_ahead,
                'days_behind': days_behind,
                'limit': limit,
                'count': len(items),
                'releases': items,
                'generated_at': generated_at,
                'source': 'igdb',
                'empty_reason': reason if not items else None,
            }
            return _secure_response(_json_response(payload), flask_app, request)

    return router


def mount_release_calendar_routes(app: FastAPI, flask_app, **kwargs):
    """Convenience integration contract for the default ASGI application."""
    app.include_router(create_release_calendar_router(flask_app, **kwargs))
    return app


def _json_response(payload: dict, *, status: int = 200) -> Response:
    """Serialize this JSON-only payload without Flask's request globals."""
    from starlette.responses import JSONResponse

    return JSONResponse(payload, status_code=status)


def _secure_response(response: Response, flask_app, request: Request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    # Flask-Login reads the signed session for every protected route, and the
    # Flask session interface adds this even when it does not rewrite a cookie.
    response.headers.add_vary_header('Cookie')
    if request.method == 'HEAD':
        response.body = b''
    return response


def _login_redirect(flask_app, request: Request, login_manager, auth: RequestAuthContext):
    """Match Flask-Login's default ``apis`` blueprint redirect and flash."""
    from oneirodex.utils.security_headers import security_header_values

    blueprint_views = getattr(login_manager, 'blueprint_login_views', {}) or {}
    login_view = blueprint_views.get('apis') or getattr(login_manager, 'login_view', None)
    if not login_view:
        return Response(status_code=401)

    login_url = str(login_view)
    parsed_login = urlsplit(login_url)
    if not (parsed_login.scheme or parsed_login.netloc or login_url.startswith('/')):
        rule = next(iter(flask_app.url_map.iter_rules(login_url)), None)
        login_url = rule.rule if rule is not None else '/login'
        parsed_login = urlsplit(login_url)

    current_url = str(request.url)
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
    response = RedirectResponse(location, status_code=302)

    message = getattr(login_manager, 'login_message', None)
    if message:
        localize = getattr(login_manager, 'localize_callback', None)
        if localize is not None:
            message = localize(message)
        flashes = list(auth.session_data.get('_flashes') or [])
        flashes.append((getattr(login_manager, 'login_message_category', 'message'), message))
        auth.session_data['_flashes'] = flashes
    if message or auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response


def _set_session_cookie(response, flask_app, auth: RequestAuthContext):
    from oneirodex.runtime_native.session_compat import dump_session_cookie

    config = flask_app.config
    secret_key = config.get('SECRET_KEY')
    if not secret_key:
        return
    session_data = auth.session_data
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
    response.headers.add_vary_header('Cookie')
