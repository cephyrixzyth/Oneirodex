"""Native FastAPI creation route for admin-managed household accounts."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminUserCreateData:
    def create(self, body, actor):
        from sqlalchemy import func, select
        from sqlalchemy.exc import IntegrityError
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.accounts import display_email, placeholder_email
        from oneirodex.utils.admin_user_validation import (
            validate_about, validate_email, validate_role, validate_username,
        )
        from oneirodex.utils.event_logging import log_system_event

        username = body.get('username', '').strip()
        email = body.get('email', '').strip().lower()
        password = body.get('password', '')
        role = body.get('role', 'user')
        state = body.get('state', True)
        verified = body.get('is_email_verified', True)
        about = body.get('about', '')
        emailless = not email
        if emailless:
            email = placeholder_email(username)
            verified = False

        for valid, message in (
            validate_username(username),
            ((True, '') if emailless else validate_email(email)),
            validate_role(role),
            validate_about(about),
        ):
            if not valid:
                return None, (message, 'bad_request', None)
        if not password:
            return None, ('Password is required', 'bad_request', None)
        if not isinstance(state, bool):
            return None, ('State must be true or false', 'bad_request', None)
        if not isinstance(verified, bool):
            return None, ('Email verification status must be true or false', 'bad_request', None)

        username_exists = db.session.execute(
            select(User.id).where(func.lower(User.name) == username.lower())
        ).scalar_one_or_none()
        if username_exists is not None:
            return None, ('Username is already taken', 'bad_request', None)
        email_exists = db.session.execute(
            select(User.id).where(func.lower(User.email) == email.lower())
        ).scalar_one_or_none()
        if email_exists is not None:
            return None, ('Email address is already in use', 'bad_request', None)

        try:
            created = User(
                name=username, email=email, role=role, state=state,
                is_email_verified=verified, about=about if about else None,
                user_id=str(uuid4()),
            )
            created.set_password(password)
            db.session.add(created)
            db.session.commit()
            log_system_event(
                f"Admin {actor.name} created new user: {username} "
                f"(email: {'none — local account' if emailless else email}, role: {role})",
                event_type='audit', event_level='information', audit_user=actor.id,
            )
            return {'user': {
                'id': created.id, 'name': created.name,
                'email': display_email(created.email), 'has_email': not emailless,
                'role': created.role,
            }}, None
        except IntegrityError:
            db.session.rollback()
            log_system_event(
                f'Admin {actor.name} failed to create user {username}: database integrity error',
                event_type='audit', event_level='error', audit_user=actor.id,
            )
            return None, ('Username or email already exists', 'bad_request', None)
        except Exception:  # noqa: BLE001 — don't expose persistence diagnostics
            db.session.rollback()
            log_system_event(
                f'Admin {actor.name} failed to create user {username}: database error',
                event_type='audit', event_level='error', audit_user=actor.id,
            )
            return None, ('Failed to create user', 'internal', None)


def create_admin_user_create_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminUserCreateData()

    @router.put('/admin/api/user/0')
    async def create_admin_user(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                csrf_response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                csrf_response = None
            from oneirodex.utils.role_catalog import normalize_role
            user = auth.user
            is_admin = (
                user is not None and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not is_admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                response = _error('This token does not have the admin scope', 'forbidden')
            else:
                body = await _json_object(request)
                if body is None:
                    response = _error('No data provided', 'bad_request')
                else:
                    try:
                        payload, error = data.create(body, user)
                        response = _result(payload, error)
                    except Exception:  # noqa: BLE001 — creation fails closed
                        response = _error('Failed to create user', 'internal')
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


async def _json_object(request):
    import json
    try:
        body = json.loads(await request.body() or b'null')
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _result(payload, error):
    if error is not None:
        return _error(error[0], error[1], error[2])
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload(payload))


def _error(message, code, status=None):
    from oneirodex.utils.api_contract import api_error_payload
    payload, status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=status)


def mount_admin_user_create_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_user_create_router(flask_app, **kwargs))
    return app
