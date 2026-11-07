"""Native account routes for listing and revoking browser sessions."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


def create_account_sessions_router(
    flask_app: FastAPI,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id=None,
    login_manager=None,
    database_scope=None,
) -> APIRouter:
    from oneirodex.utils.persistent_sessions import (
        active_login_sessions,
        revoke_all_login_sessions,
        revoke_login_session,
        session_id_from_identity,
    )

    from oneirodex.utils.api_response import api_ok_payload

    router = APIRouter()

    def _context(request):
        return request_auth_context(
            request,
            flask_app.config,
            find_user=find_user,
            find_token=find_token,
            commit_token_touch=commit_token_touch,
            load_user_id=load_user_id,
            login_manager=login_manager,
        )

    def _delete_cookies(response):
        config = flask_app.config
        response.delete_cookie(
            config.get('SESSION_COOKIE_NAME', 'session'),
            path=config.get('SESSION_COOKIE_PATH') or config.get('APPLICATION_ROOT') or '/',
            domain=config.get('SESSION_COOKIE_DOMAIN'),
        )
        response.delete_cookie(
            config.get('REMEMBER_COOKIE_NAME', 'remember_token'),
            path=config.get('REMEMBER_COOKIE_PATH') or '/',
            domain=config.get('REMEMBER_COOKIE_DOMAIN'),
        )

    @router.get('/api/account/sessions')
    def list_sessions(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _context(request)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                current_id = session_id_from_identity(
                    str(auth.session_data.get('_user_id') or '')
                )
                response = JSONResponse(api_ok_payload({
                    'sessions': [
                        {
                            'id': row.id,
                            'current': row.id == current_id,
                            'created_at': _iso(row.created_at),
                            'last_seen_at': _iso(row.last_seen_at),
                            'expires_at': _iso(row.expires_at),
                        }
                        for row in active_login_sessions(auth.user.id)
                    ],
                }))
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            _headers(response, flask_app.config)
            return response

    @router.delete('/api/account/sessions/{session_id}')
    def revoke_one(session_id: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _context(request)
            csrf = csrf_error_response(request, auth.session_data, flask_app.config)
            if csrf is not None:
                response = csrf
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                revoked = revoke_login_session(session_id, user_id=auth.user.id)
                from oneirodex.runtime_native.db_session import native_db

                native_db.session.commit()
                response = JSONResponse(api_ok_payload({'revoked': revoked}))
                if session_id == session_id_from_identity(
                    str(auth.session_data.get('_user_id') or '')
                ):
                    _delete_cookies(response)
            _headers(response, flask_app.config)
            return response

    @router.delete('/api/account/sessions')
    def revoke_all(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _context(request)
            csrf = csrf_error_response(request, auth.session_data, flask_app.config)
            if csrf is not None:
                response = csrf
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                count = revoke_all_login_sessions(auth.user.id)
                from oneirodex.runtime_native.db_session import native_db

                native_db.session.commit()
                response = JSONResponse(api_ok_payload({'revoked_count': count}))
                _delete_cookies(response)
            _headers(response, flask_app.config)
            return response

    return router


def mount_account_sessions_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_account_sessions_router(flask_app, **kwargs))
    return app


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _headers(response, config):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(config).items():
        response.headers.setdefault(key, value)
    response.headers.setdefault('Cache-Control', 'no-store')
