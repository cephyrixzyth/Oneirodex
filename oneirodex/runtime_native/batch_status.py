"""Native FastAPI implementation of member multi-select play status."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .batch_favorite import BATCH_FAVORITE_MAX, _api_error, _normalize_uuids
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context

BATCH_STATUS_MAX = BATCH_FAVORITE_MAX
_logger = logging.getLogger(__name__)


class BatchStatusData:
    def state(self, user, uuids):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, user_game_status

        games = {
            game.uuid: game
            for game in db.session.execute(
                select(Game).filter(Game.uuid.in_(uuids))
            ).scalars().all()
        }
        existing = {
            row[0]: row[1]
            for row in db.session.execute(
                select(user_game_status.c.game_uuid, user_game_status.c.status).where(
                    user_game_status.c.user_id == user.id,
                    user_game_status.c.game_uuid.in_(uuids),
                )
            ).all()
        }
        return games, existing

    def can_access(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return bool(user_can_access_game(user, game))

    def write(self, user_id, uuid, *, current, status, now):
        from sqlalchemy import and_, delete

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import user_game_status

        condition = and_(
            user_game_status.c.user_id == user_id,
            user_game_status.c.game_uuid == uuid,
        )
        if status is None:
            db.session.execute(delete(user_game_status).where(condition))
        elif current is not None:
            db.session.execute(
                user_game_status.update().where(condition).values(
                    status=status, updated_at=now,
                )
            )
        else:
            db.session.execute(user_game_status.insert().values(
                user_id=user_id, game_uuid=uuid, status=status, updated_at=now,
            ))

    def status_info(self, status):
        from oneirodex.models import get_status_info

        return get_status_info(status)

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_batch_status_router(
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
    data = data_access if data_access is not None else BatchStatusData()

    @router.post('/api/games/batch/status')
    async def set_batch_status(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is not None and not auth.has_scope('write:library'):
                response = _api_error('Forbidden', 'forbidden')
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                if response is None:
                    response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                payload = await _json_object(request)
                uuids, refusal = _normalize_uuids(payload.get('uuids'), max_size=BATCH_STATUS_MAX)
                if refusal is not None:
                    body, status_code = refusal
                    response = JSONResponse(body, status_code=status_code)
                elif 'status' not in payload:
                    response = _api_error(
                        'status required', 'bad_request', updated=[], skipped=[],
                        errors=[], limit=BATCH_STATUS_MAX,
                    )
                else:
                    raw_status = payload.get('status')
                    if raw_status is None:
                        raw_status = ''
                    if not isinstance(raw_status, str):
                        response = _api_error(
                            'status must be a string', 'bad_request', updated=[],
                            skipped=[], errors=[], limit=BATCH_STATUS_MAX,
                        )
                    else:
                        status = raw_status.strip()
                        from oneirodex.utils.play_status import PLAY_STATUS_VALUES

                        if status not in PLAY_STATUS_VALUES:
                            response = _api_error(
                                'Invalid status value', 'bad_request', updated=[],
                                skipped=[], errors=[], limit=BATCH_STATUS_MAX,
                            )
                if response is None:
                    status_out = status or None
                    status_info = data.status_info(status_out)
                    if not uuids:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({
                            'updated': [], 'skipped': [], 'errors': [],
                            'limit': BATCH_STATUS_MAX, 'status': status_out,
                            'status_info': status_info, 'requested': 0, 'count': 0,
                        }))
                    else:
                        try:
                            games, existing = data.state(auth.user, uuids)
                            updated = []
                            skipped = []
                            errors = []
                            now = datetime.now(timezone.utc)
                            for uuid in uuids:
                                game = games.get(uuid)
                                if game is None:
                                    skipped.append({'uuid': uuid, 'reason': 'not_found'})
                                    continue
                                if not data.can_access(auth.user, game):
                                    skipped.append({'uuid': uuid, 'reason': 'forbidden'})
                                    continue
                                current = existing.get(uuid)
                                if (status_out is None and current is None) or current == status_out:
                                    skipped.append({'uuid': uuid, 'reason': 'already_set'})
                                    continue
                                try:
                                    data.write(
                                        auth.user.id, uuid, current=current,
                                        status=status_out, now=now,
                                    )
                                    if status_out is None:
                                        existing.pop(uuid, None)
                                    else:
                                        existing[uuid] = status_out
                                    updated.append({'uuid': uuid, 'status': status_out})
                                except Exception:  # noqa: BLE001 — keep database details private
                                    errors.append({'uuid': uuid, 'error': 'Could not update play status'})
                            try:
                                data.commit()
                            except Exception:  # noqa: BLE001 — do not expose DB exception text
                                data.rollback()
                                _logger.warning('batch status commit failed')
                                response = _api_error(
                                    'Could not save the play status', 'internal',
                                    updated=[], skipped=skipped, errors=errors,
                                    limit=BATCH_STATUS_MAX, status=status_out,
                                )
                            if response is None:
                                response = JSONResponse({
                                    'ok': len(errors) == 0,
                                    'updated': updated, 'skipped': skipped,
                                    'errors': errors, 'limit': BATCH_STATUS_MAX,
                                    'status': status_out, 'status_info': status_info,
                                    'requested': len(uuids), 'count': len(updated),
                                })
                        except Exception:  # noqa: BLE001 — safe batch-level error
                            data.rollback()
                            _logger.warning('batch status processing failed')
                            response = _api_error('Could not save the play status', 'internal')
            _finish(response, flask_app, auth)
            return response

    return router


def mount_batch_status_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_batch_status_router(flask_app, **kwargs))
    return app


async def _json_object(request):
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' and not (
            content_type.startswith('application/') and content_type.endswith('+json')
        ):
            return {}
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001 — match Flask silent parsing for missing/bad JSON
        return {}


def _finish(response, flask_app, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response
