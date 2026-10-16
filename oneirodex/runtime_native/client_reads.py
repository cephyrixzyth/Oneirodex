"""Native read-only companion capability and lifecycle APIs."""
from __future__ import annotations

import uuid
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .request_auth import request_auth_context


def api_error(message, *, code='bad_request', status=None, detail=None, **extra):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved_status = api_error_payload(
        message, code=code, status=status, detail=detail, **extra,
    )
    return JSONResponse(payload, status_code=resolved_status), resolved_status


def api_ok(payload=None, *, status=200, **extra):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload, **extra), status_code=status), status


def _from_flask_response(response, status=None):
    if isinstance(response, JSONResponse):
        return response
    return JSONResponse(response, status_code=status or 200)


class ClientReadData:
    """Adapter over the existing capability and lifecycle projections."""

    def capabilities(self, device_kind, token, user):
        from oneirodex.utils.client_capabilities import resolve_client_capabilities

        return resolve_client_capabilities(device_kind, api_token=token, user=user)

    def lifecycle(self, user_id):
        from oneirodex.utils.client_lifecycle import load_lifecycle_map

        mapping = load_lifecycle_map(user_id)
        return {'records': [
            {'game_uuid': game_uuid, 'state': state}
            for game_uuid, state in mapping.items()
        ]}

    def save_lifecycle(self, user_id, records, *, replace=False):
        from oneirodex.utils.client_lifecycle import save_lifecycle_records

        mapping = save_lifecycle_records(user_id, records, replace=replace)
        return {'records': [
            {'game_uuid': game_uuid, 'state': state}
            for game_uuid, state in mapping.items()
        ]}

    def heartbeat(
        self, user_id, device_id, device_kind, device_name, client_version,
        user_agent, token, user,
    ):
        from oneirodex.utils.client_capabilities import (
            normalize_device_kind,
            resolve_client_capabilities,
            should_deliver_install_commands,
        )
        from oneirodex.utils.client_commands import claim_pending_commands
        from oneirodex.utils.client_presence import record_client_heartbeat

        kind = normalize_device_kind(device_kind)
        device = record_client_heartbeat(
            user_id,
            device_id,
            device_kind=kind,
            device_name=device_name,
            client_version=client_version,
            user_agent=user_agent,
        )
        payload = device.to_dict()
        payload.update(resolve_client_capabilities(kind, api_token=token, user=user))
        payload['commands'] = (
            claim_pending_commands(user_id)
            if should_deliver_install_commands(kind, api_token=token, user=user)
            else []
        )
        return payload

    def find_game(self, game_uuid):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(
            select(Game).filter_by(uuid=game_uuid)
        ).scalars().first()

    def can_access_game(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return user_can_access_game(user, game)

    def find_version(self, game, kind, version_uuid):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameExtra, GameUpdate

        model = GameUpdate if kind == 'update' else GameExtra
        return db.session.execute(
            select(model).filter_by(game_uuid=game.uuid, uuid=version_uuid)
        ).scalars().first()

    def enqueue(self, user_id, game_uuid, action, **kwargs):
        from oneirodex.utils.client_commands import enqueue_client_command

        return enqueue_client_command(user_id, game_uuid, action, **kwargs)

    def claim(self, user_id, *, limit=None):
        from oneirodex.utils.client_commands import claim_pending_commands

        return claim_pending_commands(user_id, **({'limit': limit} if limit else {}))

    def acknowledge(self, user_id, ids):
        from oneirodex.utils.client_commands import ack_client_commands

        return ack_client_commands(user_id, ids)

    def negative_acknowledge(self, user_id, ids):
        from oneirodex.utils.client_commands import nack_client_commands

        return nack_client_commands(user_id, ids)


def create_client_reads_router(
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
    data = data_access or ClientReadData()

    def open_database_scope():
        return database_scope(flask_app) if database_scope else nullcontext()

    @router.api_route('/api/client/capabilities', methods=['GET', 'HEAD'])
    def client_capabilities(request: Request):
        with open_database_scope():
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                device_kinds = request.query_params.getlist('device_kind')
                response = JSONResponse(data.capabilities(
                    device_kinds[0] if device_kinds else None, auth.token, auth.user
                ))
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.post('/api/client/heartbeat')
    async def client_heartbeat(request: Request):
        with open_database_scope():
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )

            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not auth.has_scope('write:presence'):
                flask_response, status = api_error(
                    'Missing scope: write:presence', code='forbidden',
                    detail={'required_scope': 'write:presence'},
                )
                response = _from_flask_response(flask_response, status)
            elif auth.token is None:
                csrf_response = csrf_error_response(
                    request, auth.session_data, flask_app.config
                )
                if csrf_response is not None:
                    response = csrf_response
                else:
                    payload = await _heartbeat_payload(
                        request, data, auth.user.id, auth.token, auth.user
                    )
                    from starlette.responses import JSONResponse

                    response = JSONResponse(payload)
                    if auth.should_set_session_cookie:
                        from .oidc_status import _set_session_cookie

                        _set_session_cookie(response, flask_app, auth)
            else:
                payload = await _heartbeat_payload(
                    request, data, auth.user.id, auth.token, auth.user
                )
                from starlette.responses import JSONResponse

                response = JSONResponse(payload)
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.api_route('/api/client/commands', methods=['GET', 'HEAD'])
    def client_commands_get(request: Request):
        with open_database_scope():
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )

            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not auth.has_scope('read:library'):
                flask_response, status = api_error(
                    'Missing scope: read:library', code='forbidden'
                )
                response = _from_flask_response(flask_response, status)
            elif auth.token is None:
                flask_response, status = api_error(
                    'Companion API token required', code='forbidden'
                )
                response = _from_flask_response(flask_response, status)
            else:
                kinds = request.query_params.getlist('device_kind')
                kind = _normalize_device_kind(kinds[0] if kinds else None)
                if not _should_deliver_commands(kind, auth.token, auth.user):
                    from starlette.responses import JSONResponse

                    response = JSONResponse({'commands': []})
                else:
                    raw_limits = request.query_params.getlist('limit')
                    try:
                        limit = int(raw_limits[0]) if raw_limits else 10
                    except (TypeError, ValueError):
                        limit = 10
                    limit = max(1, min(limit or 10, 25))
                    from starlette.responses import JSONResponse

                    response = JSONResponse({
                        'commands': data.claim(auth.user.id, limit=limit)
                    })
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.post('/api/client/commands')
    async def client_commands_post(request: Request):
        with open_database_scope():
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            csrf_response = csrf_error_response(
                request, auth.session_data, flask_app.config
            )
            if csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                body = await _json_body(request)
                game_uuid = _text(body.get('game_uuid'))
                action = _text(body.get('action')).lower()
                kind = body.get('kind')
                version_uuid = _text(body.get('version_uuid')) or None
                open_path = _text(body.get('path')) or None
                select_in_folder = body.get('select')

                from oneirodex.utils.client_commands import WRITE_DOWNLOAD_ACTIONS

                if action in WRITE_DOWNLOAD_ACTIONS and not auth.has_scope('write:download'):
                    flask_response, status = api_error(
                        'Missing scope: write:download', code='forbidden',
                        detail={'required_scope': 'write:download'},
                    )
                    response = _from_flask_response(flask_response, status)
                elif action == 'open_path':
                    from oneirodex.utils.client_commands import open_path_target_authorized
                    from oneirodex.utils.role_catalog import normalize_role

                    admin = (
                        normalize_role(getattr(auth.user, 'role', None) or '') == 'admin'
                        and (auth.token is None or auth.has_scope('admin'))
                    )
                    game = data.find_game(game_uuid) if game_uuid else None
                    if game_uuid and game is None:
                        flask_response, status = api_error('Game not found', code='not_found')
                        response = _from_flask_response(flask_response, status)
                    elif game is not None and not data.can_access_game(auth.user, game):
                        flask_response, status = api_error('Forbidden', code='forbidden')
                        response = _from_flask_response(flask_response, status)
                    elif not game_uuid and not admin:
                        flask_response, status = api_error('Forbidden', code='forbidden')
                        response = _from_flask_response(flask_response, status)
                    elif not open_path_target_authorized(
                        auth.user, game, open_path, admin=admin,
                    ):
                        flask_response, status = api_error('Forbidden', code='forbidden')
                        response = _from_flask_response(flask_response, status)
                    else:
                        try:
                            command = data.enqueue(
                                auth.user.id, game_uuid, action, path=open_path,
                                select=None if select_in_folder is None
                                else bool(select_in_folder),
                            )
                        except ValueError as exc:
                            flask_response, status = api_error(str(exc), code='bad_request')
                            response = _from_flask_response(flask_response, status)
                        else:
                            flask_response, status = api_ok({'command': command}, status=201)
                            response = _from_flask_response(flask_response, status)
                else:
                    game = data.find_game(game_uuid)
                    if game is None:
                        flask_response, status = api_error('Game not found', code='not_found')
                        response = _from_flask_response(flask_response, status)
                    elif not data.can_access_game(auth.user, game):
                        flask_response, status = api_error('Forbidden', code='forbidden')
                        response = _from_flask_response(flask_response, status)
                    else:
                        pack_error = None
                        if kind in ('update', 'extra') and version_uuid:
                            pack = data.find_version(game, kind, version_uuid)
                            if not pack:
                                pack_error = ('Version not found for game', 'not_found')
                            elif action == 'apply_patch' and getattr(
                                pack, 'extra_kind', None
                            ) != 'translation_patch':
                                pack_error = ('Version is not a translation patch', 'bad_request')
                        if pack_error:
                            flask_response, status = api_error(
                                pack_error[0], code=pack_error[1]
                            )
                            response = _from_flask_response(flask_response, status)
                        else:
                            try:
                                command = data.enqueue(
                                    auth.user.id, game_uuid, action, kind=kind,
                                    version_uuid=version_uuid,
                                )
                            except ValueError as exc:
                                flask_response, status = api_error(
                                    str(exc), code='bad_request'
                                )
                                response = _from_flask_response(flask_response, status)
                            else:
                                flask_response, status = api_ok(
                                    {'command': command}, status=201
                                )
                                response = _from_flask_response(flask_response, status)
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.api_route('/api/client/commands/ack', methods=['POST'])
    async def client_commands_ack(request: Request):
        return await _client_command_ack(
            request, flask_app, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, data=data, action='ack',
            database_scope=database_scope,
        )

    @router.api_route('/api/client/commands/nack', methods=['POST'])
    async def client_commands_nack(request: Request):
        return await _client_command_ack(
            request, flask_app, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, data=data, action='nack',
            database_scope=database_scope,
        )

    @router.api_route('/api/client/lifecycle', methods=['GET', 'HEAD'])
    def client_lifecycle(request: Request):
        with open_database_scope():
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not auth.has_scope('read:library'):

                flask_response, status = api_error(
                    'Missing scope: read:library', code='forbidden'
                )
                response = _from_flask_response(flask_response, status)
            else:
                response = JSONResponse(data.lifecycle(auth.user.id))
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.post('/api/client/lifecycle')
    async def client_lifecycle_update(request: Request):
        with open_database_scope():
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )

            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                body, validation_error = await _lifecycle_body(request)
                if validation_error is not None:
                    response = validation_error
                elif auth.source != 'bearer' or auth.token is None:
                    flask_response, status = api_error(
                        'Companion API token required', code='forbidden'
                    )
                    response = _from_flask_response(flask_response, status)
                elif not (
                    auth.has_scope('write:download')
                    or auth.has_scope('write:library')
                ):
                    flask_response, status = api_error(
                        'Missing scope: write:download or write:library', code='forbidden'
                    )
                    response = _from_flask_response(flask_response, status)
                else:
                    try:
                        payload = data.save_lifecycle(
                            auth.user.id, body.records, replace=bool(body.replace)
                        )
                    except ValueError as exc:
                        flask_response, status = api_error(str(exc), code='bad_request')
                        response = _from_flask_response(flask_response, status)
                    else:
                        flask_response, status = api_ok({
                            'count': len(payload['records']),
                            'records': payload['records'],
                        })
                        response = _from_flask_response(flask_response, status)
            _finalize(response, flask_app, request)
            return response

    return router


def mount_client_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_client_reads_router(flask_app, **kwargs))
    return app


def _finalize(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''


async def _lifecycle_body(request: Request):
    import json

    from oneirodex.schemas.client import ClientLifecycleBody

    from oneirodex.utils.validation import format_validation_errors

    try:
        value = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        value = {}
    try:
        return ClientLifecycleBody.model_validate(
            value if isinstance(value, dict) else {}
        ), None
    except ValidationError as exc:
        flask_response, status = api_error(
            'Invalid request.', code='unprocessable',
            detail=format_validation_errors(exc),
        )
        return None, _from_flask_response(flask_response, status)


async def _heartbeat_payload(request: Request, data, user_id: int, token, user):
    import json

    body = await request.body()
    try:
        value = json.loads(body or b'{}')
    except (TypeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        value = {}
    device_id = value.get('device_id')
    device_id = device_id.strip() if isinstance(device_id, str) else ''
    if not device_id:
        device_id = str(uuid.uuid4())
    return data.heartbeat(
        user_id,
        device_id,
        value.get('device_kind'),
        value.get('device_name'),
        value.get('client_version'),
        request.headers.get('User-Agent'),
        token,
        user,
    )


async def _json_body(request: Request) -> dict:
    import json

    try:
        body = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ''


def _normalize_device_kind(value):
    from oneirodex.utils.client_capabilities import normalize_device_kind

    return normalize_device_kind(value)


def _should_deliver_commands(kind, token, user):
    from oneirodex.utils.client_capabilities import should_deliver_install_commands

    return should_deliver_install_commands(kind, api_token=token, user=user)


async def _client_command_ack(
    request, flask_app, *, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, data, action, database_scope=None,
):
    open_database_scope = (
        lambda: database_scope(flask_app) if database_scope else nullcontext()
    )
    with open_database_scope():
        auth = request_auth_context(
            request, flask_app.config,
            find_user=find_user,
            find_token=find_token,
            commit_token_touch=commit_token_touch,
            load_user_id=load_user_id,
            login_manager=login_manager,
        )

        from .oidc_status import _set_session_cookie

        if auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        elif auth.token is None:
            flask_response, status = api_error(
                'Companion API token required', code='forbidden'
            )
            response = _from_flask_response(flask_response, status)
        elif not (
            auth.has_scope('write:download')
            or auth.has_scope('write:library')
        ):
            flask_response, status = api_error(
                'Missing scope: write:download or write:library',
                code='forbidden',
                detail={'required_scope': 'write:download or write:library'},
            )
            response = _from_flask_response(flask_response, status)
        else:
            body = await _json_body(request)
            ids = body.get('ids') if isinstance(body.get('ids'), list) else []
            ids = [str(value) for value in ids]
            count = (
                data.acknowledge(auth.user.id, ids)
                if action == 'ack'
                else data.negative_acknowledge(auth.user.id, ids)
            )
            field = 'removed' if action == 'ack' else 'released'
            flask_response, status = api_ok({field: count})
            response = _from_flask_response(flask_response, status)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)

        _finalize(response, flask_app, request)
        return response
