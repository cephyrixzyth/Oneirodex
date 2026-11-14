"""Native redirect for browser-playable game requests."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, Request

from .response_compat import flask_redirect_response
from .request_auth import request_auth_context


def create_play_redirect_router(
    runtime_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.api_route('/play_game/{game_uuid}', methods=['GET', 'HEAD'])
    def play_game(request: Request, game_uuid: str):
        from .acquire_status import _login_redirect, _set_session_cookie
        from oneirodex.models import Game
        from oneirodex.runtime_native.db_session import native_db
        from oneirodex.utils.library_acl import user_can_access_game
        from oneirodex.utils.play_url import browse_play_fields
        from oneirodex.utils.security_headers import security_header_values
        from sqlalchemy import select

        scope = database_scope(runtime_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                runtime_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                login_manager=getattr(runtime_app, 'login_manager', None),
            )
            if auth.user is None:
                response = _login_redirect(
                    runtime_app, request, getattr(runtime_app, 'login_manager', None), auth,
                )
            else:
                game = native_db.session.execute(
                    select(Game).filter_by(uuid=game_uuid)
                ).scalars().first()
                target = '/library'
                if game is None:
                    message, category = 'Game not found.', 'error'
                elif not user_can_access_game(auth.user, game):
                    message, category = 'You do not have access to this game.', 'error'
                else:
                    fields = browse_play_fields(game)
                    play_url = fields.get('play_url')
                    if fields.get('can_play_in_browser') and play_url:
                        target = play_url
                        message = category = None
                    else:
                        target = f'/game_details/{game_uuid}'
                        message = (
                            'This title is not playable in the browser. '
                            'Open details for download/install.'
                        )
                        category = 'info'
                if message:
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append((category, message))
                    auth.session_data['_flashes'] = flashes
                response = flask_redirect_response(target, status_code=302)

            if auth.should_set_session_cookie or auth.session_data.get('_flashes'):
                _set_session_cookie(response, runtime_app, auth)

        for key, value in security_header_values(runtime_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_play_redirect_routes(app, runtime_app, **kwargs):
    app.include_router(create_play_redirect_router(runtime_app, **kwargs))
    return app
