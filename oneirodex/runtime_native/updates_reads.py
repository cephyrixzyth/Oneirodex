"""Native FastAPI read routes for freshness inbox and store search."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class UpdateReadData:
    def inbox(self, user, *, limit: int, library_uuid: str | None) -> dict:
        from sqlalchemy import or_, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, GameExtra, GameUpdate
        from oneirodex.utils.update_projections import batch_local_packs, dlc_summary
        from oneirodex.utils.library_acl import apply_game_access_filters
        from oneirodex.utils.lifecycle import web_client_connected

        query = select(Game).filter(or_(
            Game.freshness_status == 'behind',
            Game.freshness_status == 'heuristic_behind',
        ))
        query = apply_game_access_filters(query, user)
        query = query.order_by(Game.name.asc()).limit(limit)
        if library_uuid:
            query = query.filter(Game.library_uuid == library_uuid)
        games = db.session.execute(query).scalars().all()
        packs_by_game = batch_local_packs(
            db.session, GameUpdate, GameExtra, [game.uuid for game in games]
        )
        connected = web_client_connected(user_id=user.id)
        items = []
        for game in games:
            packs = packs_by_game.get(game.uuid) or []
            latest_update = next((pack for pack in packs if pack['kind'] == 'update'), None)
            latest_extra = next((pack for pack in packs if pack['kind'] == 'extra'), None)
            items.append({
                'uuid': game.uuid,
                'name': game.name,
                'freshness_status': game.freshness_status,
                'freshness_confidence': game.freshness_confidence,
                'local_version': game.local_version,
                'remote_version_summary': game.remote_version_summary,
                'freshness_checked_at': (
                    game.freshness_checked_at.isoformat() if game.freshness_checked_at else None
                ),
                'library_uuid': game.library_uuid,
                'steam_app_id': getattr(game, 'steam_app_id', None),
                'updates_count': sum(1 for pack in packs if pack['kind'] == 'update'),
                'extras_count': sum(1 for pack in packs if pack['kind'] == 'extra'),
                'local_packs': packs,
                'latest_update': latest_update,
                'latest_extra': latest_extra,
                'dlc': dlc_summary(game),
                'client_connected': connected,
            })
        return {
            'count': len(items),
            'limit': limit,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'items': items,
            'freshness_check': {
                'single': 'POST /api/games/<uuid>/freshness/check',
                'batch_member': 'POST /api/games/batch/freshness/check',
                'batch_member_limit': 50,
                'bulk_admin': 'POST /api/admin/freshness/refresh',
                'only_stale_default': True,
                'note': (
                    'Inbox reads stored freshness_status only; poll this endpoint for UI '
                    'auto-refresh, then call freshness/check, member batch, or admin refresh '
                    'to re-probe stores.'
                ),
            },
        }

    def store_search(self, user, *, name: str, source: str, limit: int) -> dict:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.library_acl import apply_game_access_filters
        from oneirodex.utils.secondary_scrapers import search_gog_games, search_steam_games

        results = []
        if source in ('steam', 'all'):
            for hit in search_steam_games(name, limit=limit):
                results.append({
                    'source': 'steam', 'name': hit.get('name'),
                    'url': hit.get('url') or hit.get('store_url'),
                    'steam_app_id': hit.get('steam_app_id') or hit.get('app_id'),
                    'score': hit.get('score'),
                })
        if source in ('gog', 'all'):
            for hit in search_gog_games(name, limit=limit):
                results.append({
                    'source': 'gog', 'name': hit.get('name'),
                    'url': hit.get('url') or hit.get('store_url'),
                    'gog_id': hit.get('gog_id') or hit.get('id'),
                    'score': hit.get('score'),
                })
        steam_ids = {
            int(row['steam_app_id']) for row in results
            if row.get('source') == 'steam'
            and str(row.get('steam_app_id') or '').isdigit()
        }
        games_by_steam = {}
        if steam_ids:
            query = apply_game_access_filters(
                select(Game).filter(Game.steam_app_id.in_(list(steam_ids))), user
            )
            for game in db.session.execute(query).scalars().all():
                if game.steam_app_id is not None:
                    games_by_steam[int(game.steam_app_id)] = game
        name_keys = {
            (row.get('name') or '').strip().lower()
            for row in results if row.get('name')
        }
        games_by_name = {}
        if name_keys:
            query = apply_game_access_filters(select(Game), user).limit(2000)
            for game in db.session.execute(query).scalars().all():
                key = (game.name or '').strip().lower()
                if key in name_keys and key not in games_by_name:
                    games_by_name[key] = game
        for row in results:
            matched = None
            steam_id = row.get('steam_app_id')
            if steam_id is not None and str(steam_id).isdigit():
                matched = games_by_steam.get(int(steam_id))
            if matched is None:
                matched = games_by_name.get((row.get('name') or '').strip().lower())
            row['matched_game_uuid'] = matched.uuid if matched is not None else None
            row['matched_game_name'] = matched.name if matched is not None else None
            row['library_url'] = f'/game_details/{matched.uuid}' if matched is not None else None
        return {'q': name, 'source': source, 'results': results[:limit * 2]}


def create_update_reads_router(
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
    data = data_access if data_access is not None else UpdateReadData()

    @router.api_route('/api/updates/inbox', methods=['GET', 'HEAD'])
    def updates_inbox(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                limit_value = _first(request, 'limit')
                try:
                    limit = min(int(limit_value or 50), 200)
                except (TypeError, ValueError):
                    limit = 50
                limit = max(1, limit)
                library_uuid = (_first(request, 'library_uuid') or '').strip() or None
                response = JSONResponse(data.inbox(
                    auth.user, limit=limit, library_uuid=library_uuid,
                ))
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/updates/store_search', methods=['GET', 'HEAD'])
    def updates_store_search(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                name = (_first(request, 'q') or _first(request, 'name') or '').strip()
                source = (_first(request, 'source') or 'all').strip().lower()
                limit_value = _first(request, 'limit')
                try:
                    limit = min(int(limit_value or 8), 10)
                except (TypeError, ValueError):
                    limit = 8
                if not name:
                    response = _error('q required', 'bad_request')
                elif source not in ('steam', 'gog', 'all'):
                    response = _error('source must be steam, gog, or all', 'bad_request')
                else:
                    response = JSONResponse(data.store_search(
                        auth.user, name=name, source=source, limit=limit,
                    ))
            _finish(response, flask_app, request, auth)
            return response

    return router


def mount_update_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_update_reads_router(flask_app, **kwargs))
    return app


def _first(request, key):
    values = request.query_params.getlist(key)
    return values[0] if values else None


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _error(message, code):
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
