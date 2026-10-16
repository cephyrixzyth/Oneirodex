"""Native admin reads for the local plugin catalogue."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminPluginsData:
    def list(self, category=None):
        from oneirodex.utils.plugins import list_plugins
        return list_plugins(category=category)

    def get(self, plugin_id):
        from oneirodex.utils.plugins import get_plugin
        return get_plugin(plugin_id)


def create_admin_plugins_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminPluginsData()

    @router.api_route('/api/plugins', methods=['GET', 'HEAD'])
    @router.api_route('/api/plugins/{plugin_id}', methods=['GET', 'HEAD'])
    def plugins(request: Request, plugin_id: str | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload
            from oneirodex.utils.role_catalog import normalize_role
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif plugin_id is None:
                response = JSONResponse({'plugins': data.list(request.query_params.get('category'))})
            else:
                item = data.get(plugin_id)
                if item is None:
                    payload, status = api_error_payload('Not found', code='not_found')
                    response = JSONResponse(payload, status_code=status)
                else:
                    response = JSONResponse(item)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_admin_plugins_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_plugins_router(flask_app, **kwargs))
    return app
