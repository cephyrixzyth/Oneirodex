"""Native member news-feed reads with injectable provider access."""
from __future__ import annotations

import logging
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .request_auth import request_auth_context

_logger = logging.getLogger(__name__)


class NewsFeedData:
    def gaming(self, *, limit: int) -> tuple[list, list[str]]:
        from oneirodex.utils.gaming_news import (
            fetch_gaming_headlines,
        )

        return fetch_gaming_headlines(limit=limit), self.sources()

    def sources(self) -> list[str]:
        from oneirodex.utils.gaming_news import feed_urls, source_name

        return sorted({source_name(url) for url in feed_urls()})

    def connected_stores(self, user_id: int):
        from oneirodex.utils.free_games import connected_stores_for_user

        return connected_stores_for_user(user_id)

    def free_games(self, *, store, limit, connected_stores):
        from oneirodex.utils.free_games import list_active_offers

        return list_active_offers(
            store=store, limit=limit, connected_stores=connected_stores
        )

    def claim_assist(self, offer_id: int, user_id: int):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import FreeGameOffer
        from oneirodex.utils.free_games import claim_assist_for_user

        offer = db.session.execute(
            select(FreeGameOffer).where(FreeGameOffer.id == offer_id)
        ).scalars().first()
        if offer is None:
            return None
        return claim_assist_for_user(user_id, offer)


def create_news_feeds_router(
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
    data = data_access or NewsFeedData()

    @router.api_route('/api/news/gaming', methods=['GET', 'HEAD'])
    def gaming_news(request: Request):
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
                limit = _int_query(request, 'limit', 12) or 12
                try:
                    items, sources = data.gaming(limit=max(1, min(limit, 30)))
                except Exception as exc:
                    _logger.warning('gaming news feed failed: %s', exc)
                    items = []
                    try:
                        sources = data.sources()
                    except Exception:
                        sources = []
                response = JSONResponse({
                    'items': items,
                    'sources': sources,
                    'empty': len(items) == 0,
                })
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.api_route('/api/news/free-games', methods=['GET', 'HEAD'])
    def free_games_news(request: Request):
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
            elif not bool(flask_app.config.get('ENABLE_FREE_GAMES', True)):
                response = JSONResponse({
                    'items': [], 'enabled': False,
                    'connected_stores': [], 'empty': True,
                })
            else:
                store_values = request.query_params.getlist('store')
                store = (store_values[0] if store_values else '').strip() or None
                limit = _int_query(request, 'limit', 40) or 40
                try:
                    connected = data.connected_stores(auth.user.id)
                    items = data.free_games(
                        store=store,
                        limit=max(1, min(limit, 100)),
                        connected_stores=connected,
                    )
                except Exception as exc:
                    _logger.warning('free-games feed failed: %s', exc)
                    response = JSONResponse({
                        'items': [], 'enabled': True,
                        'connected_stores': [], 'empty': True,
                    })
                else:
                    response = JSONResponse({
                        'items': items,
                        'enabled': True,
                        'connected_stores': sorted(connected),
                        'empty': len(items) == 0,
                    })
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    @router.post('/api/news/free-games/{offer_id:int}/claim-assist')
    async def free_games_claim_assist(offer_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from .csrf_compat import csrf_error_response
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            response = (
                None if auth.token is not None
                else csrf_error_response(request, auth.session_data, flask_app.config)
            )
            if response is None and auth.token is not None and not auth.has_scope('write:library'):
                response = _error('Missing scope: write:library', 'forbidden', 403)
            if response is None:
                assert auth is not None
                if auth.user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                elif not bool(flask_app.config.get('ENABLE_FREE_GAMES', True)):
                    response = _error('Free games are switched off', 'forbidden', 403)
                else:
                    try:
                        result = data.claim_assist(offer_id, auth.user.id)
                    except Exception:
                        _logger.exception('free games claim assist failed')
                        response = _error('Ownership assist is unavailable', 'internal', 500)
                    else:
                        if result is None:
                            response = _error('Offer not found', 'not_found', 404)
                        elif not result.get('ok'):
                            response = _error(
                                result.get('error') or 'Ownership assist is not available',
                                'bad_request', 400,
                            )
                        else:
                            from oneirodex.utils.api_contract import api_ok_payload

                            response = JSONResponse(api_ok_payload(result))
            if auth is not None and auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            _finalize(response, flask_app, request)
            return response

    return router


def mount_news_feed_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_news_feeds_router(flask_app, **kwargs))
    return app


def _int_query(request: Request, name: str, default: int) -> int:
    values = request.query_params.getlist(name)
    try:
        return int(values[0]) if values else default
    except (TypeError, ValueError):
        return default


def _finalize(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''


def _error(message: str, code: str, status: int):
    from oneirodex.utils.api_contract import api_error_payload

    payload, _ = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=status)
