"""Native FastAPI mutation routes for admin-managed user accounts."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminUserMutationData:
    def _lock_and_reload_actor(self, actor_id):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.admin_invariant import lock_admin_mutation

        lock_admin_mutation(db.session)
        actor = db.session.execute(
            select(User).where(User.id == actor_id).execution_options(populate_existing=True)
        ).scalars().first()
        if actor is None or actor.role != 'admin' or actor.state is False:
            return None
        return actor

    def _find_user(self, user_id, *, refresh=False):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        if not refresh:
            return db.session.get(User, user_id)
        return db.session.execute(
            select(User).where(User.id == user_id).execution_options(populate_existing=True)
        ).scalars().first()

    def _protect_active_admin(self, user_id, *, new_role=None, new_state=None):
        from sqlalchemy import func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        active_admins = db.session.execute(
            select(func.count(User.id)).where(User.role == 'admin', User.state.is_not(False))
        ).scalar()
        user = self._find_user(user_id)
        if user is None:
            return False, 'User not found'
        if user.role == 'admin' and user.state is not False and active_admins <= 1:
            if (new_role and new_role != 'admin') or (new_state is not None and not new_state):
                return False, 'Cannot modify the last active admin account'
        return True, ''

    def update(self, user_id, body, actor_id):
        from sqlalchemy.exc import IntegrityError
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.accounts import display_email, is_placeholder_email, placeholder_email
        from oneirodex.utils.admin_user_validation import validate_about, validate_email, validate_role
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.library_acl import (
            get_user_content_filters, set_user_content_filters, set_user_library_allowlist,
        )

        actor = self._lock_and_reload_actor(actor_id)
        if actor is None:
            return None, ('Admin account is no longer active', 'forbidden', None), False
        user = self._find_user(user_id, refresh=True)
        if user is None:
            return None, ('User not found', 'not_found', None), False
        if user_id == 1 and actor.id != 1:
            return None, ('Cannot modify primary admin account', 'forbidden', None), False
        if actor.id == user_id and body.get('role') and body['role'] != user.role:
            return None, ('Cannot modify your own role', 'forbidden', None), False

        changes = []
        if 'email' in body:
            new_email = (body['email'] or '').strip().lower()
            if not new_email:
                if not is_placeholder_email(user.email):
                    changes.append(f"email from '{user.email}' to none — local account")
                    user.email = placeholder_email(user.name)
                    user.is_email_verified = False
            elif new_email != (user.email or '').lower():
                valid, message = validate_email(new_email)
                if not valid:
                    return None, (message, 'bad_request', None), False
                from sqlalchemy import func, select
                duplicate = db.session.execute(
                    select(User.id).where(func.lower(User.email) == new_email, User.id != user_id)
                ).scalar_one_or_none()
                if duplicate is not None:
                    return None, ('Email address is already in use', 'bad_request', None), False
                previous = display_email(user.email) or 'none — local account'
                changes.append(f"email from '{previous}' to '{new_email}'")
                user.email = new_email

        if 'role' in body:
            new_role = body['role']
            if new_role != user.role:
                valid, message = validate_role(new_role)
                if not valid:
                    return None, (message, 'bad_request', None), False
                valid, message = self._protect_active_admin(user_id, new_role=new_role)
                if not valid:
                    return None, (message, 'forbidden', None), False
                changes.append(f"role from '{user.role}' to '{new_role}'")
                user.role = new_role

        if 'state' in body:
            new_state = body['state']
            if not isinstance(new_state, bool):
                return None, ('State must be true or false', 'bad_request', None), False
            if new_state != user.state:
                valid, message = self._protect_active_admin(user_id, new_state=new_state)
                if not valid:
                    return None, (message, 'forbidden', None), False
                changes.append(f"state to {'active' if new_state else 'inactive'}")
                user.state = new_state

        if 'is_email_verified' in body:
            verified = body['is_email_verified']
            if not isinstance(verified, bool):
                return None, ('Email verification status must be true or false', 'bad_request', None), False
            if verified != user.is_email_verified:
                changes.append(f"email verification to {'verified' if verified else 'unverified'}")
                user.is_email_verified = verified

        if 'about' in body:
            about = body['about']
            valid, message = validate_about(about)
            if not valid:
                return None, (message, 'bad_request', None), False
            if about != user.about:
                changes.append('about field')
                user.about = about

        password_changed = bool(body.get('password'))
        if password_changed:
            password = body['password']
            if not isinstance(password, str) or not password.strip():
                return None, ('Invalid password provided', 'bad_request', None), False
            user.set_password(password)
            changes.append('password')

        if 'allowed_library_uuids' in body:
            uuids = body.get('allowed_library_uuids') or []
            if not isinstance(uuids, list):
                return None, ('allowed_library_uuids must be a list', 'bad_request', None), False
            set_user_library_allowlist(user.id, [str(value) for value in uuids])
            changes.append('library allow-list')

        if 'denied_genres' in body or 'denied_themes' in body:
            denied_genres = body.get('denied_genres')
            denied_themes = body.get('denied_themes')
            if denied_genres is not None and not isinstance(denied_genres, list):
                return None, ('denied_genres must be a list', 'bad_request', None), False
            if denied_themes is not None and not isinstance(denied_themes, list):
                return None, ('denied_themes must be a list', 'bad_request', None), False
            existing = get_user_content_filters(user.id)
            set_user_content_filters(
                user.id,
                denied_genres if denied_genres is not None else existing['denied_genres'],
                denied_themes if denied_themes is not None else existing['denied_themes'],
            )
            changes.append('content deny-list')

        try:
            db.session.commit()
            if changes:
                log_system_event(
                    f"Admin {actor.name} modified user {user.name}: {', '.join(changes)}",
                    event_type='audit', event_level='information', audit_user=actor.id,
                )
            return {}, None, password_changed and user.id == actor.id
        except IntegrityError:
            db.session.rollback()
            log_system_event(
                f'Admin {actor.name} failed to modify user {user.name}: database integrity error',
                event_type='audit', event_level='error', audit_user=actor.id,
            )
            return None, ('Email address already in use', 'bad_request', None), False
        except Exception:  # noqa: BLE001 — don't expose persistence diagnostics
            db.session.rollback()
            log_system_event(
                f'Admin {actor.name} failed to modify user {user.name}: database error',
                event_type='audit', event_level='error', audit_user=actor.id,
            )
            return None, ('Failed to update user', 'internal', None), False

    def delete(self, user_id, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.event_logging import log_system_event

        actor = self._lock_and_reload_actor(actor_id)
        if actor is None:
            return None, ('Admin account is no longer active', 'forbidden', None)
        user = self._find_user(user_id, refresh=True)
        if user is None:
            return None, ('User not found', 'not_found', None)
        if user_id == 1:
            return None, ('Cannot delete primary admin account', 'forbidden', None)
        valid, message = self._protect_active_admin(user_id, new_state=False)
        if not valid:
            return None, (message, 'forbidden', None)
        info = f'{user.name} (email: {user.email}, role: {user.role})'
        try:
            db.session.delete(user)
            db.session.commit()
            log_system_event(
                f'Admin {actor.name} deleted user: {info}',
                event_type='audit', event_level='warning', audit_user=actor.id,
            )
            return {}, None
        except Exception:  # noqa: BLE001 — persistence diagnostics stay in logs
            db.session.rollback()
            log_system_event(
                f'Admin {actor.name} failed to delete user {info}: database error',
                event_type='audit', event_level='error', audit_user=actor.id,
            )
            return None, ('Failed to delete user', 'internal', None)


def create_admin_user_mutation_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminUserMutationData()

    @router.put('/admin/api/user/{user_id:int}')
    @router.delete('/admin/api/user/{user_id:int}')
    async def mutate_admin_user(request: Request, user_id: int):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.role_catalog import normalize_role
            actor = auth.user
            admin = (
                actor is not None and bool(getattr(actor, 'is_authenticated', True))
                and normalize_role(getattr(actor, 'role', None) or '') == 'admin'
            )
            if auth.token is None:
                from .csrf_compat import csrf_error_response
                csrf_response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                csrf_response = None
            if csrf_response is not None:
                response = csrf_response
            elif actor is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                response = _error('This token does not have the admin scope', 'forbidden')
            else:
                try:
                    if request.method == 'DELETE':
                        payload, error = data.delete(user_id, actor.id)
                        refresh_session = False
                    else:
                        body = await _json_object(request)
                        if body is None:
                            payload, error, refresh_session = None, ('No data provided', 'bad_request', None), False
                        else:
                            payload, error, refresh_session = data.update(user_id, body, actor.id)
                    response = _result(payload, error)
                    if refresh_session:
                        _refresh_password_session(auth.session_data, actor, request, flask_app.config)
                        _write_remember_cookie(response, flask_app, auth.session_data)
                except Exception:  # noqa: BLE001 — mutation routes fail closed
                    response = _error('Failed to update user' if request.method == 'PUT' else 'Failed to delete user', 'internal')
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            response.headers.setdefault('Cache-Control', 'no-store')
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


def _refresh_password_session(session_data, user, request, config):
    from .auth_resolver import session_identifier
    from oneirodex.utils.trusted_proxy import trusted_forwarded_for
    session_data['_user_id'] = str(user.get_id())
    session_data['_fresh'] = True
    session_data['_id'] = session_identifier(
        getattr(getattr(request, 'client', None), 'host', None),
        request.headers.get('User-Agent'), trusted_forwarded_for(request, config),
    )
    session_data['_remember'] = 'set'


def _write_remember_cookie(response, flask_app, session_data):
    from .session_compat import encode_remember_cookie
    config = flask_app.config
    duration = config.get('REMEMBER_COOKIE_DURATION') or timedelta(days=365)
    seconds = session_data.pop('_remember_seconds', None)
    if seconds is not None:
        duration = timedelta(seconds=seconds)
    response.set_cookie(
        config.get('REMEMBER_COOKIE_NAME', 'remember_token'),
        encode_remember_cookie(str(session_data['_user_id']), config['SECRET_KEY']),
        expires=datetime.now(timezone.utc) + duration,
        path=config.get('REMEMBER_COOKIE_PATH') or '/',
        domain=config.get('REMEMBER_COOKIE_DOMAIN'),
        secure=bool(config.get('REMEMBER_COOKIE_SECURE', False)),
        httponly=bool(config.get('REMEMBER_COOKIE_HTTPONLY', True)),
        samesite=config.get('REMEMBER_COOKIE_SAMESITE'),
    )
    session_data.pop('_remember', None)


def mount_admin_user_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_user_mutation_router(flask_app, **kwargs))
    return app
