"""FastAPI compatibility read for the React admin user roster."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminUsersReadData:
    def list(self):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.accounts import display_email, is_placeholder_email

        users = db.session.execute(select(User).order_by(User.name.asc())).scalars().all()
        return {'users': [{
            'id': user.id,
            'email': display_email(user.email) or '',
            'has_email': not is_placeholder_email(user.email),
            'name': user.name, 'role': user.role, 'state': bool(user.state),
            'is_email_verified': bool(user.is_email_verified),
            'about': user.about or '', 'avatarpath': user.avatarpath or '',
        } for user in users]}

    def detail(self, user_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.accounts import display_email, is_placeholder_email
        from oneirodex.utils.library_acl import (
            get_user_content_filters, get_user_library_allowlist,
        )

        user = db.session.get(User, user_id)
        if user is None:
            return None
        filters = get_user_content_filters(user.id)
        return {
            'email': display_email(user.email) or '',
            'has_email': not is_placeholder_email(user.email),
            'role': user.role, 'state': user.state, 'about': user.about,
            'is_email_verified': user.is_email_verified,
            'allowed_library_uuids': get_user_library_allowlist(user.id),
            'denied_genres': filters['denied_genres'],
            'denied_themes': filters['denied_themes'],
        }


def create_admin_users_read_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminUsersReadData()

    @router.api_route('/admin/api/users', methods=['GET', 'HEAD'])
    @router.api_route('/admin/api/user/{user_id:int}', methods=['GET', 'HEAD'])
    async def admin_users(request: Request, user_id: int | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.role_catalog import normalize_role
            user = auth.user
            admin = (
                user is not None and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                from oneirodex.utils.api_contract import api_error_payload
                payload, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden',
                )
                response = JSONResponse(payload, status_code=status)
            else:
                if user_id is None:
                    payload = data.list()
                else:
                    payload = data.detail(user_id)
                    if payload is None:
                        from oneirodex.utils.api_contract import api_error_payload
                        body, status = api_error_payload('User not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                        payload = None
                if payload is not None:
                    response = JSONResponse(payload)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            response.headers.setdefault('Cache-Control', 'no-store')
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_admin_users_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_users_read_router(flask_app, **kwargs))
    return app
