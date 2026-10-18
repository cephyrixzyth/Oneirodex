"""Native FastAPI password change with Flask-Login session compatibility."""
from __future__ import annotations

import logging
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import RedirectResponse, Response

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .form_compat import first_form_value, first_form_values
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context

_logger = logging.getLogger(__name__)


class AccountPasswordData:
    """Adapter for user lookup and SQLAlchemy transaction operations."""

    def get_user(self, user_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        return db.session.get(User, user_id)

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_account_password_router(
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
    router = APIRouter()
    data = data_access or AccountPasswordData()

    @router.post('/api/account/password')
    async def account_password(request: Request):
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
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                from oneirodex.schemas.account import ChangePasswordBody
                from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
                from oneirodex.utils.validation import format_validation_errors

                body, validation_error = await _validated_body(request, ChangePasswordBody)
                if validation_error:
                    response = validation_error
                else:
                    user = data.get_user(auth.user.id)
                    if user is None:
                        response = _api_error('Account not found.', code='not_found')
                    elif not user.check_password(body.current_password):
                        response = _api_error(
                            'Current password is incorrect.', code='unprocessable'
                        )
                    else:
                        minimum = 8
                        if len(body.new_password) < minimum:
                            response = _api_error(
                                f'New password must be at least {minimum} characters.',
                                code='unprocessable',
                            )
                        elif body.new_password != body.confirm_password:
                            response = _api_error(
                                "Those two passwords don't match.", code='unprocessable'
                            )
                        elif body.new_password == body.current_password:
                            response = _api_error(
                                "Pick a password you're not already using.",
                                code='unprocessable',
                            )
                        else:
                            try:
                                user.set_password(body.new_password)
                                data.commit()
                            except Exception as exc:
                                data.rollback()
                                _logger.warning(
                                    'password change failed for user %s: %s',
                                    auth.user.id,
                                    exc,
                                )
                                response = _api_error(
                                    'Could not change your password.', code='internal'
                                )
                            else:
                                _refresh_password_session(auth.session_data, user, request, flask_app.config)
                                from starlette.responses import JSONResponse

                                response = JSONResponse(api_ok_payload({'changed': True}))
                                _write_remember_cookie(response, flask_app, auth.session_data)

            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/settings_password')
    async def legacy_password_change(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            form, body_error = await _legacy_password_form(request)
            response = body_error
            if response is None:
                response = csrf_error_response(
                    request, auth.session_data, flask_app.config,
                    token=first_form_value(form, 'csrf_token'),
                )
            remember_cookie = False
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                from .account_avatar_upload import _flash

                user = data.get_user(auth.user.id)
                if user is None:
                    _flash(auth.session_data, 'error', 'Account not found.')
                elif not first_form_value(form, 'current_password'):
                    _flash(auth.session_data, 'error', 'Current Password: This field is required.')
                elif not user.check_password(form['current_password']):
                    _flash(auth.session_data, 'error', 'Current password is incorrect.')
                elif len(first_form_value(form, 'password') or '') < 8:
                    _flash(
                        auth.session_data,
                        'error',
                        'New Password: Field must be at least 8 characters long.',
                    )
                elif (
                    first_form_value(form, 'password')
                    != first_form_value(form, 'confirm_password')
                ):
                    _flash(auth.session_data, 'error', 'Confirm Password: Passwords must match')
                elif first_form_value(form, 'password') == first_form_value(form, 'current_password'):
                    _flash(auth.session_data, 'error', "Pick a password you're not already using.")
                else:
                    try:
                        user.set_password(form['password'])
                        data.commit()
                        _refresh_password_session(auth.session_data, user, request, flask_app.config)
                        remember_cookie = True
                        _flash(auth.session_data, 'success', 'Password changed successfully!')
                    except Exception:
                        data.rollback()
                        _flash(auth.session_data, 'error', 'An error occurred. Please try again.')
                response = RedirectResponse('/library?account=password', status_code=302)
                if remember_cookie:
                    _write_remember_cookie(response, flask_app, auth.session_data)

            if auth.should_set_session_cookie or auth.session_data.get('_flashes'):
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            response.headers.setdefault('Cache-Control', 'no-store')
            return response

    return router


def mount_account_password_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_account_password_router(flask_app, **kwargs))
    return app


async def _validated_body(request: Request, model):
    import json

    from oneirodex.utils.api_contract import api_error_payload

    try:
        value = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        return None, _api_error('Invalid request.', code='unprocessable')
    try:
        body = model.model_validate(value if isinstance(value, dict) else {})
        return body, None
    except ValidationError as exc:
        payload, status = api_error_payload(
            'Invalid request.',
            code='unprocessable',
            detail=format_validation_errors(exc),
        )
        from starlette.responses import JSONResponse

        return None, JSONResponse(payload, status_code=status)


async def _legacy_password_form(request: Request):
    from urllib.parse import parse_qs

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 64 * 1024:
            return {}, Response(status_code=413)
    try:
        fields = parse_qs(bytes(body).decode('utf-8'), keep_blank_values=True)
    except UnicodeDecodeError:
        return {}, Response(status_code=400)
    return first_form_values(fields), None


def _api_error(message: str, *, code: str):
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


def _refresh_password_session(session_data, user, request, config) -> None:
    from .auth_resolver import session_identifier
    from oneirodex.utils.trusted_proxy import trusted_forwarded_for

    session_data['_user_id'] = str(user.get_id())
    session_data['_fresh'] = True
    session_data['_id'] = session_identifier(
        getattr(getattr(request, 'client', None), 'host', None),
        request.headers.get('User-Agent'),
        trusted_forwarded_for(request, config),
    )
    session_data['_remember'] = 'set'


def _write_remember_cookie(response: Response, flask_app, session_data) -> None:
    from .session_compat import encode_remember_cookie

    config = flask_app.config
    remember_id = session_data.get('_user_id')
    if not remember_id:
        return
    duration = config.get('REMEMBER_COOKIE_DURATION') or timedelta(days=365)
    seconds = session_data.pop('_remember_seconds', None)
    if seconds is not None:
        duration = timedelta(seconds=seconds)
    response.set_cookie(
        config.get('REMEMBER_COOKIE_NAME', 'remember_token'),
        encode_remember_cookie(str(remember_id), config['SECRET_KEY']),
        expires=datetime.now(timezone.utc) + duration,
        path=config.get('REMEMBER_COOKIE_PATH') or '/',
        domain=config.get('REMEMBER_COOKIE_DOMAIN'),
        secure=bool(config.get('REMEMBER_COOKIE_SECURE', False)),
        httponly=bool(config.get('REMEMBER_COOKIE_HTTPONLY', True)),
        samesite=config.get('REMEMBER_COOKIE_SAMESITE'),
    )
    session_data.pop('_remember', None)
