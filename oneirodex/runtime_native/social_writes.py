"""Native FastAPI friend-request, accept, reject, block and remove APIs."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _from_flask_response, _set_session_cookie
from .request_auth import request_auth_context


class SocialWriteData:
    def request(self, user, payload: dict):
        from sqlalchemy import or_, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User, UserFriendship
        from oneirodex.utils.notifications import notify_friend_request

        username = (payload.get('username') or payload.get('name') or '').strip()
        friend_id = payload.get('user_id')
        target = None
        if friend_id is not None:
            try:
                target = db.session.get(User, int(friend_id))
            except (TypeError, ValueError, OverflowError):
                target = None
        elif username:
            target = db.session.execute(
                select(User).where(User.name == username)
            ).scalars().first()
        opaque = {
            'sent': False,
            'message': 'If that username exists, a friend request was sent.',
        }
        if not target:
            return opaque, 200, None
        if target.id == user.id:
            return None, 400, ('bad_request', 'Cannot friend yourself')
        existing = db.session.execute(select(UserFriendship).where(or_(
            (UserFriendship.user_id == user.id) & (UserFriendship.friend_user_id == target.id),
            (UserFriendship.user_id == target.id) & (UserFriendship.friend_user_id == user.id),
        ))).scalars().first()
        if existing:
            if existing.status == 'blocked':
                return opaque, 200, None
            return {
                'friendship': existing.to_dict(), 'existing': True, 'sent': False,
            }, 200, None
        row = UserFriendship(
            user_id=user.id, friend_user_id=target.id, status='pending',
        )
        db.session.add(row)
        db.session.commit()
        try:
            notify_friend_request(target, user)
        except Exception:
            pass
        return {'friendship': row.to_dict(), 'sent': True}, 201, None

    def reject(self, user, friendship_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserFriendship

        row = db.session.get(UserFriendship, friendship_id)
        if row is None or row.friend_user_id != user.id or row.status != 'pending':
            return None, (404, 'not_found', 'Not found')
        db.session.delete(row)
        db.session.commit()
        return None, None

    def block(self, user, friendship_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserFriendship

        row = db.session.get(UserFriendship, friendship_id)
        if row is None or (row.user_id != user.id and row.friend_user_id != user.id):
            return None, (404, 'not_found', 'Not found')
        if row.status == 'blocked' and row.user_id != user.id:
            return None, (404, 'not_found', 'Not found')
        row.status = 'blocked'
        row.updated_at = datetime.now(timezone.utc)
        if row.friend_user_id == user.id:
            row.user_id, row.friend_user_id = row.friend_user_id, row.user_id
        db.session.commit()
        return {'friendship': row.to_dict()}, None

    def accept(self, user, friendship_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User, UserFriendship
        from oneirodex.utils.notifications import notify_friend_accepted

        row = db.session.get(UserFriendship, friendship_id)
        if row is None or row.friend_user_id != user.id or row.status == 'blocked':
            return None, (404, 'not_found', 'Not found')
        row.status = 'accepted'
        row.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        requester = db.session.get(User, row.user_id)
        if requester:
            try:
                notify_friend_accepted(requester, user)
            except Exception:
                pass
        return {'friendship': row.to_dict()}, None

    def delete(self, user, friendship_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserFriendship

        row = db.session.get(UserFriendship, friendship_id)
        if row is None or (row.user_id != user.id and row.friend_user_id != user.id):
            return None, (404, 'not_found', 'Not found')
        if row.status == 'blocked' and row.user_id != user.id:
            return None, (404, 'not_found', 'Not found')
        db.session.delete(row)
        db.session.commit()
        return None, None


def create_social_writes_router(
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
    data = data_access or SocialWriteData()

    @router.post('/api/social/friends')
    async def request_friend(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _csrf_for_browser(request, auth, flask_app)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                response = _scope_error(auth, 'write:social')
                if response is None:
                    payload = _json_object(await request.body())
                    if payload is None:
                        response = _error(400, 'bad_request', 'Expected a JSON object')
                    else:
                        result, status, refusal = data.request(auth.user, payload)
                        response = _error(*refusal) if refusal else _success(result, status=status)
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/social/friends/{friendship_id}/reject')
    def reject_friend(friendship_id: int, request: Request):
        return _mutate(request, friendship_id, 'reject', flask_app, find_user, find_token,
                       commit_token_touch, load_user_id, login_manager, data, database_scope)

    @router.post('/api/social/friends/{friendship_id}/block')
    def block_friend(friendship_id: int, request: Request):
        return _mutate(request, friendship_id, 'block', flask_app, find_user, find_token,
                       commit_token_touch, load_user_id, login_manager, data, database_scope)

    @router.post('/api/social/friends/{friendship_id}/accept')
    def accept_friend(friendship_id: int, request: Request):
        return _mutate(request, friendship_id, 'accept', flask_app, find_user, find_token,
                       commit_token_touch, load_user_id, login_manager, data, database_scope)

    @router.delete('/api/social/friends/{friendship_id}')
    def remove_friend(friendship_id: int, request: Request):
        return _mutate(request, friendship_id, 'delete', flask_app, find_user, find_token,
                       commit_token_touch, load_user_id, login_manager, data, database_scope)

    return router


def mount_social_writes_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_social_writes_router(flask_app, **kwargs))
    return app


def _mutate(request, friendship_id, operation, flask_app, find_user, find_token,
            commit_token_touch, load_user_id, login_manager, data, database_scope=None):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                     load_user_id, login_manager)
        response = _csrf_for_browser(request, auth, flask_app)
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        elif response is None:
            response = _scope_error(auth, 'write:social')
            if response is None:
                result, refusal = getattr(data, operation)(auth.user, friendship_id)
                if refusal:
                    response = _error(*refusal)
                else:
                    response = _success(result or {})
        _finish(response, flask_app, request, auth)
        return response


def _scope_error(auth, scope):
    if auth.has_scope(scope):
        return None
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(
        f'Missing scope: {scope}', code='forbidden',
        detail={'required_scope': scope},
    )
    return JSONResponse(payload, status_code=status)


def _csrf_for_browser(request, auth, flask_app):
    if auth.token is not None:
        return None
    return csrf_error_response(request, auth.session_data, flask_app.config)


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _json_object(raw_body: bytes) -> dict | None:
    import json

    try:
        payload = json.loads(raw_body or b'{}')
    except (TypeError, ValueError):
        return {}
    if isinstance(payload, dict):
        return payload
    # Preserve the legacy endpoint's empty-input behavior, but avoid claiming
    # success for a truthy scalar/array that cannot express a friend request.
    return None if payload else {}


def _error(status, code, message):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)


def _success(payload, *, status=200):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload), status_code=status)


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)

