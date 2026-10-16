"""Native static React-shell routes for member authentication pages."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import RedirectResponse, Response

from .request_auth import request_auth_context


class AuthPageData:
    def invite_active(self, token):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import InviteToken

        invite = db.session.execute(
            select(InviteToken).filter_by(token=token, used=False)
        ).scalar_one_or_none()
        expires = invite.expires_at if invite else None
        if expires is None:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires >= datetime.now(timezone.utc)

    def reset_token_active(self, token):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        user = db.session.execute(
            select(User).filter_by(password_reset_token=token)
        ).scalar_one_or_none()
        issued = user.token_creation_time if user else None
        if issued is None:
            return False
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        return issued + timedelta(minutes=15) >= datetime.now(timezone.utc)


def create_auth_pages_router(
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
    data = data_access or AuthPageData()

    @router.api_route('/login', methods=['GET', 'HEAD'])
    def login_page(request: Request):
        return _serve_shell(
            request, flask_app, page='login', find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope, data=data,
        )

    @router.api_route('/register', methods=['GET', 'HEAD'])
    def register_page(request: Request):
        return _serve_shell(
            request, flask_app, page='register', find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope, data=data,
        )

    @router.api_route('/confirm/{token}', methods=['GET', 'HEAD'])
    def confirm_page(request: Request, token: str):
        return _serve_shell(
            request, flask_app, page='confirm', token=token, find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope, data=data,
        )

    @router.api_route('/reset_password_request', methods=['GET', 'HEAD'])
    def reset_request_page(request: Request):
        return _serve_shell(
            request, flask_app, page='reset_request', find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope, data=data,
        )

    @router.api_route('/reset_password/{token}', methods=['GET', 'HEAD'])
    def reset_page(request: Request, token: str):
        return _serve_shell(
            request, flask_app, page='reset', token=token, find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope, data=data,
        )

    def _serve_shell(
        request, app, *, page, token=None, find_user, find_token,
        commit_token_touch, load_user_id, login_manager, database_scope, data,
    ):
        scope = database_scope(app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
                allow_bearer=False,
            )
            invite_token = request.query_params.get('token') if page == 'register' else None
            if page == 'login' and auth.user is not None:
                response = RedirectResponse('/discover', status_code=302)
            elif page in {'reset_request', 'reset'} and auth.user is not None:
                response = RedirectResponse('/login', status_code=302)
            elif page == 'register' and auth.user is not None and not invite_token:
                response = RedirectResponse('/login', status_code=302)
            else:
                if page == 'register' and auth.user is not None and invite_token:
                    for key in ('_user_id', '_fresh', '_id', 'next', '_remember_seconds'):
                        auth.session_data.pop(key, None)
                    auth.session_data['_remember'] = 'clear'
                invalid_message = None
                if page == 'register' and invite_token and not data.invite_active(invite_token):
                    invalid_message = ('warning', 'The invite is invalid or has expired.')
                elif page == 'reset' and not data.reset_token_active(token):
                    invalid_message = ('info', 'The password reset link is invalid or has expired.')
                if invalid_message:
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append(invalid_message)
                    auth.session_data['_flashes'] = flashes
                    response = RedirectResponse(
                        '/register' if page == 'register' else '/login', status_code=302,
                    )
                else:
                    response = _shell_response(app, auth.session_data)

            if auth.remember_action:
                from oneirodex.runtime_native.auth_login import _write_remember_cookie

                _write_remember_cookie(response, auth.session_data, app.config)
            if auth.should_set_session_cookie:
                from oneirodex.runtime_native.oidc_status import _set_session_cookie

                _set_session_cookie(response, app, auth)
            _security_headers(response, app.config)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def _shell_response(app, session_data):
    path = Path(app.static_folder or '') / 'dist' / 'member-auth' / 'auth.html'
    try:
        shell = path.read_text(encoding='utf-8')
    except OSError:
        return Response(status_code=503)
    if shell.count('id="member-auth-root"') != 1 or '</body>' not in shell:
        return Response(status_code=503)
    notices = []
    for category, message in session_data.pop('_flashes', []) or []:
        role = 'alert' if category in {'error', 'danger'} else 'status'
        notices.append(
            '<p class="auth-pilot__message" role="' + role + '">'
            + escape(str(message), quote=True) + '</p>'
        )
    if notices:
        shell = shell.replace(
            '<div id="member-auth-root"></div>',
            '<div class="auth-pilot__notices" aria-label="Messages">'
            + ''.join(notices) + '</div><div id="member-auth-root"></div>', 1,
        )
    response = Response(content=shell, media_type='text/html')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Vary'] = 'Cookie'
    return response


def _security_headers(response, config):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(config).items():
        response.headers.setdefault(key, value)


def mount_auth_pages_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_auth_pages_router(flask_app, **kwargs))
    return app
