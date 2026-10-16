"""Native member VR catalogue and game detail reads."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .batch_favorite import _finish
from .request_auth import request_auth_context


class VrReadData:
    def enabled(self, flask_app):
        return str(flask_app.config.get('ENABLE_VR_BROWSE', '')).lower() in (
            '1', 'true', 'yes', 'on',
        )

    def catalog(self, user, *, page: int, per_page: int, compatibility: str):
        from sqlalchemy import and_, exists, func, or_, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import (
            Game, GameVrProfile, Image, PlayerPerspective,
            game_player_perspective_association,
        )
        from oneirodex.utils.library_acl import apply_game_access_filters
        from oneirodex.utils.secondary_scrapers import VR_PERSPECTIVE_NAME, game_vr_compat
        from oneirodex.utils.vr_catalog import (
            cover_url_for_game, vr_perspective_link, vr_profile_link,
        )

        perspective_link = vr_perspective_link(
            Game, PlayerPerspective, game_player_perspective_association,
            (VR_PERSPECTIVE_NAME.lower(), 'vr', 'vr / virtual reality'),
        )

        def profile_link(kinds):
            return vr_profile_link(Game, GameVrProfile, kinds)

        query = select(Game).where(or_(
            Game.vr_compat.in_(('native_vr', 'injector_profile')),
            and_(Game.vr_compat.is_(None), exists(perspective_link)),
            and_(Game.vr_compat.is_(None), exists(profile_link(('native', 'injector')))),
        ))
        query = apply_game_access_filters(query, user)
        if compatibility == 'native_vr':
            query = query.where(or_(
                Game.vr_compat == 'native_vr',
                and_(Game.vr_compat.is_(None), exists(profile_link(('native',)))),
                and_(
                    Game.vr_compat.is_(None),
                    ~exists(profile_link(('injector',))),
                    exists(perspective_link),
                ),
            ))
        elif compatibility == 'injector_profile':
            query = query.where(or_(
                Game.vr_compat == 'injector_profile',
                and_(
                    Game.vr_compat.is_(None),
                    ~exists(profile_link(('native',))),
                    exists(profile_link(('injector',))),
                ),
            ))
        query = query.order_by(Game.name.asc())
        total = db.session.execute(
            select(func.count()).select_from(query.order_by(None).subquery()),
        ).scalar() or 0
        pages = max(1, (total + per_page - 1) // per_page)
        games = db.session.execute(
            query.offset((page - 1) * per_page).limit(per_page),
        ).scalars().all()
        return {
            'page': page, 'pages': pages, 'total': total,
            'games': [{
                'uuid': game.uuid, 'name': game.name,
                'cover_url': cover_url_for_game(game, db.session, Game, Image),
                'vr_compat': game_vr_compat(game),
            } for game in games],
        }

    def detail(self, user, game_uuid):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Image
        from oneirodex.utils.functions import format_size
        from oneirodex.utils.library_acl import user_can_access_game
        from oneirodex.utils.secondary_scrapers import game_vr_compat
        from oneirodex.utils.vr_catalog import cover_url_for_game, game_in_vr_hub

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if game is None:
            return None, 'not_found'
        if not user_can_access_game(user, game):
            return None, 'forbidden'
        if not game_in_vr_hub(game, game_vr_compat):
            return None, 'not_found'
        return {
            'uuid': game.uuid, 'name': game.name,
            'cover_url': cover_url_for_game(game, db.session, Game, Image), 'summary': game.summary,
            'size': format_size(game.size) if game.size is not None else None,
            'vr_compat': game_vr_compat(game),
            'vr_profiles': [row.to_dict() for row in (game.vr_profiles or [])],
        }, None

    def accessible_game(self, user, game_uuid):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.library_acl import user_can_access_game

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if game is None:
            return None, 'not_found'
        if not user_can_access_game(user, game):
            return None, 'forbidden'
        return game, None

    def profiles_payload(self, game):
        from oneirodex.utils.secondary_scrapers import game_vr_compat

        return {
            'uuid': game.uuid,
            'vr_profiles': [row.to_dict() for row in (game.vr_profiles or [])],
            'vr_compat': game_vr_compat(game),
            'vr_compat_stored': game.vr_compat,
            'kinds': ['native', 'injector', 'flat'],
        }

    def save_profile(self, game, kind, body):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameVrProfile

        row = next((item for item in (game.vr_profiles or []) if item.kind == kind), None)
        if row is None:
            row = GameVrProfile(game_uuid=game.uuid, kind=kind)
            db.session.add(row)
        row.runtime = body.runtime
        row.profile_url = body.profile_url
        row.notes = body.notes
        row.source = body.source
        db.session.commit()
        db.session.refresh(game)
        return row

    def delete_profile(self, game, kind):
        from oneirodex.runtime_native.db_session import native_db as db

        row = next((item for item in (game.vr_profiles or []) if item.kind == kind), None)
        if row is None:
            return False
        db.session.delete(row)
        db.session.commit()
        db.session.refresh(game)
        return True

    def save_compat(self, game, value):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.secondary_scrapers import game_indicates_vr, game_vr_compat

        game.vr_compat = value
        db.session.commit()
        return {
            'uuid': game.uuid, 'vr_compat': game_vr_compat(game),
            'vr_compat_stored': game.vr_compat, 'is_vr': game_indicates_vr(game),
        }

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_vr_read_router(
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
    data = data_access or VrReadData()

    @router.api_route('/api/vr/catalog', methods=['GET', 'HEAD'])
    def vr_catalog(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None and not data.enabled(flask_app):
                response = _api_error('VR browse is disabled', 'forbidden')
            if response is None:
                try:
                    page = max(1, int(_first(request, 'page') or 1))
                    per_page = min(100, max(1, int(_first(request, 'per_page') or 24)))
                except (TypeError, ValueError):
                    response = _api_error('Invalid pagination', 'bad_request')
                else:
                    compatibility = str(_first(request, 'vr_compat') or '').strip().lower()
                    try:
                        response = JSONResponse(data.catalog(
                            auth.user, page=page, per_page=per_page,
                            compatibility=compatibility,
                        ))
                    except Exception:  # noqa: BLE001 — protect DB internals
                        response = _api_error('Could not load the VR catalogue', 'internal')
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/vr/games/{game_uuid}', methods=['GET', 'HEAD'])
    def vr_game_detail(request: Request, game_uuid: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None and not data.enabled(flask_app):
                response = _api_error('VR browse is disabled', 'forbidden')
            if response is None:
                try:
                    payload, refusal = data.detail(auth.user, game_uuid)
                    if refusal:
                        message = 'Forbidden' if refusal == 'forbidden' else 'Game not found'
                        response = _api_error(message, refusal)
                    else:
                        response = JSONResponse(payload)
                except Exception:  # noqa: BLE001 — protect DB internals
                    response = _api_error('Could not load the VR game', 'internal')
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    def authorize(request: Request, *, write=False, librarian=False):
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
        )
        response = None
        if write and auth.token is None:
            from .csrf_compat import csrf_error_response

            response = csrf_error_response(request, auth.session_data, flask_app.config)
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        if response is None and librarian:
            from oneirodex.utils.role_catalog import role_at_least

            permitted = (
                getattr(auth.user, 'is_authenticated', False)
                and role_at_least(getattr(auth.user, 'role', None), 'librarian')
                and (auth.token is None or auth.has_scope('admin'))
            )
            if not permitted:
                response = _api_error('Librarian or admin required', 'forbidden')
        return auth, response

    @router.api_route('/api/games/{game_uuid}/vr_profiles', methods=['GET', 'HEAD'])
    def get_game_vr_profiles(request: Request, game_uuid: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = authorize(request)
            if response is None:
                game, refusal = data.accessible_game(auth.user, game_uuid)
                if refusal:
                    response = _api_error(
                        'Game not found' if refusal == 'not_found' else 'Forbidden', refusal,
                    )
                else:
                    response = _ok(data.profiles_payload(game))
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.put('/api/games/{game_uuid}/vr_profiles/{kind}')
    async def put_game_vr_profile(request: Request, game_uuid: str, kind: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = authorize(request, write=True, librarian=True)
            if response is None:
                kind = (kind or '').strip().lower()
                kinds = ['native', 'injector', 'flat']
                from pydantic import ValidationError

                from oneirodex.schemas.vr import VrProfileBody
                from oneirodex.utils.validation import format_validation_errors

                try:
                    body = VrProfileBody.model_validate(await _json_object(request))
                except ValidationError as exc:
                    response = _api_error(
                        'Invalid request.', 'unprocessable',
                        detail=format_validation_errors(exc),
                    )
                else:
                    if kind not in kinds:
                        response = _api_error(
                            'kind must be native, injector or flat', 'bad_request', kinds=kinds,
                        )
                    else:
                        game, refusal = data.accessible_game(auth.user, game_uuid)
                        if refusal:
                            response = _api_error(
                                'Game not found' if refusal == 'not_found' else 'Forbidden', refusal,
                            )
                        else:
                            try:
                                row = data.save_profile(game, kind, body)
                                response = _ok({
                                    **data.profiles_payload(game), 'profile': row.to_dict(),
                                })
                            except Exception:  # noqa: BLE001 — do not expose persistence details
                                data.rollback()
                                flask_app.logger.warning('VR profile save failed')
                                response = _api_error("Couldn't save the VR profile.", 'internal')
            _finish(response, flask_app, auth)
            return response

    @router.delete('/api/games/{game_uuid}/vr_profiles/{kind}')
    def delete_game_vr_profile(request: Request, game_uuid: str, kind: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = authorize(request, write=True, librarian=True)
            if response is None:
                game, refusal = data.accessible_game(auth.user, game_uuid)
                if refusal:
                    response = _api_error(
                        'Game not found' if refusal == 'not_found' else 'Forbidden', refusal,
                    )
                else:
                    try:
                        if not data.delete_profile(game, (kind or '').strip().lower()):
                            response = _api_error('Profile not found', 'not_found')
                        else:
                            response = _ok(data.profiles_payload(game))
                    except Exception:  # noqa: BLE001 — do not expose persistence details
                        data.rollback()
                        flask_app.logger.warning('VR profile delete failed')
                        response = _api_error("Couldn't remove the VR profile.", 'internal')
            _finish(response, flask_app, auth)
            return response

    @router.patch('/api/games/{game_uuid}/vr_compat')
    async def patch_game_vr_compat(request: Request, game_uuid: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = authorize(request, write=True, librarian=True)
            if response is None:
                from pydantic import ValidationError

                from oneirodex.schemas.vr import VrCompatBody
                from oneirodex.utils.validation import format_validation_errors

                try:
                    body = VrCompatBody.model_validate(await _json_object(request))
                except ValidationError as exc:
                    response = _api_error(
                        'Invalid request.', 'unprocessable',
                        detail=format_validation_errors(exc),
                    )
                else:
                    game, refusal = data.accessible_game(auth.user, game_uuid)
                    if refusal:
                        response = _api_error(
                            'Game not found' if refusal == 'not_found' else 'Forbidden', refusal,
                        )
                    else:
                        try:
                            response = _ok(data.save_compat(game, body.vr_compat))
                        except Exception:  # noqa: BLE001 — do not expose persistence details
                            data.rollback()
                            flask_app.logger.warning('VR compatibility save failed')
                            response = _api_error("Couldn't save the VR row.", 'internal')
            _finish(response, flask_app, auth)
            return response

    return router


def mount_vr_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_vr_read_router(flask_app, **kwargs))
    return app


def _first(request, key):
    values = request.query_params.getlist(key)
    return values[0] if values else None


def _api_error(message, code, **extra):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, **extra)
    return JSONResponse(payload, status_code=status)


def _ok(payload):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload))


async def _json_object(request):
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' and not (
            content_type.startswith('application/') and content_type.endswith('+json')
        ):
            return {}
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001 — Flask's silent JSON parsing
        return {}
