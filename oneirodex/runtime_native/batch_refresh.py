"""Native FastAPI implementations of member batch freshness and artwork refresh."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .batch_favorite import _finish, _normalize_uuids
from .request_auth import request_auth_context

BATCH_FRESHNESS_MAX = 50
BATCH_REFRESH_IMAGES_MAX = 20
FRESHNESS_STALE_SECONDS = 86400


class BatchRefreshData:
    def admin_games(self, limit, library_uuid=None, *, fetch_n=None):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        query = select(Game).order_by(Game.name.asc())
        if library_uuid:
            query = query.filter(Game.library_uuid == library_uuid)
        return db.session.execute(query.limit(fetch_n or limit)).scalars().all()

    def state(self, uuids):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return {
            game.uuid: game
            for game in db.session.execute(
                select(Game).filter(Game.uuid.in_(uuids))
            ).scalars().all()
        }

    def game(self, game_uuid):
        return self.state([game_uuid]).get(game_uuid)

    def can_access(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return bool(user_can_access_game(user, game))

    def check_freshness(self, game):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.freshness import check_and_store_freshness

        # Preserve the legacy relationship lazy-loads before calculating data.
        _ = list(game.updates or [])
        _ = list(game.extras or [])
        _ = list(game.urls or [])
        return check_and_store_freshness(game, commit=False, db_session=db.session)

    def enqueue_images(self, flask_app, uuid):
        from oneirodex.utils.background import run_in_background
        from oneirodex.utils.scanning import refresh_images_in_background

        run_in_background(
            flask_app, refresh_images_in_background, uuid, app=flask_app,
            name=f'oneirodex-refresh-images-{str(uuid)[:8]}',
        )

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_batch_refresh_router(
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
    data = data_access or BatchRefreshData()

    @router.post('/api/games/batch/freshness/check')
    async def check_batch_freshness(request: Request):
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
            if response is None:
                payload = await _json_object(request)
                uuids, refusal = _normalize_uuids(
                    payload.get('uuids'), max_size=BATCH_FRESHNESS_MAX,
                )
                if refusal is not None:
                    body, status = refusal
                    response = JSONResponse(body, status_code=status)
                else:
                    only_stale = bool(payload.get('only_stale', True))
            if response is None and not uuids:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload({
                    'updated': [], 'skipped': [], 'errors': [],
                    'limit': BATCH_FRESHNESS_MAX, 'only_stale': only_stale,
                    'requested': 0,
                }))
            if response is None:
                try:
                    games = data.state(uuids)
                    updated, skipped, errors = [], [], []
                    now = datetime.now(timezone.utc)
                    for uuid in uuids:
                        game = games.get(uuid)
                        if game is None:
                            skipped.append({'uuid': uuid, 'reason': 'not_found'})
                            continue
                        if not data.can_access(auth.user, game):
                            skipped.append({'uuid': uuid, 'reason': 'forbidden'})
                            continue
                        if only_stale and game.freshness_checked_at and game.freshness_status:
                            checked = game.freshness_checked_at
                            if checked.tzinfo is None:
                                checked = checked.replace(tzinfo=timezone.utc)
                            if (now - checked).total_seconds() < FRESHNESS_STALE_SECONDS:
                                skipped.append({'uuid': uuid, 'reason': 'fresh'})
                                continue
                        try:
                            public = data.check_freshness(game)
                            updated.append({
                                'uuid': uuid, 'name': game.name,
                                'status': public.get('status'),
                                'confidence': public.get('confidence'),
                            })
                        except Exception as exc:  # noqa: BLE001 — legacy item-level result
                            errors.append({
                                'uuid': uuid, 'name': getattr(game, 'name', None),
                                'error': str(exc),
                            })
                    try:
                        data.commit()
                    except Exception:  # noqa: BLE001 — do not expose DB exception text
                        data.rollback()
                        flask_app.logger.warning('batch freshness commit failed')
                        response = _api_error(
                            'Could not save the change', 'internal', updated=[],
                            skipped=skipped, errors=errors, limit=BATCH_FRESHNESS_MAX,
                        )
                    if response is None:
                        response = JSONResponse({
                            'ok': len(errors) == 0, 'updated': updated,
                            'skipped': skipped, 'errors': errors,
                            'limit': BATCH_FRESHNESS_MAX,
                            'only_stale': only_stale, 'requested': len(uuids),
                            'count': len(updated),
                        })
                except Exception:  # noqa: BLE001 — safe batch-level failure
                    data.rollback()
                    flask_app.logger.warning('batch freshness processing failed')
                    response = _api_error('Could not save the change', 'internal')
            _finish(response, flask_app, auth)
            return response

    @router.post('/api/admin/freshness/refresh')
    async def refresh_all_freshness(request: Request):
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
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            from oneirodex.utils.role_catalog import normalize_role

            if response is None and (
                normalize_role(getattr(auth.user, 'role', None)) != 'admin'
                or (auth.token is not None and not auth.has_scope('admin'))
            ):
                response = _api_error('Admin required', 'forbidden')
            if response is None:
                payload = await _json_object(request)
                entire = bool(payload.get('entire_library') or payload.get('all'))
                limit_raw = payload.get('limit')
                try:
                    limit = (500 if entire and limit_raw is None else
                             min(int(limit_raw or 25), 500))
                except (TypeError, ValueError):
                    response = _api_error('Invalid limit', 'bad_request')
                    limit = 0
                only_stale = bool(payload.get('only_stale', True))
                library_uuid = (payload.get('library_uuid') or '').strip() or None
            if response is None:
                fetch_n = limit * 5 if only_stale else limit
                try:
                    games = data.admin_games(limit, library_uuid, fetch_n=fetch_n)
                    updated, errors = [], []
                    skipped = 0
                    now = datetime.now(timezone.utc)
                    for game in games:
                        if len(updated) >= limit:
                            break
                        if only_stale and game.freshness_checked_at and game.freshness_status:
                            checked = game.freshness_checked_at
                            if checked.tzinfo is None:
                                checked = checked.replace(tzinfo=timezone.utc)
                            if (now - checked).total_seconds() < FRESHNESS_STALE_SECONDS:
                                skipped += 1
                                continue
                        try:
                            public = data.check_freshness(game)
                            updated.append({
                                'uuid': game.uuid, 'name': game.name,
                                'status': public.get('status'),
                            })
                        except Exception as exc:  # noqa: BLE001 — preserve per-game outcomes
                            errors.append({
                                'uuid': game.uuid, 'name': game.name, 'error': str(exc),
                            })
                    try:
                        data.commit()
                    except Exception:  # noqa: BLE001 — don't expose database details
                        data.rollback()
                        flask_app.logger.warning('admin freshness commit failed')
                        response = _api_error('Freshness check failed', 'internal')
                    if response is None:
                        response = JSONResponse({
                            'updated': updated, 'errors': errors,
                            'count': len(updated), 'skipped_fresh': skipped,
                            'library_uuid': library_uuid, 'limit': limit,
                        })
                except Exception:  # noqa: BLE001 — safe bulk-level failure
                    data.rollback()
                    flask_app.logger.warning('admin freshness processing failed')
                    response = _api_error('Freshness check failed', 'internal')
            _finish(response, flask_app, auth)
            return response

    @router.post('/api/games/batch/refresh_images', status_code=202)
    async def refresh_batch_images(request: Request):
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
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None and not _is_librarian(auth.user):
                response = _api_error('Librarian or admin required', 'forbidden')
            if response is None and auth.token is not None and not auth.has_scope('admin'):
                response = _api_error('Librarian or admin required', 'forbidden')
            if response is None:
                payload = await _json_object(request)
                uuids, refusal = _normalize_uuids(
                    payload.get('uuids'), max_size=BATCH_REFRESH_IMAGES_MAX,
                )
                if refusal is not None:
                    body, status = refusal
                    response = JSONResponse(body, status_code=status)
            if response is None and not uuids:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload({
                    'queued': [], 'skipped': [], 'errors': [],
                    'limit': BATCH_REFRESH_IMAGES_MAX, 'requested': 0, 'count': 0,
                }))
            if response is None:
                try:
                    games = data.state(uuids)
                    queued, skipped, errors = [], [], []
                    for uuid in uuids:
                        game = games.get(uuid)
                        if game is None:
                            skipped.append({'uuid': uuid, 'reason': 'not_found'})
                            continue
                        if not data.can_access(auth.user, game):
                            skipped.append({'uuid': uuid, 'reason': 'forbidden'})
                            continue
                        if not getattr(game, 'igdb_id', None):
                            skipped.append({
                                'uuid': uuid, 'reason': 'no_igdb_id', 'name': game.name,
                            })
                            continue
                        try:
                            data.enqueue_images(flask_app, uuid)
                            queued.append({'uuid': uuid, 'name': game.name, 'status': 'queued'})
                        except Exception as exc:  # noqa: BLE001 — legacy item-level result
                            errors.append({
                                'uuid': uuid, 'name': getattr(game, 'name', None),
                                'error': str(exc),
                            })
                    response = JSONResponse({
                        'ok': len(errors) == 0, 'queued': queued,
                        'skipped': skipped, 'errors': errors,
                        'limit': BATCH_REFRESH_IMAGES_MAX,
                        'requested': len(uuids), 'count': len(queued),
                    }, status_code=202)
                except Exception:  # noqa: BLE001 — safe batch-level failure
                    flask_app.logger.warning('batch image refresh processing failed')
                    response = _api_error('Could not queue the image refresh', 'internal')
            _finish(response, flask_app, auth)
            return response

    @router.post('/refresh_game_images/{game_uuid}')
    async def legacy_refresh_game_images(game_uuid: str, request: Request):
        from .csrf_compat import csrf_error_response
        from .oidc_status import _login_redirect, _set_session_cookie
        from oneirodex.utils.role_catalog import normalize_role
        from starlette.responses import RedirectResponse

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None and normalize_role(getattr(auth.user, 'role', '') or '') != 'admin':
                response = _api_error('Admin access required', 'forbidden')
            if response is None and auth.token is not None and not auth.has_scope('admin'):
                response = _api_error('Admin access required', 'forbidden')
            if response is None:
                try:
                    game = data.game(game_uuid)
                    game_name = getattr(game, 'name', None)
                    data.enqueue_images(flask_app, game_uuid)
                    message = f'Game images refresh process started for {game_name}.'
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({
                            'message': message, 'status': 'info',
                        }))
                    else:
                        flashes = list(auth.session_data.get('_flashes') or [])
                        flashes.append(('info', message))
                        auth.session_data['_flashes'] = flashes
                        response = RedirectResponse('/libraries', status_code=302)
                except Exception:
                    flask_app.logger.warning('legacy image refresh queue failed', exc_info=True)
                    response = _api_error('Could not queue the image refresh', 'internal')
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_batch_refresh_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_batch_refresh_router(flask_app, **kwargs))
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


def _api_error(message, code, **extra):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, **extra)
    return JSONResponse(payload, status_code=status)


def _is_librarian(user):
    from oneirodex.utils.role_catalog import role_at_least

    return bool(
        getattr(user, 'is_authenticated', False)
        and role_at_least(getattr(user, 'role', None), 'librarian')
    )
