"""Native FastAPI play-session lifecycle and member playtime reads."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class PlaytimeData:
    uses_explicit_app = True

    flask_app = None

    def start(self, user, body):
        from oneirodex.utils.playtime import start_session

        return start_session(
            user.id, body.game_uuid, client=body.client,
            config=self.flask_app.config if self.flask_app is not None else None,
        )

    def session(self, user, session_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import PlaySession

        row = db.session.get(PlaySession, session_id)
        return row if row is not None and row.user_id == user.id else None

    def heartbeat(self, session):
        from oneirodex.utils.playtime import heartbeat_session

        return heartbeat_session(session)

    def stop(self, session):
        from oneirodex.utils.playtime import end_session

        return end_session(
            session,
            config=self.flask_app.config if self.flask_app is not None else None,
        )

    def me(self, user):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, UserGameProgress
        from oneirodex.utils.library_acl import user_can_access_game

        rows = db.session.execute(
            select(UserGameProgress)
            .filter_by(user_id=user.id)
            .order_by(UserGameProgress.last_played_at.desc())
            .limit(100)
        ).scalars().all()
        game_uuids = [row.game_uuid for row in rows]
        games_by_uuid = {}
        if game_uuids:
            games = db.session.execute(
                select(Game).filter(Game.uuid.in_(game_uuids))
            ).scalars().all()
            games_by_uuid = {game.uuid: game for game in games}
        visible = [
            row for row in rows
            if row.game_uuid in games_by_uuid
            and user_can_access_game(user, games_by_uuid[row.game_uuid])
        ]
        games = []
        for row in visible:
            payload = row.to_dict()
            payload['game_name'] = games_by_uuid[row.game_uuid].name
            games.append(payload)
        return {
            'total_seconds': sum(int(row.total_seconds or 0) for row in visible),
            'games': games,
        }

    def game(self, user, game_uuid: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, UserGameProgress
        from oneirodex.utils.library_acl import user_can_access_game

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if game is None or not user_can_access_game(user, game):
            return None, None
        row = db.session.execute(
            select(UserGameProgress).filter_by(user_id=user.id, game_uuid=game_uuid)
        ).scalars().first()
        if row is None:
            return None, {
                'user_id': user.id,
                'game_uuid': game_uuid,
                'total_seconds': 0,
                'session_count': 0,
                'last_played_at': None,
            }
        return row, row.to_dict()

    def share_svg(self, user, game_uuid: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, UserGameProgress
        from oneirodex.utils.library_acl import user_can_access_game
        from oneirodex.utils.stats_share import build_playtime_share_svg

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if game is None:
            return None, ('Game not found', 'not_found')
        if not user_can_access_game(user, game):
            return None, ('Forbidden', 'forbidden')
        row = db.session.execute(
            select(UserGameProgress).filter_by(user_id=user.id, game_uuid=game_uuid),
        ).scalars().first()
        svg = build_playtime_share_svg(
            username=user.name,
            game_name=game.name,
            total_seconds=int(row.total_seconds) if row else 0,
            session_count=int(row.session_count) if row else 0,
        )
        return svg, None


def create_playtime_router(
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
    data = data_access or PlaytimeData()
    if getattr(data, 'uses_explicit_app', False):
        data.flask_app = flask_app

    @router.post('/api/playtime/sessions')
    async def start_session(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None:
                response = _write_scope_error(auth)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                try:
                    from oneirodex.schemas.playtime import StartPlaytimeSessionBody
                    from oneirodex.utils.validation import format_validation_errors

                    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                    is_json = content_type == 'application/json' or (
                        content_type.startswith('application/') and content_type.endswith('+json')
                    )
                    payload = await request.json() if is_json else {}
                    if not isinstance(payload, dict):
                        payload = {}
                    body = StartPlaytimeSessionBody.model_validate(payload)
                except ValidationError as exc:
                    response = _api_error(
                        'Invalid request.', 'unprocessable',
                        detail=format_validation_errors(exc),
                    )
                except Exception:  # noqa: BLE001 — malformed/missing JSON is an empty body
                    from oneirodex.schemas.playtime import StartPlaytimeSessionBody
                    from oneirodex.utils.validation import format_validation_errors

                    try:
                        body = StartPlaytimeSessionBody.model_validate({})
                    except ValidationError as exc:
                        response = _api_error(
                            'Invalid request.', 'unprocessable',
                            detail=format_validation_errors(exc),
                        )
                if response is None:
                    try:
                        session = data.start(auth.user, body)
                        response = _json_response(flask_app, session.to_dict(), status=201)
                    except PermissionError:
                        response = _api_error('Forbidden', 'forbidden')
                    except ValueError as exc:
                        response = _api_error(str(exc), 'not_found')
            _finish(response, flask_app, auth)
            return response

    @router.post('/api/playtime/sessions/{session_id:int}/heartbeat')
    def heartbeat_session(session_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None:
                response = _write_scope_error(auth)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                session = data.session(auth.user, session_id)
                if session is None:
                    response = _api_error('Session not found', 'not_found')
                else:
                    try:
                        session = data.heartbeat(session)
                        response = _json_response(flask_app, session.to_dict())
                    except ValueError as exc:
                        response = _api_error(str(exc), 'bad_request')
            _finish(response, flask_app, auth)
            return response

    @router.post('/api/playtime/sessions/{session_id:int}/stop')
    def stop_session(session_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf(request, auth, flask_app)
            if response is None:
                response = _write_scope_error(auth)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                session = data.session(auth.user, session_id)
                if session is None:
                    response = _api_error('Session not found', 'not_found')
                else:
                    response = _json_response(flask_app, data.stop(session).to_dict())
            _finish(response, flask_app, auth)
            return response

    @router.api_route('/api/playtime/me', methods=['GET', 'HEAD'])
    def playtime_me(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                response = _json_response(flask_app, data.me(auth.user))
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/playtime/games/{game_uuid}', methods=['GET', 'HEAD'])
    def playtime_game(game_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                _row, payload = data.game(auth.user, game_uuid)
                response = (
                    _api_error('Forbidden', 'forbidden')
                    if payload is None else _json_response(flask_app, payload)
                )
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/playtime/share/{game_uuid}.svg', methods=['GET', 'HEAD'])
    def playtime_share_card(game_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                svg, error = data.share_svg(auth.user, game_uuid)
                response = (
                    _api_error(error[0], error[1]) if error
                    else Response(content=svg, media_type='image/svg+xml')
                )
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_playtime_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_playtime_router(flask_app, **kwargs))
    return app


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _csrf(request, auth, flask_app):
    if auth.token is not None:
        return None
    from .csrf_compat import csrf_error_response

    return csrf_error_response(request, auth.session_data, flask_app.config)


def _write_scope_error(auth):
    if auth.token is not None and not auth.has_scope('write:library'):
        return _api_error('Missing scope: write:library', 'forbidden')
    return None


def _api_error(message, code, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, detail=detail)
    return JSONResponse(payload, status_code=status)


def _json_response(flask_app, payload, *, status=200):
    from starlette.responses import Response

    response = flask_app.json.response(payload)
    return Response(content=response.get_data(), status_code=status,
                    headers={'Content-Type': response.headers.get('Content-Type', 'application/json')})


def _finish(response, flask_app, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
