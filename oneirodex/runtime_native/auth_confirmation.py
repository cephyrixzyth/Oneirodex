"""FastAPI confirmation-link transition for the static member auth shell."""
from __future__ import annotations

from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response


class AuthConfirmationData:
    def confirm(self, token, secret_key):
        from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        serializer = URLSafeTimedSerializer(secret_key)
        try:
            email = serializer.loads(token, salt='email-confirm', max_age=900)
        except SignatureExpired:
            return 'expired'
        except BadSignature:
            return 'invalid'
        user = db.session.execute(
            select(User).where(func.lower(User.email) == email.lower())
        ).scalar_one_or_none()
        if user is None:
            return 'not_found'
        if user.is_email_verified:
            return 'already_confirmed'
        user.is_email_verified = True
        db.session.add(user)
        db.session.commit()
        return 'confirmed'


def create_auth_confirmation_router(*, data_access=None, database_scope=None, app_config=None):
    router = APIRouter()
    data = data_access or AuthConfirmationData()

    @router.api_route('/api/auth/confirm/{token}', methods=['GET', 'HEAD'])
    def confirm_email(token: str, request: Request):
        scope = database_scope() if database_scope else nullcontext()
        with scope:
            try:
                secret = app_config.get('SECRET_KEY') if app_config else None
                if not secret:
                    return _error('Confirmation is unavailable.', 'internal', 500)
                outcome = data.confirm(token, secret)
            except Exception:  # noqa: BLE001 — keep token/database internals private
                return _error('Confirmation is unavailable.', 'internal', 500)
            if outcome == 'expired':
                response = _error('The confirmation link has expired.', 'bad_request', 400)
            elif outcome == 'invalid':
                response = _error('The confirmation link is invalid.', 'bad_request', 400)
            elif outcome == 'not_found':
                response = _error(
                    'The account for this confirmation link was not found.', 'not_found', 404,
                )
            else:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload({
                    'confirmed': True, 'already_confirmed': outcome == 'already_confirmed',
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
