"""Native FastAPI read routes for social status and friend list."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class SocialReadData:
    def profile(self, viewer, user_id: int, flask_app):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, User, UserGameProgress
        from oneirodex.utils.avatar import DEFAULT_AVATAR
        from oneirodex.utils.presence import accepted_friend_ids, presence_for_user

        target = db.session.get(User, user_id)
        if not target or not target.state:
            return None
        friends = accepted_friend_ids(viewer.id)
        rows = db.session.execute(
            select(UserGameProgress)
            .where(UserGameProgress.user_id == target.id)
            .order_by(UserGameProgress.last_played_at.desc().nullslast())
            .limit(40)
        ).scalars().all()
        recent, total_seconds = [], 0
        for row in rows:
            game = db.session.execute(select(Game).filter_by(uuid=row.game_uuid)).scalars().first()
            if not game or not self._can_view_game(viewer, game):
                continue
            seconds = int(row.total_seconds or 0)
            total_seconds += seconds
            recent.append({
                'game_uuid': row.game_uuid, 'game_name': game.name,
                'total_seconds': seconds,
                'last_played_at': row.last_played_at.isoformat() if row.last_played_at else None,
            })
            if len(recent) >= 12:
                break
        avatar = getattr(target, 'avatarpath', None) or DEFAULT_AVATAR
        return {
            'user': {
                'id': target.id, 'name': target.name,
                'about': getattr(target, 'about', None),
                'avatar_url': (
                    f"{flask_app.static_url_path.rstrip('/')}/{quote(avatar, safe='/')}"
                    if avatar else None
                ),
            },
            'presence': presence_for_user(target.id, viewer=viewer),
            'is_self': target.id == viewer.id,
            'is_friend': target.id in friends,
            'total_seconds': total_seconds,
            'recent_games': recent,
        }

    def profile_compare(self, viewer, user_id: int, other_id: int):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, User, UserGameProgress
        from oneirodex.utils.presence import accepted_friend_ids

        if viewer.id not in {user_id, other_id}:
            return 'Forbidden', 403
        friends = accepted_friend_ids(viewer.id)
        other = other_id if viewer.id == user_id else user_id
        if other != viewer.id and other not in friends:
            return 'Friends only', 403
        left, right = db.session.get(User, user_id), db.session.get(User, other_id)
        if not left or not right:
            return 'Not found', 404
        left_rows = {
            row.game_uuid: row for row in db.session.execute(
                select(UserGameProgress).where(UserGameProgress.user_id == user_id)
            ).scalars().all()
        }
        right_rows = {
            row.game_uuid: row for row in db.session.execute(
                select(UserGameProgress).where(UserGameProgress.user_id == other_id)
            ).scalars().all()
        }
        shared = []
        for game_uuid in set(left_rows) & set(right_rows):
            game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
            if not game or not self._can_view_game(viewer, game):
                continue
            shared.append({
                'game_uuid': game_uuid, 'game_name': game.name,
                'left_seconds': int(left_rows[game_uuid].total_seconds or 0),
                'right_seconds': int(right_rows[game_uuid].total_seconds or 0),
            })
        shared.sort(key=lambda row: row['left_seconds'] + row['right_seconds'], reverse=True)
        return {
            'left': {'id': left.id, 'name': left.name},
            'right': {'id': right.id, 'name': right.name},
            'shared_games': shared[:40],
        }, 200

    @staticmethod
    def _can_view_game(user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return bool(user_can_access_game(user, game))

    def activity(self, user, *, limit: int, friends_only: bool):
        from oneirodex.utils.activity_feed import (
            list_now_playing,
            list_recent_activity,
        )
        from oneirodex.utils.role_catalog import normalize_role

        if normalize_role(getattr(user, 'role', None)) == 'child':
            return {'activity': [], 'now_playing': [], 'restricted': True}
        return {
            'activity': list_recent_activity(
                limit=limit, viewer=user, friends_only=friends_only,
            ),
            'now_playing': list_now_playing(
                viewer=user, friends_only=friends_only,
            ),
            'friends_only': friends_only,
        }

    def status(self, user):
        from sqlalchemy import or_, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UserFriendship
        from oneirodex.utils.social_projections import community_settings
        from oneirodex.utils.activity_feed import list_now_playing
        from oneirodex.utils.presence import list_friend_presence

        friendships = db.session.execute(select(UserFriendship).where(
            or_(
                UserFriendship.user_id == user.id,
                UserFriendship.friend_user_id == user.id,
            ),
            UserFriendship.status == 'accepted',
        )).scalars().all()
        pending_in = db.session.execute(select(UserFriendship).where(
            UserFriendship.friend_user_id == user.id,
            UserFriendship.status == 'pending',
        )).scalars().all()
        return {
            **community_settings(),
            'friend_count': len(friendships),
            'pending_incoming': len(pending_in),
            'now_playing': list_now_playing(viewer=user),
            'presence': list_friend_presence(user),
        }

    def friends(self, user):
        from sqlalchemy import or_, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User, UserFriendship
        from oneirodex.utils.social_projections import user_public

        rows = db.session.execute(select(UserFriendship).where(or_(
            UserFriendship.user_id == user.id,
            UserFriendship.friend_user_id == user.id,
        ))).scalars().all()
        output = []
        for row in rows:
            other_id = row.friend_user_id if row.user_id == user.id else row.user_id
            other = db.session.get(User, other_id)
            if other is None:
                continue
            direction = 'outgoing' if row.user_id == user.id else 'incoming'
            output.append({
                **row.to_dict(),
                'direction': direction,
                'user': user_public(other, viewer=user),
            })
        return {'friends': output}


def create_social_reads_router(
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
    data = data_access or SocialReadData()

    @router.api_route('/api/social/status', methods=['GET', 'HEAD'])
    def social_status(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                response = _scope_error(auth, 'read:social')
            if response is None:
                response = JSONResponse(data.status(auth.user))
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/social/friends', methods=['GET', 'HEAD'])
    def social_friends(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                response = _scope_error(auth, 'read:social')
            if response is None:
                response = JSONResponse(data.friends(auth.user))
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/users/{user_id:int}/profile', methods=['GET', 'HEAD'])
    def member_profile(request: Request, user_id: int):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                response = _scope_error(auth, 'read:social')
            if response is None:
                try:
                    payload = data.profile(auth.user, user_id, flask_app)
                    response = (
                        _api_error('Not found', 'not_found') if payload is None
                        else JSONResponse(payload)
                    )
                except Exception:  # noqa: BLE001 — keep private DB failures private
                    response = _api_error('Could not load the member profile', 'internal')
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/users/{user_id:int}/compare/{other_id:int}', methods=['GET', 'HEAD'])
    def member_profile_compare(request: Request, user_id: int, other_id: int):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                response = _scope_error(auth, 'read:social')
            if response is None:
                try:
                    payload, status = data.profile_compare(auth.user, user_id, other_id)
                    response = (
                        _api_error(payload, 'forbidden' if status == 403 else 'not_found')
                        if status != 200 else JSONResponse(payload)
                    )
                except Exception:  # noqa: BLE001 — keep private DB failures private
                    response = _api_error('Could not compare member playtime', 'internal')
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/activity', methods=['GET', 'HEAD'])
    def activity(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                response = _scope_error(auth, 'read:social')
            if response is None:
                # Werkzeug's MultiDict returns the first value; preserve that when
                # the caller repeats a query parameter under Starlette.
                raw_limit = _first_query_value(request, 'limit') or '25'
                try:
                    limit = min(100, max(1, int(raw_limit)))
                except (TypeError, ValueError, OverflowError):
                    limit = 25
                raw_friends_only = (_first_query_value(request, 'friends_only') or '').lower()
                friends_only = raw_friends_only in ('1', 'true', 'yes')
                from oneirodex.utils.role_catalog import normalize_role

                if normalize_role(getattr(auth.user, 'role', None)) == 'child':
                    payload = {'activity': [], 'now_playing': [], 'restricted': True}
                else:
                    payload = data.activity(
                        auth.user, limit=limit, friends_only=friends_only,
                    )
                response = JSONResponse(payload)
            _finish(response, flask_app, request, auth)
            return response

    return router


def mount_social_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_social_reads_router(flask_app, **kwargs))
    return app


def _scope_error(auth, scope):
    if auth.has_scope(scope):
        return None
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(
        f'Missing scope: {scope}', code='forbidden',
        detail={'required_scope': scope},
    )
    return JSONResponse(payload, status_code=status)


def _api_error(message, code):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''


def _first_query_value(request, name: str) -> str | None:
    values = request.query_params.getlist(name)
    return values[0] if values else None
