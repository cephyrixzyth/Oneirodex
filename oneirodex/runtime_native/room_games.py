"""Native, authenticated progress API for original library-room games."""
from contextlib import nullcontext
from functools import partial
import json

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from oneirodex.schemas.room_games import (
    IMPLEMENTED_ROOM_GAMES, MAX_PROGRESS_BODY, RoomGameDeleteBody, RoomGameSaveBody,
)
from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
from .bounded_request_body import BODY_TOO_LARGE, read_bounded_body
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context, require_bearer_scope
from .room_game_store import RoomGameProgressData, RoomProgressConflict, RoomProgressUnavailable


def _error(message, code):
    body, status = api_error_payload(message, code=code)
    return JSONResponse(body, status_code=status)


def create_room_games_router(
    flask_app, *, find_user, find_token, commit_token_touch, load_user_id=None,
    login_manager=None, data_access=None, database_scope=None,
):
    router = APIRouter()
    data = data_access or RoomGameProgressData()

    @router.api_route('/api/room-games/{game_id}/progress', methods=['GET', 'HEAD', 'PUT', 'DELETE'])
    async def progress(request: Request, game_id: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            # Sign-in and progress storage query the database synchronously.
            # Run them on the threadpool so a slow query never stalls this
            # worker's event loop; the request's session context is copied.
            auth = await run_in_threadpool(partial(
                request_auth_context,
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            ))
            response = None
            mutating = request.method in ('PUT', 'DELETE')
            if auth.user is None:
                response = _error('Sign in to access your game progress.', 'unauthorized')
            else:
                response = require_bearer_scope(auth, 'write:library' if mutating else 'read:library')
                if response is None and mutating and auth.token is None:
                    response = csrf_error_response(request, auth.session_data, flask_app.config)
                if response is None and game_id not in IMPLEMENTED_ROOM_GAMES:
                    response = _error('This room game is not available.', 'not_found')
            if response is None:
                try:
                    if not mutating:
                        response = JSONResponse(api_ok_payload(
                            await run_in_threadpool(data.read, auth.user, game_id)))
                    elif request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                        response = _error('Send game progress as application/json.', 'bad_request')
                    else:
                        raw = await read_bounded_body(request, MAX_PROGRESS_BODY)
                        if raw is BODY_TOO_LARGE:
                            response = _error('Game progress is too large.', 'payload_too_large')
                        else:
                            try:
                                value = json.loads(raw)
                                body = (RoomGameSaveBody if request.method == 'PUT' else RoomGameDeleteBody).model_validate(value)
                            except (ValidationError, TypeError, ValueError, UnicodeDecodeError):
                                response = _error('This game save is unsupported or invalid.', 'unprocessable')
                            else:
                                state = body.state.model_dump() if isinstance(body, RoomGameSaveBody) else None
                                result = await run_in_threadpool(data.write, auth.user, game_id, body.revision, state)
                                response = JSONResponse(api_ok_payload(result))
                except RoomProgressConflict:
                    response = _error('Your saved game changed elsewhere. Reload it before saving again.', 'conflict')
                except RoomProgressUnavailable:
                    response = _error('Game progress could not be saved or loaded. Try again.', 'unavailable')
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for name, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(name, value)
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['Vary'] = 'Cookie, Authorization'
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_room_games_routes(app, flask_app, **kwargs):
    app.include_router(create_room_games_router(flask_app, **kwargs))
    return app
