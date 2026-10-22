"""Native FastAPI routes for the household game-server registry."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .request_auth import request_auth_context


class GameServersData:
    """Lazy ORM and probe adapter; tests replace it with an in-memory fake."""

    def list_servers(self):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameServer

        return db.session.execute(
            select(GameServer).order_by(GameServer.display_name.asc())
        ).scalars().all()

    def get_server(self, server_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameServer

        return db.session.execute(
            select(GameServer).filter_by(uuid=server_uuid)
        ).scalars().first()

    def game_exists(self, game_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(
            select(Game).filter_by(uuid=game_uuid)
        ).scalars().first() is not None

    def create_server(self, **values):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameServer

        server = GameServer(**values)
        db.session.add(server)
        db.session.commit()
        # Match Flask-SQLAlchemy's post-commit behavior: the legacy session
        # expires the instance and reloads database values before serialization.
        # Native sessions deliberately keep instances alive across commit, so
        # refresh here to avoid returning an aware timestamp only on create.
        db.session.refresh(server)
        return server

    def save_server(self, server):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def delete_server(self, server):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.delete(server)
        db.session.commit()

    def probe(self, connect_string, health_url):
        from oneirodex.utils.game_servers import probe_server_health

        return probe_server_health(connect_string, health_url)

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_game_servers_router(
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
    """Create member-read/admin-write routes with Flask-compatible identity."""
    router = APIRouter()
    data = data_access if data_access is not None else GameServersData()

    @router.api_route('/api/game-servers', methods=['GET', 'POST', 'HEAD'])
    async def game_servers(request: Request):
        return await _dispatch(
            request, flask_app, data, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    @router.api_route('/api/game-servers/acl-check', methods=['GET', 'HEAD'])
    async def game_servers_acl(request: Request):
        return await _dispatch(
            request, flask_app, data, acl=True, find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope,
        )

    @router.api_route(
        '/api/game-servers/{server_uuid:str}',
        methods=['GET', 'PUT', 'PATCH', 'DELETE', 'HEAD'],
    )
    async def game_server(server_uuid: str, request: Request):
        return await _dispatch(
            request, flask_app, data, server_uuid=server_uuid,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    @router.api_route('/api/game-servers/{server_uuid:str}/status', methods=['GET', 'HEAD'])
    async def game_server_status(server_uuid: str, request: Request):
        return await _dispatch(
            request, flask_app, data, server_uuid=server_uuid, status=True,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    return router


def mount_game_servers_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_game_servers_router(flask_app, **kwargs))
    return app


async def _dispatch(
    request, flask_app, data, *, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, database_scope, server_uuid=None,
    status=False, acl=False,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        method = request.method
        if method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            from .csrf_compat import csrf_error_response

            response = csrf_error_response(request, auth.session_data, flask_app.config)
        else:
            response = None
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        elif response is None and method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            if not _is_admin(auth.user):
                response = _error(403, 'forbidden', 'Admin required')
            elif auth.token is not None and not auth.has_scope('admin'):
                response = _error(403, 'forbidden', 'Admin required')
            else:
                response = await _write_request(request, flask_app, data, method, server_uuid)
        elif response is None and acl:
            response = JSONResponse(_acl_payload(auth.user, auth))
        elif response is None:
            server = data.get_server(server_uuid) if server_uuid is not None else None
            if server_uuid is not None and server is None:
                response = _error(404, 'not_found', 'Not found')
            elif method in ('GET', 'HEAD') and status:
                health = data.probe(server.connect_string, server.health_url)
                response = JSONResponse({
                    'uuid': server.uuid,
                    'display_name': server.display_name,
                    **health,
                })
            elif method in ('GET', 'HEAD') and server_uuid is not None:
                response = JSONResponse(server.to_dict(admin=_is_admin(auth.user, auth)))
            elif method in ('GET', 'HEAD'):
                admin_view = _is_admin(auth.user, auth)
                response = JSONResponse({
                    'servers': [row.to_dict(admin=admin_view) for row in data.list_servers()],
                })
            else:
                response = _error(404, 'not_found', 'Not found')
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _write_request(request, flask_app, data, method, server_uuid):
    from oneirodex.schemas.game_servers import CreateGameServerBody
    from oneirodex.utils.validation import format_validation_errors

    if method == 'POST':
        body, malformed = await _json_body(request)
        if malformed:
            return _error(422, 'unprocessable', 'Invalid request.', detail={'__root__': 'Invalid JSON format'})
        try:
            parsed = CreateGameServerBody.model_validate(body)
        except ValidationError as exc:
            return _error(422, 'unprocessable', 'Invalid request.', detail=format_validation_errors(exc))
        game_uuid = (parsed.game_uuid or '').strip() or None
        if game_uuid and not data.game_exists(game_uuid):
            return _error(400, 'bad_request', 'Game not found')
        try:
            server = data.create_server(
                display_name=parsed.display_name,
                connect_string=parsed.connect_string,
                game_uuid=game_uuid,
                health_url=(parsed.health_url or '').strip() or None,
                compose_project=(parsed.compose_project or '').strip() or None,
                container_id=(parsed.container_id or '').strip() or None,
                invite_note=(parsed.invite_note or '').strip() or None,
            )
        except Exception:
            data.rollback()
            return _error(500, 'internal', 'An error occurred while processing your request')
        return JSONResponse(server.to_dict(admin=True), status_code=201)

    server = data.get_server(server_uuid)
    if server is None:
        return _error(404, 'not_found', 'Not found')
    if method == 'DELETE':
        try:
            data.delete_server(server)
        except Exception:
            data.rollback()
            return _error(500, 'internal', 'An error occurred while processing your request')
        from oneirodex.utils.api_contract import api_ok_payload

        return JSONResponse(api_ok_payload({'uuid': server_uuid}))

    body, malformed = await _json_body(request)
    if malformed or not isinstance(body, dict):
        body = {}
    if 'display_name' in body:
        value = _trimmed_string(body.get('display_name'))
        if not value:
            return _error(400, 'bad_request', 'display_name cannot be empty')
        server.display_name = value
    if 'connect_string' in body:
        value = _trimmed_string(body.get('connect_string'))
        if not value:
            return _error(400, 'bad_request', 'connect_string cannot be empty')
        server.connect_string = value
    if 'game_uuid' in body:
        game_uuid = _trimmed_string(body.get('game_uuid')) or None
        if game_uuid and not data.game_exists(game_uuid):
            return _error(400, 'bad_request', 'Game not found')
        server.game_uuid = game_uuid
    for field in ('health_url', 'compose_project', 'container_id', 'invite_note'):
        if field in body:
            setattr(server, field, _trimmed_string(body.get(field)) or None)
    try:
        data.save_server(server)
    except Exception:
        data.rollback()
        return _error(500, 'internal', 'An error occurred while processing your request')
    return JSONResponse(server.to_dict(admin=True))


async def _json_body(request):
    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type != 'application/json' and not (
        content_type.startswith('application/') and content_type.endswith('+json')
    ):
        return {}, False
    try:
        value = await request.json()
    except Exception:
        return {}, True
    return value if isinstance(value, dict) else {}, not isinstance(value, dict)


def _trimmed_string(value):
    return value.strip() if isinstance(value, str) else ''


def _acl_payload(user, auth=None):
    from oneirodex.utils.role_catalog import normalize_role

    role = normalize_role(getattr(user, 'role', None))
    return {
        'role': role,
        'can_manage': _is_admin(user, auth),
        'can_read': True,
        'read_only': role == 'child',
    }


def _is_admin(user, auth=None):
    from oneirodex.utils.role_catalog import normalize_role

    return bool(
        user is not None
        and getattr(user, 'is_authenticated', True)
        and normalize_role(getattr(user, 'role', None) or '') == 'admin'
        and (auth is None or auth.token is None or auth.has_scope('admin'))
    )


def _error(status, code, message, **fields):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, **fields)
    return JSONResponse(payload, status_code=resolved)


def _login_redirect(flask_app, request, login_manager, auth):
    from .acquire_status import _login_redirect as login_redirect

    return login_redirect(flask_app, request, login_manager, auth)


def _finish(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
