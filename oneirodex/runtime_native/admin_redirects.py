"""FastAPI compatibility redirects for retired administrator page URLs."""
from __future__ import annotations

from contextlib import nullcontext
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import RedirectResponse


ADMIN_REDIRECTS = {
    '/admin/library_tools': '/scan_management?active_tab=tools',
    '/admin/server_logs': '/admin/ops?open=full-log',
    '/admin/system_logs': '/admin/ops?open=full-log',
    '/admin/server_status_page': '/admin/ops',
}
ADMIN_QUERY_REDIRECTS = {'/admin/scan_management': '/scan_management'}


def is_admin_redirect_path(path: str) -> bool:
    return path in ADMIN_REDIRECTS or path in ADMIN_QUERY_REDIRECTS


def create_admin_redirect_router(
    flask_app,
    *,
    find_user,
    find_token,
    commit_token_touch,
    login_manager=None,
    database_scope=None,
):
    router = APIRouter()

    def handler(request: Request):
        from .acquire_status import _login_redirect, _set_session_cookie
        from .admin_pilot import _native_auth_backend, _native_json_error
        from .request_auth import request_auth_context
        from oneirodex.utils.role_catalog import normalize_role
        from oneirodex.utils.security_headers import security_header_values

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            if find_user is None:
                user_lookup, token_lookup, token_touch = _native_auth_backend(flask_app)
            else:
                user_lookup, token_lookup, token_touch = (
                    find_user, find_token, commit_token_touch,
                )
            manager = login_manager or getattr(flask_app, 'login_manager', None)
            auth = request_auth_context(
                request, flask_app.config,
                find_user=user_lookup,
                find_token=token_lookup,
                commit_token_touch=token_touch,
                login_manager=manager,
            )
            role = normalize_role(getattr(auth.user, 'role', None) or '')
            if auth.user is None:
                response = _login_redirect(flask_app, request, manager, auth)
            elif role != 'admin':
                flashes = list(auth.session_data.get('_flashes') or [])
                flashes.append(('danger', 'You must be an admin to access this page.'))
                auth.session_data['_flashes'] = flashes
                response = RedirectResponse('/login', status_code=302)
            elif not auth.has_scope('admin'):
                response = _native_json_error(
                    'This token does not have the admin scope', 'forbidden', 403,
                )
            else:
                target = ADMIN_REDIRECTS.get(request.url.path)
                if target is None:
                    target = ADMIN_QUERY_REDIRECTS[request.url.path]
                    query = {}
                    for key, value in request.query_params.multi_items():
                        query.setdefault(key, value)
                    if query:
                        target += '?' + urlencode(query)
                response = RedirectResponse(target, status_code=302)
            if auth.user is not None and auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)

        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    for path in (*ADMIN_REDIRECTS, *ADMIN_QUERY_REDIRECTS):
        router.add_api_route(path, handler, methods=['GET', 'HEAD'])

    @router.api_route('/delete_filter/{filter_id:int}', methods=['GET', 'HEAD'])
    def delete_filter_notice(request: Request, filter_id: int):
        from .acquire_status import _login_redirect, _set_session_cookie
        from .admin_pilot import _native_json_error
        from .request_auth import request_auth_context
        from oneirodex.utils.role_catalog import normalize_role
        from oneirodex.utils.security_headers import security_header_values

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            manager = login_manager or getattr(flask_app, 'login_manager', None)
            if find_user is None:
                user_lookup, token_lookup, token_touch = _native_auth_backend(flask_app)
            else:
                user_lookup, token_lookup, token_touch = find_user, find_token, commit_token_touch
            auth = request_auth_context(
                request, flask_app.config, find_user=user_lookup,
                find_token=token_lookup, commit_token_touch=token_touch,
                login_manager=manager,
            )
            role = normalize_role(getattr(auth.user, 'role', None) or '')
            if auth.user is None:
                response = _login_redirect(flask_app, request, manager, auth)
            elif role != 'admin':
                flashes = list(auth.session_data.get('_flashes') or [])
                flashes.append(('danger', 'You must be an admin to access this page.'))
                auth.session_data['_flashes'] = flashes
                response = RedirectResponse('/login', status_code=302)
            elif not auth.has_scope('admin'):
                response = _native_json_error(
                    'This token does not have the admin scope', 'forbidden', 403,
                )
            else:
                flashes = list(auth.session_data.get('_flashes') or [])
                flashes.append(('warning', 'Open Scan Filters and confirm removal there.'))
                auth.session_data['_flashes'] = flashes
                response = RedirectResponse('/admin/edit_filters', status_code=302)
            if auth.user is not None and (
                auth.should_set_session_cookie or auth.session_data.get('_flashes')
            ):
                _set_session_cookie(response, flask_app, auth)

        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response
    return router


def mount_admin_redirect_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_redirect_router(flask_app, **kwargs))
    return app
