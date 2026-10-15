"""FastAPI invited/allow-listed member registration."""
from __future__ import annotations

import re
from contextlib import nullcontext
from datetime import datetime, timezone
from html import escape
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from starlette.responses import JSONResponse

from .request_auth import request_auth_context

_REGISTRATION_ACK = 'If the details can be used to create an account, check your email for next steps.'


def _registration_ack():
    return {'requested': True, 'message': _REGISTRATION_ACK, 'next_url': '/login'}


class AuthRegistrationData:
    def register(self, payload, invite_token, request, config):
        from sqlalchemy import func, select, update

        from itsdangerous import URLSafeTimedSerializer
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import InviteToken, User, Whitelist
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.smtp import send_email_quiet
        from oneirodex.runtime_native.password_reset_confirm import _trusted_public_origin

        if invite_token:
            invite = db.session.execute(
                select(InviteToken).filter_by(token=invite_token, used=False)
            ).scalar_one_or_none()
            expiry = invite.expires_at if invite else None
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if invite is None or expiry is None or expiry < datetime.now(timezone.utc):
                return None, ('bad_request', 'The invite is invalid or has expired.', 400, None)
        else:
            invite = None

        email = payload['email'].lower()
        if db.session.execute(
            select(User).where(func.lower(User.email) == email)
        ).scalar_one_or_none():
            return _registration_ack(), None
        if invite is None and db.session.execute(
            select(Whitelist).where(func.lower(Whitelist.email) == email)
        ).scalar_one_or_none() is None:
            return _registration_ack(), None
        if db.session.execute(
            select(User).where(func.lower(User.name) == payload['username'].lower())
        ).scalars().first() is not None:
            return _registration_ack(), None

        now = datetime.now(timezone.utc)
        user_uuid = str(uuid4())
        verification_token = URLSafeTimedSerializer(config['SECRET_KEY']).dumps(
            email, salt='email-confirm',
        )
        user = User(
            user_id=user_uuid,
            name=payload['username'],
            email=email,
            role='user',
            is_email_verified=False,
            email_verification_token=verification_token,
            token_creation_time=now,
            created=now,
        )
        user.set_password(payload['password'])
        db.session.add(user)
        try:
            if invite is not None:
                db.session.flush()
                claimed = db.session.execute(
                    update(InviteToken)
                    .where(InviteToken.id == invite.id, InviteToken.used.is_(False))
                    .values(used=True, used_by=user_uuid, used_at=datetime.now(timezone.utc))
                ).rowcount
                if claimed != 1:
                    db.session.rollback()
                    return None, (
                        'conflict', 'The invite is invalid or has expired.', 409, None,
                    )
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            log_system_event(
                'Registration failed because a unique account value was claimed concurrently.',
                event_type='registration', event_level='warning', audit_user='system',
            )
            return _registration_ack(), None

        log_system_event(
            f'New user registered: {user.name}',
            event_type='audit', event_level='information', audit_user='system',
        )
        origin = _trusted_public_origin(request, config)
        confirm_url = f'{origin}/confirm/{verification_token}'
        send_email_quiet(
            user.email, 'Please confirm your email', _registration_confirmation_email(confirm_url),
            preflight=True, audit_user='system',
        )
        return _registration_ack(), None


def create_auth_registration_router(
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
    data = data_access or AuthRegistrationData()

    @router.post('/api/auth/register')
    async def api_register(request: Request):
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
            invite_token = request.query_params.get('token')
            if response is None and auth.user is not None:
                if invite_token:
                    for key in ('_user_id', '_fresh', '_id', 'next', '_remember_seconds'):
                        auth.session_data.pop(key, None)
                    auth.session_data['_remember'] = 'clear'
                else:
                    response = _error('Sign out before creating an account.', 'conflict', 409)
            if response is None:
                body, validation_error = await _validated_body(request)
                if validation_error:
                    response = validation_error
                else:
                    errors = _registration_errors(body)
                    if errors:
                        response = _error(
                            'Invalid registration details.', 'unprocessable', 422, detail=errors,
                        )
                    else:
                        try:
                            result, failure = data.register(
                                body, invite_token, request, flask_app.config,
                            )
                        except Exception:  # noqa: BLE001 — keep account and mail errors private
                            result, failure = None, (
                                'internal', 'Could not create the account.', 500, None,
                            )
                        if failure:
                            code, message, status, detail = failure
                            response = _error(message, code, status, detail=detail)
                        else:
                            response = _ok(result, status=202)
            if auth is not None and auth.remember_action:
                from oneirodex.runtime_native.auth_login import _write_remember_cookie

                _write_remember_cookie(response, auth.session_data, flask_app.config)
            if auth is not None and auth.should_set_session_cookie:
                from oneirodex.runtime_native.oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_auth_registration_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_auth_registration_router(flask_app, **kwargs))
    return app


async def _validated_body(request):
    from oneirodex.schemas.registration import RegistrationBody

    try:
        body = RegistrationBody.model_validate_json(await request.body())
        return body.model_dump(), None
    except ValidationError as exc:
        from oneirodex.utils.validation import format_validation_errors

        return None, _error(
            'Invalid registration details.', 'unprocessable', 422,
            detail=format_validation_errors(exc),
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        return None, _error('Invalid JSON body.', 'bad_request', 400)


def _registration_errors(body):
    errors = {}
    username = body['username']
    if username.lower() == 'system':
        errors['username'] = ["'system' is a reserved username and cannot be used."]
    elif not re.match(r'^[\w.]+$', username):
        errors['username'] = ['Username can only contain letters, numbers, dots and underscores']
    elif len(username) < 3 or len(username) > 64:
        errors['username'] = ['Username must be between 3 and 64 characters long']
    email = body['email']
    try:
        from email_validator import EmailNotValidError, validate_email

        validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        errors['email'] = ['Invalid email address.']
    password = body['password']
    if not password.strip():
        errors['password'] = ['This field is required.']
    elif len(password) < 8:
        errors['password'] = ['Field must be at least 8 characters long.']
    return errors


def _session_data(request, config):
    from oneirodex.runtime_native.password_reset_confirm import _session_data as load_session

    return load_session(request, config)


def _ok(payload, *, status=200):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload), status_code=status)


def _error(message, code, status, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, detail=detail)
    return JSONResponse(payload, status_code=resolved)


def _registration_confirmation_email(confirm_url):
    safe_url = escape(confirm_url, quote=True)
    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Confirm your Oneirodex email</title>
<style>body{{background:#f3f4f6;color:#333;font-family:'Courier New',Courier,monospace;padding:20px}}.container{{background:#fff;border:1px solid #ddd;padding:20px;border-radius:10px;max-width:600px;margin:20px auto;box-shadow:0 2px 4px rgba(0,0,0,.1)}}h1{{color:#007bff}}a{{background:#007bff;color:#fff;padding:10px 20px;text-decoration:none;border-radius:5px;font-weight:bold}}p{{margin-bottom:20px}}</style></head>
<body><div class="container"><h2>Ready, Player One!</h2>
<p>You're just one click away from joining the elite ranks at Oneirodex. Grab your controller and get ready to dive into an epic gaming adventure. But first, let's complete your character creation!</p>
<p>Click the power-up below to confirm your email and activate your account. Quick, before the server resets!</p>
<a href="{safe_url}">Confirm Your Email</a>
<p>If you didn't try to create an account with us, just ignore this message and no action is needed. This email will despawn automatically.</p></div></body></html>'''
