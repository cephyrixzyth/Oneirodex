"""FastAPI confirmation-link transition for the static member auth shell."""
from __future__ import annotations

import json
from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response


class AuthConfirmationData:
    def _resolve_user(self, token, secret_key):
        from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        serializer = URLSafeTimedSerializer(secret_key)
        try:
            email = serializer.loads(token, salt='email-confirm', max_age=900)
        except SignatureExpired:
            return None, 'expired'
        except BadSignature:
            return None, 'invalid'
        user = db.session.execute(
            select(User).where(func.lower(User.email) == email.lower())
        ).scalar_one_or_none()
        if user is None:
            return None, 'not_found'
        if user.is_email_verified:
            return user, 'already_confirmed'
        return user, 'confirmed'

    def inspect(self, token, secret_key):
        """Resolve confirmation state without changing it, for safe HEAD requests."""
        _user, outcome = self._resolve_user(token, secret_key)
        return outcome

    def confirm(self, token, secret_key, password):
        from oneirodex.runtime_native.db_session import native_db as db

        user, outcome = self._resolve_user(token, secret_key)
        if outcome != 'confirmed':
            return outcome
        # The mailbox owner, not the invite holder, must choose the credentials
        # that become usable when this account is activated.
        user.set_password(password)
        user.is_email_verified = True
        db.session.add(user)
        db.session.commit()
        return 'confirmed'


def create_auth_confirmation_router(*, data_access=None, database_scope=None, app_config=None):
    router = APIRouter()
    data = data_access or AuthConfirmationData()

    @router.api_route('/api/auth/confirm/{token}', methods=['GET', 'HEAD', 'POST'])
    async def confirm_email(token: str, request: Request):
        scope = database_scope() if database_scope else nullcontext()
        with scope:
            try:
                secret = app_config.get('SECRET_KEY') if app_config else None
                if not secret:
                    return _error('Confirmation is unavailable.', 'internal', 500)
                if request.method == 'POST':
                    from oneirodex.runtime_native.auth_registration import _session_data
                    from oneirodex.runtime_native.csrf_compat import csrf_error_response

                    csrf_error = csrf_error_response(
                        request, _session_data(request, app_config), app_config,
                    )
                    if csrf_error is not None:
                        return csrf_error
                    from oneirodex.runtime_native.bounded_request_body import (
                        BODY_TOO_LARGE, read_bounded_body,
                    )
                    raw_body = await read_bounded_body(request, 4096)
                    if raw_body is BODY_TOO_LARGE:
                        return _error('Request body is too large.', 'payload_too_large', 413)
                    try:
                        payload = json.loads(raw_body)
                    except (TypeError, ValueError, UnicodeDecodeError):
                        return _error('Invalid JSON body.', 'bad_request', 400)
                    password = payload.get('password') if isinstance(payload, dict) else None
                    confirm_password = (
                        payload.get('confirm_password') if isinstance(payload, dict) else None
                    )
                    try:
                        password_bytes = (
                            len(password.encode('utf-8')) if isinstance(password, str) else 0
                        )
                    except UnicodeEncodeError:
                        password_bytes = 0
                    if (
                        not isinstance(password, str)
                        or not password.strip()
                        or len(password) < 8
                        or password_bytes > 1024
                        or not password_bytes
                    ):
                        return _error('Password must be at least 8 characters.', 'unprocessable', 422)
                    if password != confirm_password:
                        return _error('Passwords do not match.', 'unprocessable', 422)
                    outcome = data.confirm(token, secret, password)
                else:
                    outcome = data.inspect(token, secret)
            except Exception:  # noqa: BLE001 — keep token/database internals private
                return _error('Confirmation is unavailable.', 'internal', 500)
            if outcome == 'expired':
                response = _error(
                    'The confirmation link is invalid or has expired. Request a new activation '
                    'from an admin or try registering again with a fresh invite.',
                    'bad_request', 400,
                )
            elif outcome == 'invalid':
                response = _error(
                    'This confirmation link is not valid. Check your email for the correct link, '
                    'or sign in if your account is already active.',
                    'bad_request', 400,
                )
            elif outcome == 'not_found':
                response = _error(
                    'The account for this confirmation link was not found.', 'not_found', 404,
                )
            else:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload({
                    'confirmed': (
                        (request.method == 'POST' and outcome == 'confirmed')
                        or outcome == 'already_confirmed'
                    ),
                    'already_confirmed': outcome == 'already_confirmed',
                }))
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(app_config or {}).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                headers = dict(response.headers)
                headers.setdefault('content-length', str(len(getattr(response, 'body', b''))))
                return Response(content=b'', status_code=response.status_code, headers=headers)
            return response

    return router


def mount_auth_confirmation_routes(app: FastAPI, **kwargs):
    app.include_router(create_auth_confirmation_router(**kwargs))
    return app


def _error(message, code, status):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)
