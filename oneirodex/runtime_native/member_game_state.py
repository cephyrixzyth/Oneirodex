"""Native member favorite and play-status actions for a single game."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request

from .acquire_status import _login_redirect
from .batch_favorite import _finish
from .request_auth import request_auth_context

_UNSUPPORTED_JSON_CONTENT_TYPE = object()


class MemberGameStateData:
    def game(self, uuid):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(select(Game).filter_by(uuid=uuid)).scalars().first()

    def can_access(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return bool(user_can_access_game(user, game))

    def is_favorite(self, user, game):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import user_favorites

        return db.session.execute(
            select(user_favorites.c.game_uuid).where(
                user_favorites.c.user_id == user.id,
                user_favorites.c.game_uuid == game.uuid,
            )
        ).first() is not None

    def set_favorite(self, user, game, favorite):
        if favorite:
            user.favorites.append(game)
        else:
            user.favorites.remove(game)

    def status(self, user_id, game_uuid):
        from sqlalchemy import and_, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import user_game_status

        row = db.session.execute(
            select(user_game_status.c.status).where(and_(
                user_game_status.c.user_id == user_id,
                user_game_status.c.game_uuid == game_uuid,
            ))
        ).first()
        return row[0] if row else None

    def write_status(self, user_id, game_uuid, status):
        from sqlalchemy import and_, delete, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import user_game_status

        condition = and_(
            user_game_status.c.user_id == user_id,
            user_game_status.c.game_uuid == game_uuid,
        )
        existing = db.session.execute(select(user_game_status).where(condition)).first()
        if not status:
            db.session.execute(delete(user_game_status).where(condition))
        elif existing:
            db.session.execute(
                user_game_status.update().where(condition).values(
                    status=status, updated_at=datetime.now(timezone.utc),
                )
            )
        else:
            db.session.execute(user_game_status.insert().values(
                user_id=user_id, game_uuid=game_uuid,
                status=status, updated_at=datetime.now(timezone.utc),
            ))

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()


def create_member_game_state_router(
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
    data = data_access or MemberGameStateData()

    def open_database_scope():
        return database_scope(flask_app) if database_scope else nullcontext()

    async def authorize(request: Request, *, write: bool):
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
        )
        response = None
        if write and auth.token is not None and not auth.has_scope('write:library'):
            response = _api_error('Forbidden', 'forbidden')
        if write and auth.token is None:
            from .csrf_compat import csrf_error_response

            if response is None:
                response = csrf_error_response(request, auth.session_data, flask_app.config)
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        return auth, response

    @router.api_route('/api/check_favorite/{game_uuid}', methods=['GET', 'HEAD'])
    async def check_favorite(request: Request, game_uuid: str):
        with open_database_scope():
            auth, response = await authorize(request, write=False)
            if response is None:
                game = data.game(game_uuid)
                if game is None:
                    response = _api_error('Game not found', 'not_found')
                elif not data.can_access(auth.user, game):
                    response = _api_error('Forbidden', 'forbidden')
                else:
                    from starlette.responses import JSONResponse

                    response = JSONResponse({'is_favorite': data.is_favorite(auth.user, game)})
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/toggle_favorite/{game_uuid}')
    async def toggle_favorite(request: Request, game_uuid: str):
        with open_database_scope():
            auth, response = await authorize(request, write=True)
            if response is None:
                game = data.game(game_uuid)
                if game is None:
                    response = _api_error('Game not found', 'not_found')
                elif not data.can_access(auth.user, game):
                    response = _api_error('Forbidden', 'forbidden')
                else:
                    from starlette.responses import JSONResponse

                    favorite = not data.is_favorite(auth.user, game)
                    data.set_favorite(auth.user, game, favorite)
                    data.commit()
                    from oneirodex.utils.api_contract import api_ok_payload
                    from starlette.responses import JSONResponse

                    response = JSONResponse(api_ok_payload({'is_favorite': favorite}))
            _finish(response, flask_app, auth)
            return response

    @router.api_route('/api/get_game_status/{game_uuid}', methods=['GET', 'HEAD'])
    async def get_game_status(request: Request, game_uuid: str):
        with open_database_scope():
            auth, response = await authorize(request, write=False)
            if response is None:
                game = data.game(game_uuid)
                if game is None or not data.can_access(auth.user, game):
                    response = _api_error('Game not found', 'not_found')
                else:
                    from oneirodex.models import get_status_info
                    from oneirodex.utils.api_contract import api_ok_payload
                    from starlette.responses import JSONResponse

                    status = data.status(auth.user.id, game_uuid)
                    response = JSONResponse(api_ok_payload({
                        'status': status, 'status_info': get_status_info(status),
                    }))
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/set_game_status/{game_uuid}')
    async def set_game_status(request: Request, game_uuid: str):
        with open_database_scope():
            auth, response = await authorize(request, write=True)
            if response is None:
                game = data.game(game_uuid)
                if game is None or not data.can_access(auth.user, game):
                    response = _api_error('Game not found', 'not_found')
                else:
                    payload = await _json_payload(request)
                    if payload is _UNSUPPORTED_JSON_CONTENT_TYPE:
                        response = _api_error(
                            "Did not attempt to load JSON data because the request Content-Type was not 'application/json'.",
                            'bad_request', status=415,
                        )
                    elif not isinstance(payload, dict):
                        # Match the legacy handler's generic 500 when JSON is
                        # valid but its top-level value cannot provide .get().
                        response = _api_error(
                            'Something went wrong on our end. The error has been logged.',
                            'internal',
                        )
                    else:
                        # The v1.1.8 contract treats an omitted status as an
                        # empty value, which clears the saved status.
                        raw_status = payload.get('status', '')
                        if not isinstance(raw_status, str):
                            # Legacy calls .strip() directly and its global
                            # error handler returns this generic internal error.
                            response = _api_error(
                                'Something went wrong on our end. The error has been logged.',
                                'internal',
                            )
                        else:
                            status = raw_status.strip()
                            from oneirodex.models import get_status_info
                            from oneirodex.utils.api_contract import api_ok_payload
                            from starlette.responses import JSONResponse
                            from oneirodex.utils.play_status import PLAY_STATUS_VALUES

                            if status not in sorted(PLAY_STATUS_VALUES):
                                response = _api_error('Invalid status value', 'bad_request')
                            else:
                                data.write_status(auth.user.id, game_uuid, status)
                                data.commit()
                                status_out = status or None
                                info = get_status_info(status_out)
                                message = (
                                    'Status cleared' if not status
                                    else f'Status updated to {info["label"]}'
                                )
                                response = JSONResponse(api_ok_payload({
                                    'status': status_out, 'status_info': info,
                                    'message': message,
                                }))
            _finish(response, flask_app, auth)
            return response

    return router


def mount_member_game_state_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_member_game_state_router(flask_app, **kwargs))
    return app


async def _json_payload(request):
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' and not (
            content_type.startswith('application/') and content_type.endswith('+json')
        ):
            return _UNSUPPORTED_JSON_CONTENT_TYPE
        payload = await request.json()
        return payload
    except Exception:  # noqa: BLE001 — match Flask silent JSON handling
        return {}


def _api_error(message, code, *, status=None):
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    payload, resolved_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=resolved_status)

