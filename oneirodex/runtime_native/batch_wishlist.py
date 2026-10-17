"""Native FastAPI implementation of linked member wishlist batches."""
from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .batch_favorite import _normalize_uuids, _api_error, _finish
from .request_auth import request_auth_context

BATCH_WISHLIST_MAX = 50
_logger = logging.getLogger(__name__)


class BatchWishlistData:
    def can_request_games(self, user):
        from oneirodex.utils.role_catalog import can_request_games

        return bool(can_request_games(user))

    def state(self, user, uuids):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, GameRequest

        games = {
            game.uuid: game
            for game in db.session.execute(
                select(Game).filter(Game.uuid.in_(uuids))
            ).scalars().all()
        }
        pending = db.session.execute(
            select(GameRequest).filter_by(user_id=user.id, status='pending')
        ).scalars().all()
        return games, pending

    def can_access(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return bool(user_can_access_game(user, game))

    def create(self, user_id, title, uuid):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameRequest

        row = GameRequest(
            user_id=user_id, title=title[:255], notes=None,
            status='pending', linked_game_uuid=uuid,
        )
        db.session.add(row)
        db.session.flush()
        return row

    def delete(self, row):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.delete(row)

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def log_created(self, count, *, audit_user=None):
        from oneirodex.utils.event_logging import log_system_event

        log_system_event(
            f'Wishlist batch: {count} request(s) created',
            event_type='game', event_level='information',
            audit_user=audit_user,
        )


def create_batch_wishlist_router(
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
    data = data_access if data_access is not None else BatchWishlistData()

    @router.post('/api/games/batch/wishlist')
    async def set_batch_wishlist(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.token is not None and not auth.has_scope('write:library'):
                response = _api_error('Missing scope: write:library', 'forbidden')
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None and not data.can_request_games(auth.user):
                response = _api_error(
                    'Wishlist requests are not available for this account',
                    'forbidden', updated=[], skipped=[], errors=[],
                    limit=BATCH_WISHLIST_MAX,
                )
            if response is None:
                payload = await _json_object(request)
                action = str(payload.get('action') or 'add').strip().lower()
                if action not in ('add', 'remove'):
                    response = _api_error('action must be add or remove', 'bad_request')
                else:
                    uuids, refusal = _normalize_uuids(
                        payload.get('uuids'), max_size=BATCH_WISHLIST_MAX,
                    )
                    if refusal is not None:
                        body, status = refusal
                        response = JSONResponse(body, status_code=status)
            if response is None and not uuids:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload({
                    'updated': [], 'skipped': [], 'errors': [],
                    'limit': BATCH_WISHLIST_MAX, 'requested': 0,
                    'count': 0, 'action': action,
                }))
            if response is None:
                try:
                    games, pending_rows = data.state(auth.user, uuids)
                    pending_titles = {
                        (row.title or '').strip().lower()
                        for row in pending_rows if row.title
                    }
                    pending_linked = {
                        row.linked_game_uuid for row in pending_rows
                        if row.linked_game_uuid
                    }
                    pending_by_linked = {
                        row.linked_game_uuid: row for row in pending_rows
                        if row.linked_game_uuid
                    }
                    updated, skipped, errors = [], [], []
                    if action == 'remove':
                        for uuid in uuids:
                            row = pending_by_linked.get(uuid)
                            if row is None:
                                skipped.append({'uuid': uuid, 'reason': 'not_pending'})
                                continue
                            try:
                                data.delete(row)
                                updated.append({'uuid': uuid, 'id': row.id})
                            except Exception:  # noqa: BLE001 — preserve legacy item result
                                _logger.warning('wishlist batch remove failed')
                                errors.append({'uuid': uuid, 'error': 'delete_failed'})
                        if updated:
                            data.commit()
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({
                            'updated': updated, 'skipped': skipped, 'errors': errors,
                            'limit': BATCH_WISHLIST_MAX, 'requested': len(uuids),
                            'count': len(updated), 'action': 'remove',
                        }))
                    else:
                        for uuid in uuids:
                            game = games.get(uuid)
                            if game is None:
                                skipped.append({'uuid': uuid, 'reason': 'not_found'})
                                continue
                            if not data.can_access(auth.user, game):
                                skipped.append({'uuid': uuid, 'reason': 'forbidden'})
                                continue
                            title = (game.name or '').strip()
                            if not title:
                                skipped.append({'uuid': uuid, 'reason': 'unavailable'})
                                continue
                            title_key = title.lower()
                            if uuid in pending_linked or title_key in pending_titles:
                                skipped.append({'uuid': uuid, 'reason': 'already_pending'})
                                continue
                            try:
                                row = data.create(auth.user.id, title, uuid)
                                pending_titles.add(title_key)
                                pending_linked.add(uuid)
                                updated.append({
                                    'uuid': uuid, 'request_id': row.id,
                                    'title': row.title, 'status': row.status,
                                })
                            except Exception as exc:  # noqa: BLE001 — item-level result parity
                                errors.append({'uuid': uuid, 'error': str(exc)})
                        try:
                            data.commit()
                        except Exception:  # noqa: BLE001 — do not expose DB exceptions
                            data.rollback()
                            _logger.warning('wishlist batch commit failed')
                            response = _api_error(
                                'Could not save the change', 'internal',
                                updated=[], skipped=skipped, errors=errors,
                                limit=BATCH_WISHLIST_MAX,
                            )
                        if response is None:
                            if updated:
                                try:
                                    data.log_created(
                                        len(updated), audit_user=auth.user.id,
                                    )
                                except Exception:  # noqa: BLE001 — logging is best effort
                                    pass
                            response = JSONResponse({
                                'ok': len(errors) == 0, 'updated': updated,
                                'skipped': skipped, 'errors': errors,
                                'limit': BATCH_WISHLIST_MAX,
                                'requested': len(uuids), 'count': len(updated),
                            })
                except Exception:  # noqa: BLE001 — safe batch-level failure
                    data.rollback()
                    _logger.warning('wishlist batch processing failed')
                    response = _api_error('Could not save the change', 'internal')
            _finish(response, flask_app, auth)
            return response

    return router


def mount_batch_wishlist_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_batch_wishlist_router(flask_app, **kwargs))
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
    except Exception:  # noqa: BLE001 — Flask's silent JSON parsing
        return {}


