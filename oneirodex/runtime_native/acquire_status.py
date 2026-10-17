"""Native FastAPI handler for the authenticated Acquire status read API."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .request_auth import RequestAuthContext, request_auth_context
from .response_compat import add_vary_header, flask_redirect_response


class AcquireStatusData:
    """Read the same readiness services used by the Flask route."""

    def __init__(self, config=None):
        self.config = config

    def status(self, user) -> dict:
        from oneirodex.utils.acquire_readiness import acquire_allowed, indexer_readiness
        from oneirodex.utils.debrid_connectors import debrid_enabled, debrid_status
        from oneirodex.utils.module_status import arr_module_on
        from oneirodex.utils.role_catalog import is_librarian

        config = self.config or {}
        readiness = indexer_readiness(config)
        return {
            'enabled': acquire_allowed(config),
            'arr_enabled': arr_module_on(config=config),
            'debrid_enabled': debrid_enabled(config=config),
            'debrid': debrid_status(config=config),
            'can_send': is_librarian(user),
            'clients': ['qbittorrent', 'transmission', 'sabnzbd', 'nzbget'],
            'native_ready': readiness['native_ready'],
            'hubs_ready': readiness['hubs_ready'],
            'indexers_ready': readiness['indexers_ready'],
            'indexer_warnings': readiness['indexer_warnings'],
            'native_count': readiness['native_count'],
            'native_ready_count': readiness['native_ready_count'],
            'message': (
                'Acquisition ready (native indexers / hubs / debrid configured by admin).'
                if acquire_allowed(config)
                else 'Enable ENABLE_ARR_MODULE and/or ENABLE_DEBRID to use Acquire.'
            ),
        }


def create_acquire_status_router(
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
    """Build the native GET route with Flask-compatible identity and JSON."""
    router = APIRouter()
    if data_access is None:
        data = AcquireStatusData()
        data.config = flask_app.config
    else:
        data = data_access

    @router.api_route('/api/acquire/status', methods=['GET', 'HEAD'])
    def acquire_status(request: Request):
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
                response = _login_redirect(flask_app, request, login_manager, context)
            else:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload(data.status(context.user)))

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_acquire_status_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_acquire_status_router(flask_app, **kwargs))
    return app


def _login_redirect(flask_app, request: Request, login_manager, auth_context: RequestAuthContext):
    """Mirror Flask-Login's default unauthorized handling for the ``apis`` BP."""
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
    parsed_current = urlsplit(str(request.url))
    same_origin = (
        (not parsed_login.scheme or parsed_login.scheme == parsed_current.scheme)
        and (not parsed_login.netloc or parsed_login.netloc == parsed_current.netloc)
    )
    next_url = (
        urlunsplit(('', '', parsed_current.path, parsed_current.query, ''))
        if same_origin else str(request.url)
    )
    query = parse_qs(parsed_login.query, keep_blank_values=True)
    query['next'] = [next_url]
    forced_host = flask_app.config.get('FORCE_HOST_FOR_REDIRECTS')
    if forced_host:
        parsed_login = parsed_login._replace(netloc=forced_host)
    response = flask_redirect_response(
        urlunsplit(parsed_login._replace(query=urlencode(query, doseq=True)))
    )

    message = getattr(login_manager, 'login_message', None)
    if message:
        localize = getattr(login_manager, 'localize_callback', None)
        if localize is not None:
            message = localize(message)
        flashes = list(auth_context.session_data.get('_flashes') or [])
        flashes.append((getattr(login_manager, 'login_message_category', 'message'), message))
        auth_context.session_data['_flashes'] = flashes
    if message or auth_context.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth_context)
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response


def _set_session_cookie(response, flask_app, auth_context):
    from oneirodex.runtime_native.session_compat import dump_session_cookie

    config = flask_app.config
    cookie_name = config.get('SESSION_COOKIE_NAME', 'session')
    if any(
        item.split(';', 1)[0].strip().startswith(f'{cookie_name}=')
        for item in response.headers.getlist('set-cookie')
    ):
        return
    secret_key = config.get('SECRET_KEY')
    if not secret_key:
        return
    session_data = auth_context.session_data
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
        path=config.get('SESSION_COOKIE_PATH') or config.get('APPLICATION_ROOT') or '/',
        domain=config.get('SESSION_COOKIE_DOMAIN'),
        secure=bool(config.get('SESSION_COOKIE_SECURE', False)),
        httponly=bool(config.get('SESSION_COOKIE_HTTPONLY', True)),
        samesite=str(samesite).lower() if samesite else None,
        partitioned=bool(config.get('SESSION_COOKIE_PARTITIONED', False)),
    )
    add_vary_header(response, 'Cookie')
