"""Native FastAPI handler for member-safe remote-play status."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from .acquire_status import _login_redirect
from .request_auth import request_auth_context


class RemotePlayStatusData:
    """Adapter around the existing member-safe status projection."""

    def status(self, *, config=None) -> dict:
        from oneirodex.utils.remote_play import member_remote_play_status

        return member_remote_play_status(config=config)


def create_remote_play_status_router(
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
    """Build native GET/HEAD routes using shared Flask-compatible auth."""
    router = APIRouter()
    data = data_access or RemotePlayStatusData()

    @router.api_route('/api/remote-play/status', methods=['GET', 'HEAD'])
    def remote_play_status(request: Request):
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
                from starlette.responses import JSONResponse

                response = JSONResponse(data.status(config=flask_app.config))

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_remote_play_status_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_remote_play_status_router(flask_app, **kwargs))
    return app
