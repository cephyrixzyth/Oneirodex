"""Native admin read for HowLongToBeat data coverage."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class HltbStatsData:
    """Build the stable coverage payload using the active ORM session."""

    def read(self) -> dict[str, int | float]:
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        total_games = db.session.execute(select(func.count(Game.id))).scalar() or 0
        games_with_hltb = db.session.execute(
            select(func.count(Game.id)).where(Game.hltb_id.isnot(None))
        ).scalar() or 0
        coverage_percentage = games_with_hltb / total_games * 100 if total_games else 0
        return {
            'total_games': total_games,
            'games_with_hltb': games_with_hltb,
            'games_without_hltb': total_games - games_with_hltb,
            'coverage_percentage': round(coverage_percentage, 2),
        }


def create_hltb_stats_router(
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
    data = data_access or HltbStatsData()

    @router.api_route('/api/hltb/stats', methods=['GET', 'HEAD'])
    def hltb_stats(request: Request):
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
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
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
                response = JSONResponse(api_ok_payload({'stats': data.read()}))

        from oneirodex.utils.security_headers import security_header_values

        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_hltb_stats_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_hltb_stats_router(flask_app, **kwargs))
    return app
