"""Native admin read/write API for persisted loading-icon settings."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response, RedirectResponse

from .acquire_status import _login_redirect, _set_session_cookie
from .csrf_compat import csrf_error_response
from .request_auth import request_auth_context


class LoadingIconAdminData:
    def public(self):
        from oneirodex.utils.loading_icons import member_loading_icon_payload

        return member_loading_icon_payload()

    def get(self):
        from oneirodex.utils.loading_icons import get_loading_icon_settings

        return get_loading_icon_settings(admin=True)

    def save(self, payload):
        from oneirodex.utils.loading_icons import save_loading_icon_settings

        return save_loading_icon_settings(payload)


def create_loading_icon_admin_router(
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
    data = data_access or LoadingIconAdminData()

    @router.api_route('/api/loading-icon', methods=['GET', 'HEAD'])
    def public_loading_icon(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            response = JSONResponse(data.public())
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    def finish(response: Response, request: Request, auth):
        if auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    def admin_denial(auth):
        from oneirodex.utils.role_catalog import normalize_role

        role = normalize_role(getattr(auth.user, 'role', None) or '')
        if role == 'admin' and auth.token is not None and not auth.has_scope('admin'):
            from oneirodex.utils.api_contract import api_error_payload

            payload, status = api_error_payload(
                'This token does not have the admin scope', code='forbidden',
            )
            return JSONResponse(payload, status_code=status)
        if role != 'admin':
            flashes = list(auth.session_data.get('_flashes') or [])
            flashes.append(('danger', 'You must be an admin to access this page.'))
            auth.session_data['_flashes'] = flashes
            response = RedirectResponse('/login', status_code=302)
            _set_session_cookie(response, flask_app, auth)
            return response
        return None

    @router.api_route('/api/admin/loading-icon/config', methods=['GET', 'HEAD', 'PUT'])
    async def loading_icon_config(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if request.method == 'PUT':
                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                response = admin_denial(auth)
            if response is None and request.method in ('GET', 'HEAD'):
                response = JSONResponse(data.get())
            if response is None:
                body = await _json_object(request)
                if not body:
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload('No fields to update', code='bad_request')
                    response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        saved = data.save(body)
                    except ValueError as exc:
                        from oneirodex.utils.api_contract import api_error_payload

                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({'status': 'saved', **saved}))
            return finish(response, request, auth)

    @router.api_route('/api/admin/themes/loading-icons', methods=['GET', 'HEAD'])
    def admin_theme_loading_icons(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                response = admin_denial(auth)
                if response is None:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(data.get()))
            return finish(response, request, auth)

    return router


async def _json_object(request: Request) -> dict:
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' and not (
            content_type.startswith('application/') and content_type.endswith('+json')
        ):
            return {}
        body = await request.json()
    except Exception:  # noqa: BLE001 — matches the legacy silent JSON parser
        return {}
    return body if isinstance(body, dict) else {}


def mount_loading_icon_admin_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_loading_icon_admin_router(flask_app, **kwargs))
    return app
