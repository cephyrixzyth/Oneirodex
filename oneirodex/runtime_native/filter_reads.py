"""Native FastAPI read routes for member filter catalogues."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class FilterReadData:
    def __init__(self, flask_app):
        self.flask_app = flask_app

    def bundle(self, user):
        from oneirodex.utils.cache import cache
        from oneirodex.models import GameMode, Genre, PlayerPerspective, Theme
        from oneirodex.utils.filter_catalog import (
            igdb_platforms_payload,
            libraries_payload,
            library_platforms_payload,
            ownership_store_options,
            taxonomy_list,
        )

        cache_key = f'filters_bundle_u{user.id}'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        static_url = str(self.flask_app.static_url_path or '/static').rstrip('/')
        app_root = str(self.flask_app.config.get('APPLICATION_ROOT') or '').rstrip('/')
        static_url = f'{app_root}{static_url}/newstyle/default_library.jpg'
        payload = {
            'libraries': libraries_payload(user, fallback_image_url=static_url),
            'libraryPlatforms': library_platforms_payload(
                user, include_completion=False,
            ),
            'igdbPlatforms': igdb_platforms_payload(),
            'genres': taxonomy_list(Genre),
            'themes': taxonomy_list(Theme),
            'gameModes': taxonomy_list(GameMode),
            'playerPerspectives': taxonomy_list(PlayerPerspective),
            'ownershipStores': ownership_store_options(),
        }
        cache.set(cache_key, payload, timeout=60)
        return payload

    def library_platforms(self, user, *, include_completion: bool):
        from oneirodex.utils.filter_catalog import library_platforms_payload

        return library_platforms_payload(user, include_completion=include_completion)

    def taxonomy(self, name: str):
        from oneirodex.models import GameMode, Genre, PlayerPerspective, Theme
        from oneirodex.utils.filter_catalog import igdb_platforms_payload, taxonomy_list

        if name == 'igdb_platforms':
            return igdb_platforms_payload()
        model = {
            'genres': Genre,
            'themes': Theme,
            'game_modes': GameMode,
            'player_perspectives': PlayerPerspective,
        }[name]
        return taxonomy_list(model)


def create_filter_reads_router(
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
    data = data_access if data_access is not None else FilterReadData(flask_app)

    @router.api_route('/api/filters/bundle', methods=['GET', 'HEAD'])
    def filters_bundle(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                try:
                    response = JSONResponse(data.bundle(auth.user))
                except Exception:  # noqa: BLE001 — keep filter failures private
                    response = _api_error('Database error retrieving filters', 'internal')
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/library_platforms', methods=['GET', 'HEAD'])
    def library_platforms(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                raw = _first_query_value(request, 'include_completion') or '0'
                include_completion = raw in ('1', 'true', 'yes')
                try:
                    response = JSONResponse(data.library_platforms(
                        auth.user, include_completion=include_completion,
                    ))
                except Exception:  # noqa: BLE001 — keep filter failures private
                    response = _api_error('Database error retrieving library platforms', 'internal')
            _finish(response, flask_app, request, auth)
            return response

    for catalogue in ('genres', 'themes', 'game_modes', 'player_perspectives', 'igdb_platforms'):
        async def taxonomy(request: Request, _catalogue=catalogue):
            scope = database_scope(flask_app) if database_scope else nullcontext()
            with scope:
                auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                             load_user_id, login_manager)
                response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
                if response is None:
                    try:
                        response = JSONResponse(data.taxonomy(_catalogue))
                    except Exception:  # noqa: BLE001 — do not return DB driver details
                        if _catalogue == 'igdb_platforms':
                            message = 'Database error retrieving igdb platforms'
                        else:
                            message = f'Error retrieving {_catalogue}'
                        response = _api_error(message, 'internal')
                _finish(response, flask_app, request, auth)
                return response

        router.add_api_route(f'/api/{catalogue}', taxonomy, methods=['GET', 'HEAD'])

    return router


def mount_filter_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_filter_reads_router(flask_app, **kwargs))
    return app


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _api_error(message: str, code: str):
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


def _first_query_value(request: Request, name: str) -> str | None:
    values = request.query_params.getlist(name)
    return values[0] if values else None


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
