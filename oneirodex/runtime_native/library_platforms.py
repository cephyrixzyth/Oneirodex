"""Native FastAPI handler for admin library-platform options."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from fastapi import APIRouter, FastAPI, Request
from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class LibraryPlatformsData:
    """Adapter for the shared LibraryPlatform enum values."""

    def platforms(self) -> Iterable[Any]:
        from oneirodex.models import LibraryPlatform

        return LibraryPlatform


def create_library_platforms_router(
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
    """Create native GET/HEAD route matching the ``admin2`` Flask contract."""
    router = APIRouter()
    data = data_access or LibraryPlatformsData()

    @router.api_route('/api/admin/library_platforms', methods=['GET', 'HEAD'])
    def library_platform_options(request: Request):
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
            user = auth.user
            if user is None:
                response = _anonymous_login_redirect(
                    flask_app, request, login_manager, auth
                )
            else:
                from oneirodex.utils.role_catalog import normalize_role

                is_admin = (
                    bool(getattr(user, 'is_authenticated', True))
                    and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                )
                if is_admin and auth.token is not None and not auth.has_scope('admin'):
                    from oneirodex.utils.api_contract import api_error_payload
                    from starlette.responses import JSONResponse

                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif not is_admin:
                    response = _admin_denied_redirect(flask_app, request, auth)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload
                    from starlette.responses import JSONResponse

                    payload = {
                        'platforms': [
                            {'key': platform.name, 'label': platform.value}
                            for platform in data.platforms()
                        ]
                    }
                    response = JSONResponse(api_ok_payload(payload))

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_library_platforms_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_library_platforms_router(flask_app, **kwargs))
    return app


def _anonymous_login_redirect(flask_app, request, login_manager, auth_context):
    """Use Flask-Login's ``admin2`` blueprint login view before generic fallback."""
    configured = getattr(login_manager, 'blueprint_login_views', {}) or {}
    view = configured.get('admin2') or getattr(login_manager, 'login_view', None)
    compatible_manager = SimpleNamespace(
        login_view=view,
        blueprint_login_views={'apis': view} if view else {},
        login_message=getattr(login_manager, 'login_message', None),
        login_message_category=getattr(login_manager, 'login_message_category', 'message'),
        localize_callback=getattr(login_manager, 'localize_callback', None),
    )
    return _login_redirect(
        flask_app,
        request,
        compatible_manager,
        auth_context,
        message=compatible_manager.login_message,
        category=compatible_manager.login_message_category,
        include_next=True,
    )


def _admin_denied_redirect(flask_app, request, auth_context):
    """Match admin_required's fixed login endpoint and danger flash."""
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={'apis': 'login.login'},
        login_message=None,
        login_message_category='danger',
        localize_callback=None,
    )
    return _login_redirect(
        flask_app,
        request,
        manager,
        auth_context,
        message='You must be an admin to access this page.',
        category='danger',
        include_next=False,
    )
