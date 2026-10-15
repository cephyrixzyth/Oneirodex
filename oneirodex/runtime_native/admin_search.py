"""Native admin-only library game search for Identify workflows."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class AdminGameSearchData:
    def search(self, query: str) -> list[dict]:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.admin_search import GAMES_SEARCH_RESULT_LIMIT

        games = db.session.execute(
            select(Game)
            .filter(Game.name.ilike(f'%{query}%'))
            .order_by(Game.name)
            .limit(GAMES_SEARCH_RESULT_LIMIT)
        ).scalars().all()
        return [
            {'uuid': game.uuid, 'name': game.name, 'full_disk_path': game.full_disk_path}
            for game in games
        ]


def create_admin_search_router(
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
    data = data_access or AdminGameSearchData()

    @router.api_route('/api/admin/games_search', methods=['GET', 'HEAD'])
    def admin_games_search(request: Request):
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
            from oneirodex.utils.api_contract import api_error_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user
            is_admin = (
                user is not None
                and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if user is None:
                response = _login_redirect(
                    flask_app,
                    request,
                    login_manager,
                    auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            elif not is_admin:
                response = _login_redirect(
                    flask_app,
                    request,
                    login_manager,
                    auth,
                    message='You must be an admin to access this page.',
                    category='danger',
                    include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden'
                )
                response = JSONResponse(payload, status_code=status)
            else:
                query = request.query_params.get('q', '').strip()
                if not query:
                    response = JSONResponse([])
                elif len(query) > 100:
                    payload, status = api_error_payload(
                        'Search term too long', code='bad_request'
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    response = JSONResponse(data.search(query))

        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_admin_search_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_search_router(flask_app, **kwargs))
    return app
