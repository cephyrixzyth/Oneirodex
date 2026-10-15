"""Native read-only collection list and detail APIs."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .request_auth import request_auth_context
from .csrf_compat import csrf_error_response


class CollectionReadData:
    def list(self, user, *, admin_access: bool):
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameCollection, GameCollectionItem

        rows = db.session.execute(
            select(GameCollection).order_by(GameCollection.created_at.desc())
        ).scalars().all()
        visible = [
            collection for collection in rows
            if collection.is_public
            or collection.owner_user_id == user.id
            or admin_access
        ]
        collection_ids = [collection.id for collection in visible]
        if collection_ids:
            counts = db.session.execute(
                select(
                    GameCollectionItem.collection_id,
                    func.count(GameCollectionItem.id),
                )
                .where(GameCollectionItem.collection_id.in_(collection_ids))
                .group_by(GameCollectionItem.collection_id)
            ).all()
            count_map = {identifier: int(count) for identifier, count in counts}
        else:
            count_map = {}
        return {'collections': [
            _collection_payload(
                collection, user, admin_access=admin_access,
                item_count=count_map.get(collection.id, 0),
            )
            for collection in visible
        ]}

    def detail(self, user, collection_uuid: str, *, admin_access: bool):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameCollection

        collection = db.session.execute(
            select(GameCollection).filter_by(uuid=collection_uuid)
        ).scalars().first()
        if collection is None:
            return None, 404
        if not collection.is_public and not (
            collection.owner_user_id == user.id or admin_access
        ):
            return None, 403
        payload = _collection_payload(
            collection, user, admin_access=admin_access, include_items=True
        )
        if collection.owner_user_id != user.id and not admin_access:
            from oneirodex.utils.library_acl import user_can_access_game

            payload['items'] = [
                item.to_dict() for item in collection.items
                if user_can_access_game(user, item.game)
            ]
            payload['item_count'] = len(payload['items'])
        return payload, 200

    def create(self, user, body):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameCollection

        collection = GameCollection(
            name=body.name[:120],
            description=(body.description or '')[:4000] or None,
            owner_user_id=user.id,
            is_public=bool(body.is_public),
            is_system=False,
        )
        db.session.add(collection)
        db.session.commit()
        return _collection_payload(collection, user, admin_access=False, item_count=0)

    def update(self, user, collection_uuid: str, payload: dict, *, admin_access: bool):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameCollection

        collection = db.session.execute(
            select(GameCollection).filter_by(uuid=collection_uuid)
        ).scalars().first()
        refusal = _editable_refusal(collection, user, admin_access)
        if refusal:
            return None, refusal
        if collection.is_system:
            return None, (400, 'bad_request', 'System collections cannot be edited')
        if 'name' in payload:
            name = (payload.get('name') or '').strip()
            if not name:
                return None, (400, 'bad_request', 'A name is required')
            collection.name = name[:120]
        if 'description' in payload:
            raw = payload.get('description')
            collection.description = None if raw is None else (str(raw).strip()[:4000] or None)
        if 'is_public' in payload:
            collection.is_public = bool(payload.get('is_public'))
        db.session.commit()
        return _collection_payload(
            collection, user, admin_access=admin_access, include_items=True
        ), None

    def delete(self, user, collection_uuid: str, *, admin_access: bool):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameCollection

        collection = db.session.execute(
            select(GameCollection).filter_by(uuid=collection_uuid)
        ).scalars().first()
        refusal = _editable_refusal(collection, user, admin_access)
        if refusal:
            return None, refusal
        if collection.is_system:
            return None, (400, 'bad_request', 'System collections cannot be deleted')
        identifier = collection.uuid
        db.session.delete(collection)
        db.session.commit()
        return {'uuid': identifier}, None

    def add_item(self, user, collection_uuid: str, game_uuid: str, *, admin_access: bool):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, GameCollectionItem
        from oneirodex.utils.library_acl import user_can_access_game

        collection, refusal = self._editable_collection(collection_uuid, user, admin_access)
        if refusal:
            return None, refusal, 0
        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if game is None:
            return None, (404, 'not_found', 'Game not found'), 0
        if not user_can_access_game(user, game):
            return None, (403, 'forbidden', 'You do not have access to that game'), 0
        existing = db.session.execute(select(GameCollectionItem).filter_by(
            collection_id=collection.id, game_uuid=game_uuid
        )).scalars().first()
        if existing:
            return existing.to_dict(), None, 200
        item = GameCollectionItem(
            collection_id=collection.id, game_uuid=game_uuid,
            position=len(collection.items),
        )
        db.session.add(item)
        db.session.commit()
        return item.to_dict(), None, 201

    def remove_item(self, user, collection_uuid: str, game_uuid: str, *, admin_access: bool):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameCollectionItem

        collection, refusal = self._editable_collection(collection_uuid, user, admin_access)
        if refusal:
            return None, refusal
        item = db.session.execute(select(GameCollectionItem).filter_by(
            collection_id=collection.id, game_uuid=game_uuid
        )).scalars().first()
        if item is None:
            return None, (404, 'not_found', 'That game is not in the collection')
        db.session.delete(item)
        db.session.commit()
        return {'game_uuid': game_uuid}, None

    def reorder(self, user, collection_uuid: str, game_uuids: list, *, admin_access: bool):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameCollection

        collection, refusal = self._editable_collection(collection_uuid, user, admin_access)
        if refusal:
            return None, refusal
        normalized = [str(value).strip() for value in game_uuids if value is not None]
        current = {item.game_uuid for item in collection.items}
        if len(normalized) != len(set(normalized)) or set(normalized) != current:
            return None, (400, 'bad_request', 'game_uuids must list each collection item exactly once')
        by_uuid = {item.game_uuid: item for item in collection.items}
        for position, game_uuid in enumerate(normalized):
            by_uuid[game_uuid].position = position
        db.session.commit()
        db.session.refresh(collection)
        return _collection_payload(
            collection, user, admin_access=admin_access, include_items=True
        ), None

    def _editable_collection(self, collection_uuid, user, admin_access):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameCollection

        collection = db.session.execute(
            select(GameCollection).filter_by(uuid=collection_uuid)
        ).scalars().first()
        refusal = _editable_refusal(collection, user, admin_access)
        return (None, refusal) if refusal else (collection, None)


def create_collection_reads_router(
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
    data = data_access or CollectionReadData()

    @router.api_route('/api/collections', methods=['GET', 'HEAD'])
    def list_collections(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
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
                from starlette.responses import JSONResponse

                response = JSONResponse(data.list(
                    auth.user,
                    admin_access=_admin_access(auth.user, auth.token),
                ))
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.post('/api/collections')
    async def create_collection(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                          load_user_id, login_manager)
            scope_response = _write_scope_error(auth)
            csrf_response = _csrf_error(request, auth, flask_app)
            if scope_response is not None:
                response = scope_response
            elif csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                body, response = await _parse_body(request, 'create_collection')
                if response is None:
                    response = JSONResponse(data.create(auth.user, body), status_code=201)
            _finish_auth(response, flask_app, request, auth)
            return response

    @router.patch('/api/collections/{collection_uuid}')
    async def update_collection(collection_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                          load_user_id, login_manager)
            scope_response = _write_scope_error(auth)
            csrf_response = _csrf_error(request, auth, flask_app)
            if scope_response is not None:
                response = scope_response
            elif csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                payload = _json_object(await request.body())
                result, refusal = data.update(
                    auth.user, collection_uuid, payload,
                    admin_access=_admin_access(auth.user, auth.token),
                )
                response = _error_response(refusal) if refusal else JSONResponse(result)
            _finish_auth(response, flask_app, request, auth)
            return response

    @router.delete('/api/collections/{collection_uuid}')
    async def delete_collection(collection_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                          load_user_id, login_manager)
            scope_response = _write_scope_error(auth)
            csrf_response = _csrf_error(request, auth, flask_app)
            if scope_response is not None:
                response = scope_response
            elif csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                result, refusal = data.delete(
                    auth.user, collection_uuid,
                    admin_access=_admin_access(auth.user, auth.token),
                )
                if refusal:
                    response = _error_response(refusal)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(result))
            _finish_auth(response, flask_app, request, auth)
            return response

    @router.post('/api/collections/{collection_uuid}/items')
    async def add_collection_item(collection_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                          load_user_id, login_manager)
            scope_response = _write_scope_error(auth)
            csrf_response = _csrf_error(request, auth, flask_app)
            if scope_response is not None:
                response = scope_response
            elif csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                body, response = await _parse_body(request, 'add_collection_item')
                if response is None:
                    item, refusal, status = data.add_item(
                        auth.user, collection_uuid, body.game_uuid,
                        admin_access=_admin_access(auth.user, auth.token),
                    )
                    response = _error_response(refusal) if refusal else JSONResponse(item, status_code=status)
            _finish_auth(response, flask_app, request, auth)
            return response

    @router.delete('/api/collections/{collection_uuid}/items/{game_uuid}')
    async def remove_collection_item(collection_uuid: str, game_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                          load_user_id, login_manager)
            scope_response = _write_scope_error(auth)
            csrf_response = _csrf_error(request, auth, flask_app)
            if scope_response is not None:
                response = scope_response
            elif csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                result, refusal = data.remove_item(
                    auth.user, collection_uuid, game_uuid,
                    admin_access=_admin_access(auth.user, auth.token),
                )
                if refusal:
                    response = _error_response(refusal)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(result))
            _finish_auth(response, flask_app, request, auth)
            return response

    @router.put('/api/collections/{collection_uuid}/items/order')
    async def reorder_collection_items(collection_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                          load_user_id, login_manager)
            scope_response = _write_scope_error(auth)
            csrf_response = _csrf_error(request, auth, flask_app)
            if scope_response is not None:
                response = scope_response
            elif csrf_response is not None:
                response = csrf_response
            elif auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                body, response = await _parse_body(request, 'reorder_collection_items')
                if response is None:
                    result, refusal = data.reorder(
                        auth.user, collection_uuid, body.game_uuids,
                        admin_access=_admin_access(auth.user, auth.token),
                    )
                    response = _error_response(refusal) if refusal else JSONResponse(result)
            _finish_auth(response, flask_app, request, auth)
            return response

    @router.api_route('/api/collections/{collection_uuid}', methods=['GET', 'HEAD'])
    def collection_detail(collection_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
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
                from oneirodex.utils.api_contract import api_error_payload

                payload, status = data.detail(
                    auth.user,
                    collection_uuid,
                    admin_access=_admin_access(auth.user, auth.token),
                )
                if status != 200:
                    message = (
                        'Collection not found' if status == 404
                        else 'That collection is private'
                    )
                    code = 'not_found' if status == 404 else 'forbidden'
                    payload, response_status = api_error_payload(
                        message, code=code, status=status
                    )
                    response = JSONResponse(payload, status_code=response_status)
                else:
                    response = JSONResponse(payload)
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    return router


def mount_collection_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_collection_reads_router(flask_app, **kwargs))
    return app


def _collection_payload(
    collection, user, *, admin_access: bool,
    include_items=False, item_count=None,
):
    payload = collection.to_dict(include_items=include_items)
    payload['can_edit'] = (
        collection.owner_user_id == user.id or admin_access
    )
    if item_count is not None:
        payload['item_count'] = int(item_count)
    elif include_items:
        payload['item_count'] = len(payload.get('items') or [])
    return payload


def _admin_access(user, token) -> bool:
    from oneirodex.utils.role_catalog import normalize_role

    return (
        bool(getattr(user, 'is_authenticated', True))
        and normalize_role(getattr(user, 'role', None)) == 'admin'
        and (token is None or token.has_scope('admin'))
    )


def _finalize(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''


def _editable_refusal(collection, user, admin_access):
    if collection is None:
        return (404, 'not_found', 'Collection not found')
    if collection.owner_user_id != user.id and not admin_access:
        return (403, 'forbidden', 'That collection belongs to someone else')
    return None


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


async def _parse_body(request, operation):
    import json

    from pydantic import ValidationError

    from oneirodex.schemas.collections import (
        AddCollectionItemBody, CreateCollectionBody, ReorderCollectionItemsBody,
    )
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.validation import format_validation_errors

    models = {
        'create_collection': CreateCollectionBody,
        'add_collection_item': AddCollectionItemBody,
        'reorder_collection_items': ReorderCollectionItemsBody,
    }
    try:
        raw = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        raw = {}
    try:
        body = models[operation].model_validate(raw if isinstance(raw, dict) else {})
    except ValidationError as exc:
        payload, status = api_error_payload(
            'Invalid request.', code='unprocessable',
            detail=format_validation_errors(exc),
        )
        return None, JSONResponse(payload, status_code=status)
    return body, None


def _json_object(raw_body: bytes) -> dict:
    import json

    try:
        payload = json.loads(raw_body or b'{}')
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _error_response(refusal):
    from oneirodex.utils.api_contract import api_error_payload

    status, code, message = refusal
    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)


def _write_scope_error(auth):
    if auth.token is None or auth.has_scope('write:library'):
        return None
    return _error_response((403, 'forbidden', 'Missing scope: write:library'))


def _csrf_error(request, auth, flask_app):
    if auth.token is not None:
        return None
    return csrf_error_response(request, auth.session_data, flask_app.config)


def _finish_auth(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        from .oidc_status import _set_session_cookie

        _set_session_cookie(response, flask_app, auth)
    _finalize(response, flask_app, request)
