"""Native authenticated read for supported launcher import formats."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class LauncherImportReadData:
    def formats(self):
        from oneirodex.utils.launcher_imports import FORMATS
        return [{'id': item.key, 'name': item.name, 'store': item.store}
                for item in FORMATS.values()]


def create_launcher_import_read_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or LauncherImportReadData()

    @router.api_route('/api/imports/launchers', methods=['GET', 'HEAD'])
    def launcher_import_formats(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            else:
                from oneirodex.utils.api_contract import api_ok_payload
                response = JSONResponse(api_ok_payload({'launchers': data.formats()}))
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_launcher_import_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_launcher_import_read_router(flask_app, **kwargs))
    return app
