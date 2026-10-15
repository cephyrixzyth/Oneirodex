"""Native admin statistics reads with both versioned and classic payloads."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


def create_admin_statistics_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    statistics_reader: Callable[[], dict] | None = None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    if statistics_reader is None:
        from oneirodex.utils.statistics import get_download_statistics

        statistics_reader = get_download_statistics

    def serve_statistics(request: Request, *, wrapped: bool):
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
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user
            is_admin = (
                user is not None
                and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if user is None:
                response = _login_redirect(
                    flask_app,
                    request,
                    login_manager,
                    auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            elif not is_admin:
                response = _login_redirect(
                    flask_app,
                    request,
                    login_manager,
                    auth,
                    message='You must be an admin to access this page.',
                    category='danger',
                    include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden'
                )
                response = JSONResponse(payload, status_code=status)
            else:
                data = statistics_reader()
                response = JSONResponse(api_ok_payload(data) if wrapped else data)

        from oneirodex.utils.security_headers import security_header_values

        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    @router.api_route('/api/admin/statistics', methods=['GET', 'HEAD'])
    def admin_statistics(request: Request):
        return serve_statistics(request, wrapped=True)

    @router.api_route('/admin/statistics/data', methods=['GET', 'HEAD'])
    def legacy_admin_statistics_data(request: Request):
        return serve_statistics(request, wrapped=False)

    return router


def mount_admin_statistics_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_statistics_router(flask_app, **kwargs))
    return app
