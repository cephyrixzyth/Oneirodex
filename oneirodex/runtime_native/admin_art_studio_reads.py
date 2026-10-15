"""Native reads for the admin art-studio catalogs and prompt lab."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminArtStudioReadData:
    def _package_root(self):
        return Path(__file__).resolve().parents[1]

    def stock_catalog(self):
        from oneirodex.utils.cover_art_stock import list_stock_catalog
        return list_stock_catalog(package_root=self._package_root())

    def system_marks_catalog(self):
        from oneirodex.utils.system_marks import list_system_marks_catalog, platform_choices
        return list_system_marks_catalog(package_root=self._package_root()), platform_choices()

    def system_marks_lab(self, *, theme, platform):
        from oneirodex.utils.system_marks import system_mark_lab_spec
        return system_mark_lab_spec(
            theme=theme, platform=platform, package_root=self._package_root(),
        )


def create_admin_art_studio_read_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminArtStudioReadData()

    @router.api_route('/admin/api/art-studio/stock', methods=['GET', 'HEAD'])
    async def stock_catalog(request: Request):
        return await _handle_read(
            request, flask_app, data, 'stock', find_user, find_token,
            commit_token_touch, load_user_id, login_manager, database_scope,
        )

    @router.api_route('/admin/api/art-studio/system-marks', methods=['GET', 'HEAD'])
    async def system_marks_catalog(request: Request):
        return await _handle_read(
            request, flask_app, data, 'system_marks', find_user, find_token,
            commit_token_touch, load_user_id, login_manager, database_scope,
        )

    @router.api_route('/admin/api/art-studio/system-marks/lab', methods=['GET', 'HEAD'])
    async def system_marks_lab(request: Request):
        return await _handle_read(
            request, flask_app, data, 'lab', find_user, find_token,
            commit_token_touch, load_user_id, login_manager, database_scope,
        )

    return router


async def _handle_read(
    request, flask_app, data, operation, find_user, find_token,
    commit_token_touch, load_user_id, login_manager, database_scope,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        from oneirodex.utils.role_catalog import normalize_role
        user = auth.user
        is_admin = (
            user is not None and bool(getattr(user, 'is_authenticated', True))
            and normalize_role(getattr(user, 'role', None) or '') == 'admin'
        )
        if user is None:
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
            try:
                if operation == 'stock':
                    items = data.stock_catalog()
                    payload = {'items': items, 'count': len(items)}
                elif operation == 'system_marks':
                    items, choices = data.system_marks_catalog()
                    payload = {'items': items, 'count': len(items), 'all_platforms': choices}
                else:
                    theme = (request.query_params.get('theme') or '').strip()
                    platform = (request.query_params.get('platform') or '').strip()
                    if not theme or not platform:
                        response = _error('theme and platform are required', 'bad_request')
                        payload = None
                    else:
                        try:
                            payload = data.system_marks_lab(theme=theme, platform=platform)
                        except ValueError as exc:
                            response = _error(str(exc), 'bad_request')
                            payload = None
                if payload is not None:
                    response = _result(payload, enveloped=operation != 'stock')
            except Exception as exc:  # noqa: BLE001 — preserve legacy error envelopes
                label = 'stock catalog' if operation == 'stock' else 'system marks'
                response = _error(f'Failed to list {label}: {exc}', 'internal')
        if auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD' and response.status_code == 200:
            response.body = b''
        return response


def _result(payload, *, enveloped):
    if enveloped:
        from oneirodex.utils.api_contract import api_ok_payload
        return JSONResponse(api_ok_payload(payload))
    return JSONResponse(payload)


def _error(message, code):
    from oneirodex.utils.api_contract import api_error_payload
    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


def mount_admin_art_studio_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_art_studio_read_router(flask_app, **kwargs))
    return app
