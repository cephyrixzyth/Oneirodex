"""FastAPI JSON sign-in with Flask-Login-compatible session cookies."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .request_auth import request_auth_context


class AuthLoginData:
    def authenticate(self, username, password, ip):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.accounts import is_placeholder_email
        from oneirodex.utils.password_checks import burn_password_check
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.login_rate_limit import (
            clear_failures, is_rate_limited, login_rate_key, record_failure,
        )

        key = login_rate_key(ip, username)
        ip_key = login_rate_key(ip, None)
        if is_rate_limited(key) or is_rate_limited(ip_key):
            log_system_event(
                f'Login rate-limited for IP {ip}', event_type='login',
                event_level='warning', audit_user='system',
            )
            return None, ('rate_limited', 'Too many login attempts. Please wait a few minutes and try again.')

        user = db.session.execute(select(User).filter_by(name=username)).scalar_one_or_none()
        if user is None:
            burn_password_check(password)
        if user is None or not user.check_password(password):
            if user is None:
                log_system_event(
                    f'Failed login for unknown user from {ip}',
                    event_type='login', event_level='warning',
                    audit_user='system',
                )
            else:
                log_system_event(
                    f'User {username} attempted to log in with invalid credentials.',
                    event_type='login', event_level='warning',
                    audit_user='system',
                )
            record_failure(key)
            record_failure(ip_key)
            return None, (
                'unauthorized',
                'Invalid username or password. USERNAMES ARE CASE SENSITIVE!',
            )
        if not user.is_email_verified and not is_placeholder_email(user.email):
            log_system_event(
                f'User {username} attempted to log in with an unverified account.',
                event_type='login', event_level='warning',
                audit_user='system',
            )
            record_failure(key)
            return None, ('forbidden', 'Your account is not activated, check your email.')
        if not user.state:
            log_system_event(
                f'User {username} attempted to log in with a banned account.',
                event_type='login', event_level='warning',
                audit_user='system',
            )
            record_failure(key)
            return None, ('forbidden', 'Your account has been banned.')

        clear_failures(key)
        clear_failures(ip_key)
        log_system_event(
            f'User {username} logged in successfully.',
            event_type='login', event_level='information',
            audit_user='system',
        )
        user.lastlogin = datetime.now(timezone.utc)
        db.session.commit()
        return user, None


def create_auth_login_router(
    flask_app: FastAPI,
    *,
    find_user,
    find_token,
    commit_token_touch,
    load_user_id=None,
    login_manager=None,
    data_access=None,
    database_scope=None,
):
    router = APIRouter()
    data = data_access or AuthLoginData()

    @router.post('/api/auth/login')
    async def api_login(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from oneirodex.runtime_native.csrf_compat import csrf_error_response

            session_data = _session_data(request, flask_app.config)
            response = csrf_error_response(request, session_data, flask_app.config)
            auth = None
            if response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user,
                    find_token=find_token, commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                    allow_bearer=False,
                )
                if auth.user is not None:
                    response = _ok({'next_url': _safe_next(request.query_params.get('next'))})
            if response is None:
                body, validation_error = await _validated_body(request)
                if validation_error:
                    response = validation_error
                else:
                    try:
                        user, failure = data.authenticate(
                            body['username'], body['password'], _client_ip(request, flask_app.config),
                        )
                    except Exception:  # noqa: BLE001 — never expose credential/database details
                        user, failure = None, (
                            'internal', 'Could not sign in. Please try again.',
                        )
                    if failure:
                        response = _error(failure[1], failure[0])
                    else:
                        from oneirodex.runtime_native.auth_resolver import session_identifier
                        from oneirodex.utils.trusted_proxy import trusted_forwarded_for

                        auth.session_data['_user_id'] = str(user.get_id())
                        auth.session_data['_fresh'] = True
                        auth.session_data['_id'] = session_identifier(
                            request.client.host if request.client else None,
                            request.headers.get('user-agent'),
                            trusted_forwarded_for(request, flask_app.config),
                        )
                        auth.session_data['_remember'] = 'set'
                        response = _ok({'next_url': _safe_next(request.query_params.get('next'))})

            if auth is not None and auth.remember_action:
                _write_remember_cookie(response, auth.session_data, flask_app.config)
            if auth is not None and auth.should_set_session_cookie:
                from oneirodex.runtime_native.oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            _security_headers(response, flask_app.config)
            return response

    return router


def mount_auth_login_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_auth_login_router(flask_app, **kwargs))
    return app


async def _validated_body(request):
    from oneirodex.schemas.auth import LoginBody

    try:
        body = LoginBody.model_validate_json(await request.body())
        return body.model_dump(), None
    except ValidationError as exc:
        from oneirodex.utils.validation import format_validation_errors

        return None, _error(
            'Invalid login details.', 'unprocessable', 422,
            detail=format_validation_errors(exc),
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        return None, _error('Invalid JSON body.', 'bad_request', 400)


def _client_ip(request, config):
    from oneirodex.utils.trusted_proxy import forwarded_client_ip

    return forwarded_client_ip(request, config)


def _safe_next(candidate):
    if not isinstance(candidate, str) or not candidate.strip().startswith('/'):
        return '/discover'
    value = candidate.strip()
    if value[1:2] in ('/', '\\'):
        return '/discover'
    from urllib.parse import urlparse

    parsed = urlparse(value)
    return '/discover' if parsed.scheme or parsed.netloc else value


def _session_data(request, config):
    from oneirodex.runtime_native.request_auth import _lifetime_seconds
    from oneirodex.runtime_native.session_compat import load_session_cookie

    name = str(config.get('SESSION_COOKIE_NAME') or 'session')
    return load_session_cookie(
        request.cookies.get(name), config.get('SECRET_KEY'),
        max_age=_lifetime_seconds(config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
        fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
    )


def _write_remember_cookie(response, session_data, config):
    action = session_data.pop('_remember', None)
    name = config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    path = config.get('REMEMBER_COOKIE_PATH') or '/'
    domain = config.get('REMEMBER_COOKIE_DOMAIN')
    if action == 'clear':
        response.delete_cookie(name, path=path, domain=domain)
    elif action == 'set' and session_data.get('_user_id'):
        from oneirodex.runtime_native.auth_resolver import encode_remember_cookie

        duration = config.get('REMEMBER_COOKIE_DURATION') or timedelta(days=365)
        seconds = session_data.pop('_remember_seconds', None)
        expires = datetime.now(timezone.utc) + (
            timedelta(seconds=seconds) if seconds is not None else duration
        )
        response.set_cookie(
            name, encode_remember_cookie(str(session_data['_user_id']), config['SECRET_KEY']),
            expires=expires, path=path, domain=domain,
            secure=bool(config.get('REMEMBER_COOKIE_SECURE', False)),
            httponly=bool(config.get('REMEMBER_COOKIE_HTTPONLY', True)),
            samesite=config.get('REMEMBER_COOKIE_SAMESITE'),
        )


def _security_headers(response, config):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(config).items():
        response.headers.setdefault(key, value)


def _ok(payload):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload))


def _error(message, code, status=None, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, detail=detail)
    return JSONResponse(payload, status_code=resolved)
