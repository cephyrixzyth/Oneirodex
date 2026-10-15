"""Native FastAPI handler for the admin-only OIDC readiness read API."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .request_auth import RequestAuthContext, request_auth_context

_DEFAULT_LOGIN_MESSAGE = object()


class OidcStatusData:
    """Adapter for the local-only readiness report; this never calls the IdP."""

    def report(self) -> dict:
        from oneirodex.utils.oidc import oidc_readiness_report

        return oidc_readiness_report()


def create_oidc_status_router(
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
    """Create native GET/HEAD routes with Flask-Login and admin parity."""
    router = APIRouter()
    data = data_access if data_access is not None else OidcStatusData()

    @router.api_route('/api/oidc/status', methods=['GET', 'HEAD'])
    def oidc_status(request: Request):
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
            user = auth.user
            if user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            else:
                from oneirodex.utils.role_catalog import normalize_role

                if (
                    normalize_role(getattr(user, 'role', None) or '') == 'admin'
                    and auth.token is not None
                    and not auth.has_scope('admin')
                ):
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif (
                    not bool(getattr(user, 'is_authenticated', True))
                    or normalize_role(getattr(user, 'role', None) or '') != 'admin'
                ):
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger',
                        include_next=False,
                    )
                else:
                    response = JSONResponse(data.report())

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_oidc_status_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_oidc_status_router(flask_app, **kwargs))
    return app


def _from_flask_response(flask_response, status: int) -> Response:
    return Response(
        content=flask_response.get_data(),
        status_code=status,
        headers={'Content-Type': flask_response.headers.get('Content-Type', 'application/json')},
    )


def _login_redirect(
    flask_app,
    request: Request,
    login_manager,
    auth_context: RequestAuthContext,
    *,
    message: str | None | object = _DEFAULT_LOGIN_MESSAGE,
    category: str | None = None,
    include_next: bool = True,
):
    """Match Flask-Login unauthorized and admin_required redirect variants."""
    from oneirodex.utils.security_headers import security_header_values

    if message is _DEFAULT_LOGIN_MESSAGE:
        message = getattr(login_manager, 'login_message', None)
    if category is None:
        category = getattr(login_manager, 'login_message_category', 'message')

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
    if include_next:
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
        parsed_login = parsed_login._replace(query=urlencode(query, doseq=True))
    forced_host = flask_app.config.get('FORCE_HOST_FOR_REDIRECTS')
    if forced_host:
        parsed_login = parsed_login._replace(netloc=forced_host)
    response = RedirectResponse(urlunsplit(parsed_login), status_code=302)

    if message:
        localize = getattr(login_manager, 'localize_callback', None)
        if localize is not None:
            message = localize(message)
        flashes = list(auth_context.session_data.get('_flashes') or [])
        flashes.append((category, message))
        auth_context.session_data['_flashes'] = flashes
    if message or auth_context.should_set_session_cookie:
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
    response.headers.add_vary_header('Cookie')
