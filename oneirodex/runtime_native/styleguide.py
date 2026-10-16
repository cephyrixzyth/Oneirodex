"""Native authenticated route for the visual styleguide."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse, Response

from .request_auth import request_auth_context


def create_styleguide_router(
    runtime_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.api_route('/dev/styleguide', methods=['GET', 'HEAD'])
    def styleguide(request: Request):
        from .acquire_status import _login_redirect, _set_session_cookie
        from .admin_pilot import _native_json_error
        from oneirodex.utils.role_catalog import normalize_role
        from oneirodex.utils.security_headers import security_header_values

        scope = database_scope(runtime_app) if database_scope else nullcontext()
        with scope:
            manager = getattr(runtime_app, 'login_manager', None)
            auth = request_auth_context(
                request,
                runtime_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=manager,
            )
            if auth.user is None:
                response = _login_redirect(runtime_app, request, manager, auth)
            elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                flashes = list(auth.session_data.get('_flashes') or [])
                flashes.append(('danger', 'You must be an admin to access this page.'))
                auth.session_data['_flashes'] = flashes
                response = RedirectResponse('/login', status_code=302)
            elif not auth.has_scope('admin'):
                response = _native_json_error(
                    'This token does not have the admin scope', 'forbidden', 403,
                )
            else:
                from oneirodex.runtime_native.session_compat import generate_csrf_token
                from oneirodex.utils.styleguide_page import render_styleguide

                csrf = generate_csrf_token(
                    auth.session_data,
                    runtime_app.config.get('WTF_CSRF_SECRET_KEY')
                    or runtime_app.config.get('SECRET_KEY'),
                    field_name=runtime_app.config.get('WTF_CSRF_FIELD_NAME', 'csrf_token'),
                )
                html = render_styleguide(
                    user=auth.user,
                    session_data=auth.session_data,
                    csrf_token=csrf,
                    static_url_path=getattr(runtime_app, 'static_url_path', '/static'),
                    package_root=getattr(runtime_app, 'root_path', None),
                    as_response=False,
                )
                response = Response(html, media_type='text/html')

            if auth.should_set_session_cookie:
                _set_session_cookie(response, runtime_app, auth)

        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(runtime_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD' and hasattr(response, 'body'):
            response.body = b''
        return response

    return router


def mount_styleguide_routes(app, runtime_app, **kwargs):
    app.include_router(create_styleguide_router(runtime_app, **kwargs))
    return app
