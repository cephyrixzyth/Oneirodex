"""FastAPI password-reset confirmation for the static member auth shell."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import os

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from .request_auth import request_auth_context


class PasswordResetConfirmData:
    def request_reset(self, email, ip, request, config):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.login_rate_limit import auth_endpoint_key, is_rate_limited, record_failure
        from oneirodex.utils.smtp import send_email_quiet
        from oneirodex.utils.tokens import get_serializer

        reset_key = auth_endpoint_key('pwd_reset', ip)
        if is_rate_limited(reset_key):
            return 'rate_limited'
        user = db.session.execute(
            select(User).filter_by(email=email.lower())
        ).scalar_one_or_none()
        record_failure(reset_key)
        if user:
            token = get_serializer().dumps(user.email, salt='password-reset-salt')
            user.password_reset_token = token
            user.token_creation_time = datetime.now(timezone.utc)
            log_system_event(
                f"Password reset requested for user: {user.email}",
                event_type='password_reset', event_level='information',
                audit_user='system',
            )
            db.session.commit()
            from oneirodex.product import PRODUCT_NAME
            from urllib.parse import quote

            reset_url = f'{_trusted_public_origin(request, config)}/reset_password/{quote(token, safe="")}'
            html = (
                '<p>You requested a password reset for your Oneirodex account.</p>'
                '<p>Use the link below to choose a new password:</p>'
                f'<p><a href="{reset_url}">Password Reset Link</a></p>'
                '<p>If you did not request this, you can ignore this message.</p>'
                '<p>Oneirodex</p>'
            )
            send_email_quiet(
                user.email, f'{PRODUCT_NAME} password reset request', html,
                preflight=True, audit_user='system',
            )
        return 'requested'

    def reset(self, token, password):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        user = db.session.execute(
            select(User).filter_by(password_reset_token=token)
        ).scalar_one_or_none()
        issued_at = user.token_creation_time if user else None
        if issued_at is not None and issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        if (user is None or issued_at is None
                or issued_at + timedelta(minutes=15) < datetime.now(timezone.utc)):
            return False
        user.set_password(password)
        user.password_reset_token = None
        db.session.commit()
        return True

    def valid_reset_token(self, token):
        """Match the classic reset page's pre-form token and expiry gate."""
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        user = db.session.execute(
            select(User).filter_by(password_reset_token=token)
        ).scalar_one_or_none()
        issued_at = user.token_creation_time if user else None
        if issued_at is not None and issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        return bool(
            user is not None and issued_at is not None
            and issued_at + timedelta(minutes=15) >= datetime.now(timezone.utc)
        )


def create_password_reset_confirm_router(
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
    data = data_access or PasswordResetConfirmData()

    @router.post('/api/auth/password-reset/request')
    async def request_reset(request: Request):
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
                    response = _error(
                        'Sign out before requesting a password reset.', 'conflict', 409,
                    )
            if response is None:
                body, validation_error = await _validated_reset_request(request)
                if validation_error:
                    response = validation_error
                else:
                    ip = _client_ip(request, flask_app.config)
                    try:
                        outcome = data.request_reset(
                            body['email'].lower(), ip, request, flask_app.config,
                        )
                    except Exception:  # noqa: BLE001 — keep account/mail internals private
                        outcome = 'internal'
                    if outcome == 'rate_limited':
                        response = _error(
                            'Too many password reset requests. Please wait and try again.',
                            'rate_limited', 429,
                        )
                    elif outcome != 'requested':
                        response = _error(
                            'Could not request a password reset.', 'internal', 500,
                        )
                    else:
                        auth.session_data.pop('_flashes', None)
                        response = _ok({
                            'requested': True,
                            'message': 'If that email is registered, password reset instructions were sent.',
                        })
                        response.headers['Cache-Control'] = 'no-store'
            if auth is not None and auth.should_set_session_cookie:
                from oneirodex.runtime_native.oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            _security_headers(response, flask_app.config)
            return response

    @router.post('/api/auth/password-reset/{token}')
    async def confirm_reset(token: str, request: Request):
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
                    response = _error('Sign out before resetting a password.', 'conflict', 409)
            if response is None:
                body, validation_error = await _validated_body(request)
                if validation_error:
                    response = validation_error
                else:
                    errors = _password_form_errors(body)
                    if errors:
                        response = _error(
                            'Invalid password details.', 'unprocessable', 422, detail=errors,
                        )
                    else:
                        try:
                            changed = data.reset(token, body['password'])
                        except Exception:  # noqa: BLE001 — keep account and storage internals private
                            changed = None
                        if changed is None:
                            response = _error('Could not reset the password.', 'internal', 500)
                        elif not changed:
                            response = _error(
                                'The password reset link is invalid or has expired.',
                                'bad_request', 400,
                            )
                        else:
                            response = _ok({'reset': True, 'next_url': '/login'})

            if auth is not None and auth.should_set_session_cookie:
                from oneirodex.runtime_native.oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            _security_headers(response, flask_app.config)
            return response

    return router


def mount_password_reset_confirm_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_password_reset_confirm_router(flask_app, **kwargs))
    return app


def _password_form_errors(body):
    password = body.get('password', '')
    confirmation = body.get('confirm_password', '')
    errors = {}
    if not password.strip():
        errors['password'] = ['This field is required.']
    elif len(password) < 8:
        errors['password'] = ['Field must be at least 8 characters long.']
    if not confirmation.strip():
        errors['confirm_password'] = ['This field is required.']
    elif confirmation != password:
        errors['confirm_password'] = ['Passwords must match']
    return errors


async def _validated_reset_request(request):
    from oneirodex.schemas.password_reset import PasswordResetRequestBody

    try:
        body = PasswordResetRequestBody.model_validate_json(await request.body())
    except ValidationError as exc:
        from oneirodex.utils.validation import format_validation_errors

        return None, _error(
            'Invalid email address.', 'unprocessable', 422,
            detail=format_validation_errors(exc),
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        return None, _error('Invalid JSON body.', 'bad_request', 400)
    email = body.email.strip()
    if not email:
        return None, _error(
            'Invalid email address.', 'unprocessable', 422,
            detail={'email': ['This field is required.']},
        )
    try:
        from email_validator import EmailNotValidError, validate_email

        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return None, _error(
            'Invalid email address.', 'unprocessable', 422,
            detail={'email': ['Invalid email address.']},
        )
    return {'email': email}, None


def _session_data(request, config):
    from oneirodex.runtime_native.request_auth import _lifetime_seconds
    from oneirodex.runtime_native.session_compat import load_session_cookie

    cookie_name = str(config.get('SESSION_COOKIE_NAME') or 'session')
    return load_session_cookie(
        request.cookies.get(cookie_name), config.get('SECRET_KEY'),
        max_age=_lifetime_seconds(config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
        fallback_secret_keys=config.get('SECRET_KEY_FALLBACKS') or (),
    )


def _client_ip(request, config):
    from oneirodex.utils.trusted_proxy import forwarded_client_ip

    return forwarded_client_ip(request, config)


def _trusted_public_origin(request, config):
    from oneirodex.utils.global_settings import global_settings_row
    from oneirodex.utils.trusted_host import host_is_trusted, parse_trusted_hosts

    try:
        settings = global_settings_row()
        configured = (getattr(settings, 'site_url', None) or '').strip().rstrip('/')
    except Exception:  # noqa: BLE001 — mail may fall back to a safe local origin
        configured = ''
    local_defaults = {
        '', 'http://127.0.0.1', 'http://127.0.0.1:5006',
        'http://localhost', 'http://localhost:5006',
    }
    if configured and configured not in local_defaults and not configured.startswith(
        ('http://127.0.0.1', 'http://localhost')
    ):
        return configured

    host = request.headers.get('host', '')
    allowed = parse_trusted_hosts(
        config.get('TRUSTED_LINK_HOSTS') or os.getenv('TRUSTED_LINK_HOSTS', '')
    )
    try:
        trusted_hops = max(0, int(config.get('TRUSTED_PROXIES') or 0))
    except (TypeError, ValueError):
        trusted_hops = 0
    from oneirodex.utils.trusted_proxy import trusted_proxy_peer

    if trusted_hops and trusted_proxy_peer(request, config):
        forwarded_host = request.headers.get('X-Forwarded-Host')
        if forwarded_host:
            from werkzeug.http import parse_list_header

            hosts = parse_list_header(forwarded_host)
            if len(hosts) >= trusted_hops:
                host = hosts[-trusted_hops] or host
    if host_is_trusted(host, allowed):
        scheme = request.url.scheme
        forwarded_proto = request.headers.get('X-Forwarded-Proto')
        if trusted_hops and forwarded_proto:
            from werkzeug.http import parse_list_header

            protocols = parse_list_header(forwarded_proto)
            if len(protocols) >= trusted_hops and protocols[-trusted_hops] in {'http', 'https'}:
                scheme = protocols[-trusted_hops]
        return f'{scheme}://{host}'
    return configured or 'http://127.0.0.1'


def _security_headers(response, config):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(config).items():
        response.headers.setdefault(key, value)


async def _validated_body(request):
    from oneirodex.schemas.password_reset import PasswordResetConfirmBody

    try:
        body = PasswordResetConfirmBody.model_validate_json(await request.body())
        return body.model_dump(), None
    except ValidationError as exc:
        from oneirodex.utils.validation import format_validation_errors

        errors = format_validation_errors(exc)
        return None, _error('Invalid password details.', 'unprocessable', 422, detail=errors)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None, _error('Invalid JSON body.', 'bad_request', 400)


def _ok(payload):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload))


def _error(message, code, status, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(
        message, code=code, status=status, detail=detail,
    )
    return JSONResponse(payload, status_code=response_status)
