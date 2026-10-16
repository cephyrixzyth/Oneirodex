"""Native FastAPI handler for per-game health detail."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .acquire_status import _login_redirect
from .request_auth import request_auth_context


class GameHealthData:
    """Adapter around existing game lookup, ACL, and scoring services."""

    def find(self, game_uuid: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

    def can_access(self, user, game) -> bool:
        from oneirodex.utils.library_acl import user_can_access_game

        return user_can_access_game(user, game)

    def score(self, game) -> dict:
        from oneirodex.utils.library_health import score_game

        return score_game(game)


def create_game_health_router(
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
    """Create GET/HEAD detail routes with the original 404/ACL/scoring order."""
    router = APIRouter()
    data = data_access if data_access is not None else GameHealthData()

    @router.api_route('/api/health/games/{game_uuid}', methods=['GET', 'HEAD'])
    def game_health_detail(game_uuid: str, request: Request):
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
                from oneirodex.utils.api_contract import api_error_payload

                game = data.find(game_uuid)
                if not game:
                    payload, status = api_error_payload('Game not found', code='not_found')
                    response = JSONResponse(payload, status_code=status)
                elif not data.can_access(auth.user, game):
                    payload, status = api_error_payload('Forbidden', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                else:
                    response = JSONResponse(data.score(game))

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_game_health_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_game_health_router(flask_app, **kwargs))
    return app
