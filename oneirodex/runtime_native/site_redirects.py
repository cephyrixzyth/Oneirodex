"""Native redirects for public site entry routes."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse, Response

from .request_auth import request_auth_context


def create_site_redirect_router(
    runtime_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    """Preserve `/` and `/index` setup/login/Discover redirect decisions."""
    router = APIRouter()

    @router.api_route('/', methods=['GET', 'HEAD', 'OPTIONS', 'POST'])
    @router.api_route('/index', methods=['GET', 'HEAD', 'OPTIONS', 'POST'])
    def site_entry(request: Request):
        scope = database_scope(runtime_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                runtime_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                allow_bearer=False,
            )
            if request.method == 'OPTIONS':
                from oneirodex.utils.setup import (
                    get_setup_redirect_url,
                    is_setup_in_progress,
                    is_setup_required,
                )

                if is_setup_required() or is_setup_in_progress():
                    from .response_compat import flask_redirect_response

                    response = flask_redirect_response(get_setup_redirect_url())
                else:
                    response = Response(
                        content=b'',
                        status_code=200,
                        media_type='text/html',
                        headers={'Allow': 'OPTIONS, HEAD, POST, GET'},
                    )
            else:
                csrf_response = None
                if request.method == 'POST':
                    from .csrf_compat import csrf_error_response, csrf_html_error_response

                    csrf_response = csrf_error_response(
                        request, auth.session_data, runtime_app.config,
                    )
                if csrf_response is not None:
                    response = csrf_html_error_response(csrf_response)
                else:
                    from oneirodex.utils.setup import (
                        get_setup_redirect_url,
                        is_setup_in_progress,
                        is_setup_required,
                    )

                    if is_setup_required() or is_setup_in_progress():
                        target = get_setup_redirect_url()
                    elif auth.user is None:
                        target = '/login'
                    else:
                        target = '/discover'

                    from .response_compat import flask_redirect_response

                    response = flask_redirect_response(target)
                    if auth.should_set_session_cookie:
                        from .oidc_status import _set_session_cookie

                        _set_session_cookie(response, runtime_app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(runtime_app.config).items():
            response.headers.setdefault(key, value)
        return response

    @router.api_route('/restricted', methods=['GET', 'HEAD'])
    def restricted(request: Request):
        from .acquire_status import _login_redirect, _set_session_cookie
        from oneirodex.utils.security_headers import security_header_values
        from oneirodex.utils.setup import get_setup_redirect_url, should_redirect_to_setup

        scope = database_scope(runtime_app) if database_scope else nullcontext()
        with scope:
            if should_redirect_to_setup():
                from .response_compat import flask_redirect_response

                response = flask_redirect_response(
                    get_setup_redirect_url(), status_code=302,
                )
            else:
                auth = request_auth_context(
                    request,
                    runtime_app.config,
                    find_user=find_user,
                    find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    allow_bearer=False,
                    login_manager=getattr(runtime_app, 'login_manager', None),
                )
                if auth.user is None:
                    response = _login_redirect(
                        runtime_app, request, getattr(runtime_app, 'login_manager', None), auth,
                    )
                else:
                    # The legacy route is the authenticated app entry page. `/welcome`
                    # now means first-run store setup, so sending every legacy visit
                    # there changes the route's purpose. Discover is the current
                    # member landing page and preserves the original entry intent.
                    response = RedirectResponse('/discover', status_code=302)
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, runtime_app, auth)

        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(runtime_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    def compatibility_redirect(request: Request, target: str):
        from .acquire_status import _login_redirect, _set_session_cookie
        from oneirodex.utils.security_headers import security_header_values
        from oneirodex.utils.setup import get_setup_redirect_url, should_redirect_to_setup

        scope = database_scope(runtime_app) if database_scope else nullcontext()
        with scope:
            if should_redirect_to_setup():
                from .response_compat import flask_redirect_response

                response = flask_redirect_response(
                    get_setup_redirect_url(), status_code=302,
                )
            else:
                manager = getattr(runtime_app, 'login_manager', None)
                auth = request_auth_context(
                    request,
                    runtime_app.config,
                    find_user=find_user,
                    find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    allow_bearer=False,
                    login_manager=manager,
                )
                if auth.user is None:
                    response = _login_redirect(runtime_app, request, manager, auth)
                else:
                    response = RedirectResponse(target, status_code=302)
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, runtime_app, auth)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(runtime_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    for path, target in (
        ('/settings_profile_view', '/library?account=profile'),
        ('/settings_password', '/library?account=password'),
        ('/settings_panel', '/library?preferences=1'),
    ):
        def make_handler(redirect_target):
            def handler(request: Request):
                return compatibility_redirect(request, redirect_target)
            return handler

        router.add_api_route(
            path, make_handler(target), methods=['GET', 'HEAD'],
            name=f'compat_redirect_{path.strip("/").replace("/", "_")}',
        )

    return router


def mount_site_redirect_routes(app, runtime_app, **kwargs):
    app.include_router(create_site_redirect_router(runtime_app, **kwargs))
    return app
