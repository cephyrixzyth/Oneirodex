"""Native FastAPI routes for member game requests / wishlist."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class WishlistData:
    def list(self, user, *, include_all: bool):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameRequest

        query = select(GameRequest).order_by(GameRequest.created_at.desc())
        if include_all:
            query = query.limit(200)
        else:
            query = query.filter_by(user_id=user.id).limit(100)
        return [row.to_dict() for row in db.session.execute(query).scalars().all()]

    def create(self, user, title: str, notes: str | None):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameRequest
        from oneirodex.utils.event_logging import log_system_event

        title = title[:255]
        existing = db.session.execute(select(GameRequest).filter_by(
            user_id=user.id, title=title, status='pending'
        )).scalars().first()
        if existing:
            return existing.to_dict(), 200, None
        row = GameRequest(
            user_id=user.id, title=title,
            notes=(notes or '')[:4000] or None, status='pending',
        )
        db.session.add(row)
        db.session.commit()
        log_system_event(
            f'Wishlist request created: {row.title}',
            event_type='game', event_level='information', audit_user=user.id,
        )
        return row.to_dict(), 201, None

    def cancel(self, user, request_id: int, *, librarian: bool):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameRequest

        row = db.session.get(GameRequest, request_id)
        if row is None:
            return None, (404, 'not_found', 'Request not found')
        if row.user_id != user.id and not librarian:
            return None, (403, 'forbidden', 'That request belongs to someone else')
        if row.status != 'pending' and not librarian:
            return None, (400, 'bad_request', 'Only pending requests can be cancelled')
        db.session.delete(row)
        db.session.commit()
        return {'id': request_id}, None

    def resolve(self, user, request_id: int, body):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, GameRequest, User
        from oneirodex.utils.event_logging import log_system_event

        row = db.session.get(GameRequest, request_id)
        if row is None:
            return None, (404, 'not_found', 'Request not found')
        status = body.status
        if status not in {'approved', 'rejected', 'fulfilled', 'pending'}:
            return None, (400, 'bad_request', 'That status is not one this request can move to')
        linked = (body.linked_game_uuid or '').strip() or None
        if linked:
            game = db.session.execute(select(Game).filter_by(uuid=linked)).scalars().first()
            if game is None:
                return None, (404, 'not_found', 'linked_game_uuid does not match a game')
            row.linked_game_uuid = linked
            if status == 'pending':
                status = 'fulfilled'
        row.status = status
        if status == 'pending':
            row.resolved_at = None
            row.resolved_by_user_id = None
        else:
            row.resolved_at = datetime.now(timezone.utc)
            row.resolved_by_user_id = user.id
        if body.notes is not None:
            note = (body.notes or '').strip()
            if note:
                row.notes = ((row.notes or '') + f'\n[staff] {note}').strip()[:4000]
        db.session.commit()
        log_system_event(
            f'Wishlist request {row.id} → {status}',
            event_type='game', event_level='information', audit_user=user.id,
        )
        if status == 'fulfilled':
            requester = db.session.get(User, row.user_id)
            try:
                from oneirodex.utils.notifications import notify_admins

                notify_admins(
                    kind='wishlist',
                    title=f'Wishlist fulfilled: {row.title}',
                    body=(f'Fulfilled for {requester.name}.' if requester
                          else 'A wishlist request was fulfilled.'),
                    link=f'/game_details/{row.linked_game_uuid}' if row.linked_game_uuid else '/wishlist',
                    payload={
                        'request_id': row.id,
                        'linked_game_uuid': row.linked_game_uuid,
                        'requester_name': requester.name if requester else None,
                    },
                )
            except Exception:
                pass
        return row.to_dict(), None


def create_wishlist_router(
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
    data = data_access or WishlistData()

    @router.api_route('/api/requests', methods=['GET', 'HEAD'])
    def list_requests(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                all_values = request.query_params.getlist('all')
                include_all = (
                    bool(all_values) and all_values[0] == '1'
                    and _librarian(auth.user, auth.token)
                )
                response = JSONResponse({'requests': data.list(auth.user, include_all=include_all)})
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.post('/api/requests')
    async def create_request(request: Request):
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
                from oneirodex.utils.role_catalog import normalize_role

                if normalize_role(getattr(auth.user, 'role', None)) == 'child':
                    response = _error(403, 'forbidden', 'Wishlist requests are not available for this account')
                else:
                    body, response = await _validated(request, 'create')
                    if response is None:
                        payload, status, refusal = data.create(auth.user, body.title, body.notes)
                        response = _error(*refusal) if refusal else JSONResponse(payload, status_code=status)
            _finish(response, flask_app, request, auth)
            return response

    @router.delete('/api/requests/{request_id:int}')
    def cancel_request(request_id: int, request: Request):
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
                payload, refusal = data.cancel(
                    auth.user, request_id,
                    librarian=_librarian(auth.user, auth.token),
                )
                if refusal:
                    response = _error(*refusal)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(payload))
            _finish(response, flask_app, request, auth)
            return response

    @router.patch('/api/requests/{request_id:int}')
    async def resolve_request(request_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                if not _librarian(auth.user, auth.token):
                    response = _error(403, 'forbidden', 'Librarian or admin required')
                else:
                    body, response = await _validated(request, 'resolve')
                    if response is None:
                        payload, refusal = data.resolve(auth.user, request_id, body)
                        response = _error(*refusal) if refusal else JSONResponse(payload)
            _finish(response, flask_app, request, auth)
            return response

    return router


def mount_wishlist_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_wishlist_router(flask_app, **kwargs))
    return app


def _librarian(user, token):
    from oneirodex.utils.role_catalog import role_at_least

    return (
        bool(getattr(user, 'is_authenticated', True))
        and role_at_least(getattr(user, 'role', None), 'librarian')
        and (token is None or token.has_scope('admin'))
    )


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


async def _validated(request, operation):
    import json

    from pydantic import ValidationError

    from oneirodex.schemas.wishlist import CreateWishlistRequestBody, ResolveWishlistRequestBody
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.validation import format_validation_errors

    model = CreateWishlistRequestBody if operation == 'create' else ResolveWishlistRequestBody
    try:
        raw = json.loads(await request.body() or b'{}')
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
    _finalize(response, flask_app, request)


def _finalize(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
