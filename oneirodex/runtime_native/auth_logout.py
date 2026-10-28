"""FastAPI logout redirect with Flask-Login session-cookie compatibility."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, FastAPI, Request

from .response_compat import flask_http_exception_response, flask_redirect_response


def create_auth_logout_router(flask_app: FastAPI):
    router = APIRouter()

    @router.api_route('/logout', methods=['GET', 'HEAD', 'POST'])
    def logout(request: Request):
        from oneirodex.utils.security_headers import security_header_values

        if request.method in ('GET', 'HEAD'):
            from oneirodex.utils.setup import get_setup_redirect_url, should_redirect_to_setup

            # Setup state is database-backed. NativeRuntimeContext.app_context
            # binds the request's native SQLAlchemy session without importing
            # the retired Flask runtime; Flask's context remains available to
            # the compatibility test harness.
            with flask_app.app_context():
                setup_redirect = should_redirect_to_setup()
                setup_target = get_setup_redirect_url() if setup_redirect else None

            if setup_redirect:
                response = flask_redirect_response(setup_target)
                for key, value in security_header_values(flask_app.config).items():
                    response.headers.setdefault(key, value)
                if request.method == 'HEAD':
                    response.body = b''
                return response
            response = flask_http_exception_response(flask_app, request, 405)
            response.headers['Allow'] = 'POST'
            return response

        from oneirodex.runtime_native.request_auth import _lifetime_seconds
        from oneirodex.runtime_native.session_compat import load_session_cookie
        from oneirodex.runtime_native.oidc_status import _set_session_cookie

        config = flask_app.config
        cookie_name = str(config.get('SESSION_COOKIE_NAME') or 'session')
        session_data = load_session_cookie(
            request.cookies.get(cookie_name), config.get('SECRET_KEY'),
            max_age=_lifetime_seconds(config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
            fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
        )
        from oneirodex.runtime_native.csrf_compat import csrf_error_response

        csrf_response = csrf_error_response(request, session_data, config)
        if csrf_response is not None:
            return csrf_response

        session_data.pop(str(config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'), None)
        original = dict(session_data)
        for key in ('_user_id', '_fresh', '_id'):
            session_data.pop(key, None)
        remember_name = config.get('REMEMBER_COOKIE_NAME', 'remember_token')
        remember_cookie_present = remember_name in request.cookies
        clear_remember = remember_cookie_present or session_data.get('_remember') == 'clear'
        if remember_cookie_present:
            session_data.pop('_remember_seconds', None)
        session_data.pop('_remember', None)
        changed = session_data != original

        response = flask_redirect_response('/login')
        if clear_remember:
            response.delete_cookie(
                remember_name,
                path=config.get('REMEMBER_COOKIE_PATH') or '/',
                domain=config.get('REMEMBER_COOKIE_DOMAIN'),
                secure=False,
                httponly=False,
                samesite=None,
                partitioned=False,
            )
        if changed:
            if session_data:
                _set_session_cookie(
                    response, flask_app,
                    SimpleNamespace(session_data=session_data, should_set_session_cookie=True),
                )
            else:
                response.delete_cookie(
                    cookie_name,
                    path=config.get('SESSION_COOKIE_PATH') or config.get('APPLICATION_ROOT') or '/',
                    domain=config.get('SESSION_COOKIE_DOMAIN'),
                    secure=bool(config.get('SESSION_COOKIE_SECURE', False)),
                    httponly=bool(config.get('SESSION_COOKIE_HTTPONLY', True)),
                    samesite=config.get('SESSION_COOKIE_SAMESITE'),
                    partitioned=bool(config.get('SESSION_COOKIE_PARTITIONED', False)),
                )
        for key, value in security_header_values(config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_auth_logout_routes(app: FastAPI, flask_app, **_kwargs):
    app.include_router(create_auth_logout_router(flask_app))
    return app
