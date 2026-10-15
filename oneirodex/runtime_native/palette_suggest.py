"""Native member command-palette suggestions."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import Response

from .acquire_status import _login_redirect
from .request_auth import request_auth_context


class PaletteSuggestData:
    def suggest(self, user, limit: int) -> dict:
        from oneirodex.utils.palette_suggest import palette_suggest

        return palette_suggest(user, limit=limit)


def create_palette_suggest_router(
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
    data = data_access or PaletteSuggestData()

    @router.api_route('/api/palette/suggest', methods=['GET', 'HEAD'])
    def palette_suggest(request: Request):
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
                from oneirodex.utils.api_contract import api_ok_payload
                from oneirodex.utils.palette_suggest import clamp_suggest_limit
                from starlette.responses import JSONResponse

                limit = clamp_suggest_limit(request.query_params.get('limit'))
                response = JSONResponse(api_ok_payload(data.suggest(auth.user, limit)))

        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_palette_suggest_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_palette_suggest_router(flask_app, **kwargs))
    return app
