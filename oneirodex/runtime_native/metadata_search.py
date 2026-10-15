"""Native admin-only metadata provider search."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context

SUPPORTED_SOURCES = (
    'steam', 'rawg', 'gog', 'epic', 'itch', 'giantbomb', 'mobygames',
    'thegamesdb', 'meta_quest',
)
META_QUEST_ALIASES = frozenset({'meta_quest', 'meta', 'quest'})
MOBYGAMES_ALIASES = frozenset({'mobygames', 'moby'})
THEGAMESDB_ALIASES = frozenset({'thegamesdb', 'tgdb'})


class MetadataSearchData:
    def search(self, source: str, name: str, *, limit: int, include_software: bool, config) -> dict:
        from oneirodex.utils.providers.meta_quest import (
            get_meta_quest_api_mode,
            normalize_meta_quest_source,
            unofficial_graphql_enabled,
        )
        from oneirodex.utils.providers.mobygames import get_mobygames_api_key
        from oneirodex.utils.providers.thegamesdb import get_thegamesdb_api_key
        from oneirodex.utils.secondary_scrapers import (
            search_epic_games, search_giantbomb_games, search_gog_games,
            search_itch_games, search_meta_quest_games, search_mobygames_games,
            search_rawg_games, search_steam_games, search_thegamesdb_games,
        )

        mobygames_key_present = False
        thegamesdb_key_present = False
        if source == 'steam':
            results = search_steam_games(name, limit=limit, include_software=include_software)
        elif source == 'rawg':
            results = search_rawg_games(name, api_key=config.get('RAWG_API_KEY') or None, limit=limit)
        elif source == 'gog':
            results = search_gog_games(name, limit=limit)
        elif source == 'epic':
            results = search_epic_games(name, limit=limit)
        elif source == 'itch':
            results = search_itch_games(name, limit=limit)
        elif source == 'giantbomb':
            results = search_giantbomb_games(name, limit=limit)
        elif source == 'mobygames':
            mobygames_key_present = bool(get_mobygames_api_key())
            results = search_mobygames_games(name, limit=limit)
        elif source == 'thegamesdb':
            thegamesdb_key_present = bool(get_thegamesdb_api_key())
            results = search_thegamesdb_games(name, limit=limit)
        else:
            results = search_meta_quest_games(name, limit=limit)

        payload = {
            'source': source,
            'results': results,
            'ownership_only': source in ('meta_quest', 'epic'),
        }
        if source == 'steam':
            payload['include_software'] = include_software
            payload['note'] = (
                'Steam results may include type=software (emulators/tools). '
                'Use item_kind for badges; never auto-treat software as IGDB Main Game. '
                'Ownership register-only — no DRM download queues.'
            )
        if source == 'mobygames':
            payload.update(needs_key=True, key_configured=mobygames_key_present)
            payload['note'] = (
                'MobyGames Class D metadata search. Select a hit → custom/enrich path. '
                'Not in Stage D scan cascade yet (manual identify only).'
                if mobygames_key_present else
                'MOBYGAMES_API_KEY not configured — empty results. '
                'Set env or GlobalSettings.mobygames_api_key '
                '(https://www.mobygames.com/info/api/). Metadata only — never downloads games.'
            )
        if source == 'thegamesdb':
            payload.update(needs_key=True, key_configured=thegamesdb_key_present)
            payload['note'] = (
                'TheGamesDB Class D metadata search (console-friendly). Select a hit → '
                'custom/enrich path. Not in Stage D scan cascade yet (manual identify only).'
                if thegamesdb_key_present else
                'THEGAMESDB_API_KEY not configured — empty results. Set env or '
                'GlobalSettings.thegamesdb_api_key (https://thegamesdb.net/api/register.php). '
                'Metadata / covers only — never downloads games.'
            )
        if source == 'meta_quest':
            payload['api_mode'] = get_meta_quest_api_mode()
            payload['unofficial_graphql'] = unofficial_graphql_enabled()
        return payload


def create_metadata_search_router(
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
    data = data_access or MetadataSearchData()

    @router.api_route('/api/search_metadata', methods=['GET', 'HEAD'])
    def search_metadata(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload
            from oneirodex.utils.role_catalog import normalize_role

            is_admin = (
                auth.user is not None
                and bool(getattr(auth.user, 'is_authenticated', True))
                and normalize_role(getattr(auth.user, 'role', None) or '') == 'admin'
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not is_admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                body, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden'
                )
                response = JSONResponse(body, status_code=status)
            else:
                params = request.query_params
                name = (params.get('name') or '').strip()
                source_raw = (params.get('source') or '').strip().lower()
                from oneirodex.utils.providers.meta_quest import normalize_meta_quest_source

                source = normalize_meta_quest_source(source_raw) or source_raw
                if source_raw in MOBYGAMES_ALIASES or source == 'moby':
                    source = 'mobygames'
                if source_raw in THEGAMESDB_ALIASES or source == 'tgdb':
                    source = 'thegamesdb'
                try:
                    limit = min(int(params.get('limit') or 10), 20)
                except (TypeError, ValueError):
                    limit = 10
                include_software = (params.get('include_software') or '1').strip().lower() not in ('0', 'false', 'no')
                if not name:
                    body, status = api_error_payload('No game name provided', code='bad_request')
                    response = JSONResponse(body, status_code=status)
                elif (
                    source not in SUPPORTED_SOURCES
                    and source_raw not in META_QUEST_ALIASES
                    and source_raw not in MOBYGAMES_ALIASES
                    and source_raw not in THEGAMESDB_ALIASES
                ):
                    message = (
                        f'Unsupported source. Use one of: {", ".join(SUPPORTED_SOURCES)} '
                        '(aliases: meta, quest, moby, tgdb)'
                    )
                    body, status = api_error_payload(message, code='bad_request')
                    body['sources'] = list(SUPPORTED_SOURCES)
                    response = JSONResponse(body, status_code=status)
                else:
                    if source not in ('meta_quest', 'mobygames', 'thegamesdb') and source_raw in META_QUEST_ALIASES:
                        source = 'meta_quest'
                    try:
                        payload = data.search(
                            source, name, limit=limit,
                            include_software=include_software, config=flask_app.config,
                        )
                    except Exception:  # noqa: BLE001 — don't leak provider responses or config
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Metadata search failed. Check the server log.', code='internal'
                        )
                        response = JSONResponse(body, status_code=status)
                    else:
                        response = JSONResponse(payload)
                if auth.should_set_session_cookie:
                    from .acquire_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)

        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_metadata_search_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_metadata_search_router(flask_app, **kwargs))
    return app
