"""Native admin APIs for configured library roots and folder browsing."""
from __future__ import annotations

import os
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class BrowseLocationsData:
    def roots(self, flask_app):
        from oneirodex.utils.library_roots import library_roots

        return library_roots(flask_app)

    def root_availability(self, root):
        from oneirodex.utils.library_roots import root_availability

        return root_availability(root)

    def resolve_root(self, root_id, flask_app):
        from oneirodex.utils.library_roots import resolve_library_root

        return resolve_library_root(root_id, flask_app)

    def allowed_bases(self, flask_app):
        from oneirodex.utils.security import get_allowed_base_directories

        return get_allowed_base_directories(flask_app)

    def is_safe_path(self, path, bases, logger):
        from oneirodex.utils.security import is_safe_path

        return is_safe_path(path, bases, logger=logger)

    def join(self, base, child):
        return os.path.abspath(os.path.join(base, child))

    def absolute(self, path):
        return os.path.abspath(path)

    def directory_exists(self, path):
        return os.path.isdir(path)

    def list_directory(self, path):
        names = sorted(os.listdir(path))
        contents = []
        for name in names:
            item_path = os.path.join(path, name)
            is_dir = os.path.isdir(item_path)
            contents.append({
                'name': name,
                'isDir': is_dir,
                'ext': None if is_dir else os.path.splitext(name)[1][1:].lower(),
                'size': None if is_dir else os.path.getsize(item_path),
            })
        return sorted(contents, key=lambda item: (not item['isDir'], item['name'].lower()))

    def parent(self, path):
        return os.path.dirname(path)

    def relative(self, path, base):
        return os.path.relpath(path, base)

    def is_parent_relative(self, relative):
        return relative == os.pardir or relative.startswith(os.pardir + os.sep)


def create_browse_locations_router(
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
    data = data_access or BrowseLocationsData()

    @router.api_route('/api/library_roots', methods=['GET', 'HEAD'])
    def library_roots_route(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            response = _authorize(auth, flask_app, request, login_manager)
            if response is None:
                from oneirodex.utils.api_contract import api_ok_payload

                roots = [data.root_availability(root) for root in data.roots(flask_app)]
                response = JSONResponse(api_ok_payload({'roots': roots}))
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            return _finish(response, flask_app, request)

    @router.api_route('/api/browse_folders_ss', methods=['GET', 'HEAD'])
    def browse_folders_route(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            response = _authorize(auth, flask_app, request, login_manager)
            if response is None:
                response = _browse(request, flask_app, data)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            return _finish(response, flask_app, request)

    return router


def _authorize(auth, flask_app, request, login_manager):
    if auth.user is None:
        return _login_redirect(flask_app, request, login_manager, auth)
    if not _is_admin(auth.user):
        from .oidc_status import _login_redirect as admin_login_redirect

        return admin_login_redirect(
            flask_app, request, login_manager, auth,
            message='You must be an admin to access this page.',
            category='danger', include_next=False,
        )
    if auth.token is not None and not auth.has_scope('admin'):
        return _error(403, 'forbidden', 'This token does not have the admin scope')
    return None


def _browse(request, flask_app, data):
    query = request.query_params
    roots = query.getlist('root')
    root_arg = roots[0] if roots else None
    if root_arg:
        root = data.resolve_root(root_arg, flask_app)
        if not root:
            return _error(404, 'not_found', 'Unknown scan location')
        base_directory = root['path']
    else:
        key = 'BASE_FOLDER_WINDOWS' if os.name == 'nt' else 'BASE_FOLDER_POSIX'
        base_directory = flask_app.config.get(key)

    abs_paths = query.getlist('abs_path')
    abs_path_arg = abs_paths[0] if abs_paths else None
    if abs_path_arg:
        allowed_bases = data.allowed_bases(flask_app)
        ok, _reason = data.is_safe_path(abs_path_arg, allowed_bases, flask_app.logger)
        if not ok:
            return _error(403, 'forbidden', 'Access denied')
        folder_path = data.absolute(abs_path_arg)
        if not data.directory_exists(folder_path):
            folder_path = data.parent(folder_path)
            if not data.directory_exists(folder_path):
                return _error(404, 'not_found', 'SS folder browser: Folder not found')
        resolved_path = None
        if base_directory:
            try:
                relative = data.relative(folder_path, base_directory)
                if not data.is_parent_relative(relative):
                    resolved_path = '' if relative == '.' else relative.replace(os.sep, '/') + '/'
            except ValueError:
                resolved_path = None
        return JSONResponse({
            'items': data.list_directory(folder_path),
            'resolved_path': resolved_path,
            'outside_base': resolved_path is None,
            'absolute_path': folder_path,
        })

    request_paths = query.getlist('path')
    request_path = request_paths[0] if request_paths else ''
    if not request_path:
        folder_path = base_directory
    else:
        folder_path = data.join(base_directory, request_path)
        ok, _reason = data.is_safe_path(folder_path, [base_directory], flask_app.logger)
        if not ok:
            return _error(403, 'forbidden', 'Access denied')
    if data.directory_exists(folder_path):
        return JSONResponse(data.list_directory(folder_path))
    return _error(404, 'not_found', 'SS folder browser: Folder not found')


def _is_admin(user):
    from oneirodex.utils.role_catalog import normalize_role

    return normalize_role(getattr(user, 'role', None) or '') == 'admin'


def _error(status, code, message):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)


def _finish(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
    return response


def mount_browse_locations_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_browse_locations_router(flask_app, **kwargs))
    return app
