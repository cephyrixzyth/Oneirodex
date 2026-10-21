"""Native FastAPI routes for the member wanted-update list."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class WantedUpdateData:
    uses_explicit_app = True

    flask_app = None

    def list(self, user_id: int):
        from oneirodex.utils.wanted_updates import list_wanted

        return list_wanted(user_id, app=self.flask_app)

    def add(self, user_id: int, body):
        from oneirodex.utils.wanted_updates import add_wanted

        return add_wanted(
            user_id, game_uuid=body.game_uuid,
            kind=body.kind or 'update', label=body.label,
            store=body.store, store_id=body.store_id, app=self.flask_app,
        )

    def fulfill(self, user_id: int, body) -> int:
        from oneirodex.utils.wanted_updates import mark_fulfilled

        return mark_fulfilled(
            user_id, body.game_uuid, kind=body.kind, app=self.flask_app,
        )

    def game_access(self, user, game_uuid: str) -> tuple[bool, bool]:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.library_acl import user_can_access_game

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if game is None:
            return False, False
        return True, bool(user_can_access_game(user, game))


def create_wanted_updates_router(
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
    data = data_access or WantedUpdateData()
    if getattr(data, 'uses_explicit_app', False):
        data.flask_app = flask_app

    @router.api_route('/api/updates/wanted', methods=['GET', 'HEAD'])
    def list_wanted(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                response = JSONResponse({'items': data.list(auth.user.id)})
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/updates/wanted')
    async def add_wanted(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.token is not None and not auth.has_scope('write:library'):
                response = _error(403, 'forbidden', 'Missing scope: write:library')
            elif auth.token is None:
                response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                response = None
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                body, response = await _validated(request, 'add')
                if response is None:
                    found, allowed = data.game_access(auth.user, body.game_uuid)
                    if not found:
                        response = _error(404, 'not_found', 'Game not found')
                    elif not allowed:
                        response = _error(403, 'forbidden', 'You do not have access to that game')
                    else:
                        try:
                            item = data.add(auth.user.id, body)
                        except ValueError as exc:
                            response = _error(400, 'bad_request', str(exc))
                        else:
                            from oneirodex.utils.api_contract import api_ok_payload

                            response = JSONResponse(
                                api_ok_payload({'item': item}), status_code=201,
                            )
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/updates/wanted/fulfill')
    async def fulfill_wanted(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.token is not None and not auth.has_scope('write:library'):
                response = _error(403, 'forbidden', 'Missing scope: write:library')
            elif auth.token is None:
                response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                response = None
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                body, response = await _validated(request, 'fulfill')
                if response is None:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload({
                        'updated': data.fulfill(auth.user.id, body),
                    }))
            _finish(response, flask_app, request, auth)
            return response

    return router


def mount_wanted_updates_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_wanted_updates_router(flask_app, **kwargs))
    return app


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


async def _validated(request, operation):
    import json

    from pydantic import ValidationError

    from oneirodex.schemas.wanted import AddWantedBody, FulfillWantedBody
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.validation import format_validation_errors

    model = AddWantedBody if operation == 'add' else FulfillWantedBody
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        is_json = content_type == 'application/json' or (
            content_type.startswith('application/') and content_type.endswith('+json')
        )
        raw = json.loads(await request.body() or b'{}') if is_json else {}
    except (TypeError, ValueError):
        raw = {}
    try:
        body = model.model_validate(raw if isinstance(raw, dict) else {})
    except ValidationError as exc:
        payload, status = api_error_payload(
            'Invalid request.', code='unprocessable', detail=format_validation_errors(exc),
        )
        return None, JSONResponse(payload, status_code=status)
    return body, None


def _error(status, code, message):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
