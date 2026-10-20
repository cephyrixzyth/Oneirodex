"""Native FastAPI implementation of member multi-select favorites."""
from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context

BATCH_FAVORITE_MAX = 100
_logger = logging.getLogger(__name__)


class BatchFavoriteData:
    def state(self, user, uuids):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, user_favorites

        games = {
            game.uuid: game
            for game in db.session.execute(
                select(Game).filter(Game.uuid.in_(uuids))
            ).scalars().all()
        }
        favorite_ids = set(db.session.execute(
            select(user_favorites.c.game_uuid).where(
                user_favorites.c.user_id == user.id,
                user_favorites.c.game_uuid.in_(uuids),
            )
        ).scalars().all())
        return games, favorite_ids

    def can_access(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return bool(user_can_access_game(user, game))

    def set_favorite(self, user, game, favorite):
        if favorite:
            user.favorites.append(game)
        else:
            user.favorites.remove(game)

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_batch_favorite_router(
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
    data = data_access if data_access is not None else BatchFavoriteData()

    @router.post('/api/games/batch/favorite')
    async def set_batch_favorite(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is not None and not auth.has_scope('write:library'):
                response = _error('Forbidden', 'forbidden')
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                if response is None:
                    response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                try:
                    from oneirodex.schemas.game import BatchFavoriteBody
                    from oneirodex.utils.validation import format_validation_errors

                    body = BatchFavoriteBody.model_validate(await _json_object(request))
                except ValidationError as exc:
                    response = _error(
                        'Invalid request.', 'unprocessable',
                        detail=format_validation_errors(exc),
                        updated=[], skipped=[], errors=[], limit=BATCH_FAVORITE_MAX,
                    )
            if response is None:
                uuids, refusal = _normalize_uuids(body.uuids)
                if refusal is not None:
                    payload, status = refusal
                    response = JSONResponse(payload, status_code=status)
                elif not uuids:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload({
                        'ok': True, 'updated': [], 'skipped': [], 'errors': [],
                        'limit': BATCH_FAVORITE_MAX, 'favorite': body.favorite,
                        'requested': 0,
                    }))
                else:
                    try:
                        games, already = data.state(auth.user, uuids)
                        updated = []
                        skipped = []
                        errors = []
                        for uuid in uuids:
                            game = games.get(uuid)
                            if game is None:
                                skipped.append({'uuid': uuid, 'reason': 'not_found'})
                                continue
                            if not data.can_access(auth.user, game):
                                skipped.append({'uuid': uuid, 'reason': 'forbidden'})
                                continue
                            is_favorite = uuid in already
                            if is_favorite == body.favorite:
                                skipped.append({'uuid': uuid, 'reason': 'already_set'})
                                continue
                            try:
                                data.set_favorite(auth.user, game, body.favorite)
                                if body.favorite:
                                    already.add(uuid)
                                else:
                                    already.discard(uuid)
                                updated.append({'uuid': uuid, 'favorite': body.favorite})
                            except Exception:  # noqa: BLE001 — keep database details private
                                errors.append({'uuid': uuid, 'error': 'Could not update favorite'})
                        try:
                            data.commit()
                        except Exception:  # noqa: BLE001 — keep exception details private
                            data.rollback()
                            _logger.warning('batch favorite commit failed')
                            response = _api_error(
                                'Could not save the change', 'internal',
                                updated=[], skipped=skipped, errors=errors,
                                limit=BATCH_FAVORITE_MAX,
                            )
                        if response is None:
                            # Here `ok` means every item had no item-level error;
                            # the legacy partial-success contract is not api_ok.
                            response = JSONResponse({
                                'ok': len(errors) == 0,
                                'updated': updated,
                                'skipped': skipped,
                                'errors': errors,
                                'limit': BATCH_FAVORITE_MAX,
                                'favorite': body.favorite,
                                'requested': len(uuids),
                                'count': len(updated),
                            })
                    except Exception:  # noqa: BLE001 — prevent private DB detail leakage
                        data.rollback()
                        _logger.warning('batch favorite processing failed')
                        response = _api_error('Could not save the change', 'internal')
            _finish(response, flask_app, auth)
            return response

    return router


def mount_batch_favorite_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_batch_favorite_router(flask_app, **kwargs))
    return app


async def _json_object(request):
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' and not (
            content_type.startswith('application/') and content_type.endswith('+json')
        ):
            return {}
        return await request.json()
    except Exception:  # noqa: BLE001 — silent JSON parsing matches Flask
        return {}


def _normalize_uuids(raw, *, max_size=BATCH_FAVORITE_MAX):
    if not isinstance(raw, list):
        return None, ({
            'ok': False, 'error': 'uuids must be a list',
            'updated': [], 'skipped': [], 'errors': [],
        }, 400)
    if len(raw) > max_size:
        return None, ({
            'ok': False,
            'error': f'uuids exceeds limit of {max_size}',
            'limit': max_size,
            'requested': len(raw), 'updated': [], 'skipped': [], 'errors': [],
        }, 400)
    seen = set()
    result = []
    for item in raw:
        uuid = (str(item) if item is not None else '').strip()
        if uuid and uuid not in seen:
            seen.add(uuid)
            result.append(uuid)
    return result, None


def _api_error(message, code, **extra):
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    payload, status = api_error_payload(message, code=code, **extra)
    return JSONResponse(payload, status_code=status)


def _error(message, code, *, detail=None, **extra):
    return _api_error(message, code, detail=detail, **extra)


def _finish(response, flask_app, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response
