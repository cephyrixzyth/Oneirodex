"""Native FastAPI handler for the admin library-health summary."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse
from werkzeug.datastructures import MultiDict

from .acquire_status import _login_redirect
from .request_auth import request_auth_context


class LibraryHealthData:
    """Adapter around the existing library-health summary service."""

    def summarize(self, *, limit: int, library_uuid: str | None) -> dict:
        from oneirodex.utils.library_health import summarize_library_health

        return summarize_library_health(limit=limit, library_uuid=library_uuid)


def create_library_health_router(
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
    """Create native GET/HEAD routes preserving Flask query/auth behavior."""
    router = APIRouter()
    data = data_access if data_access is not None else LibraryHealthData()

    @router.api_route('/api/health/library', methods=['GET', 'HEAD'])
    def library_health_summary(request: Request):
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
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.role_catalog import normalize_role

                is_admin = (
                    bool(getattr(auth.user, 'is_authenticated', True))
                    and normalize_role(getattr(auth.user, 'role', None)) == 'admin'
                    and (auth.token is None or auth.has_scope('admin'))
                )
                if not is_admin:
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload('Admin required', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                else:
                    # Flask's request.args is a Werkzeug MultiDict; get() uses
                    # the first duplicate value. Match that when adapting ASGI.
                    args = MultiDict(request.query_params.multi_items())
                    try:
                        limit = min(int(args.get('limit') or 200), 2000)
                    except (TypeError, ValueError):
                        limit = 200
                    library_uuid = (args.get('library_uuid') or '').strip() or None
                    response = JSONResponse(
                        data.summarize(limit=limit, library_uuid=library_uuid)
                    )

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_library_health_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_library_health_router(flask_app, **kwargs))
    return app


