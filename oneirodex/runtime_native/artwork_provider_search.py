"""Native read-only artwork provider searches."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class ArtworkProviderSearchData:
    """Thin adapter over the existing provider registry and search helpers."""

    def provider(self, provider_id: str):
        from oneirodex.utils.providers import get_provider

        return get_provider(provider_id)

    def pcgamingwiki(self, query: str) -> dict:
        from oneirodex.utils.providers.giantbomb import pcgamingwiki_enrichment

        return pcgamingwiki_enrichment(query)


def create_artwork_provider_search_router(
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
    data = data_access or ArtworkProviderSearchData()

    def authenticate(request: Request):
        return request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )

    def secure(response: Response, request: Request):
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    def error(message: str, code: str, **extra):
        from oneirodex.utils.api_contract import api_error_payload

        payload, status = api_error_payload(message, code=code)
        payload.update(extra)
        return JSONResponse(payload, status_code=status)

    def access_response(request: Request, *, admin_only: bool):
        from oneirodex.utils.role_catalog import normalize_role

        auth = authenticate(request)
        user = auth.user
        if user is None:
            response = _login_redirect(
                flask_app, request, login_manager, auth,
                message=getattr(login_manager, 'login_message', None),
                category=getattr(login_manager, 'login_message_category', 'message'),
                include_next=True,
            )
        elif admin_only and normalize_role(getattr(user, 'role', None) or '') != 'admin':
            response = _login_redirect(
                flask_app, request, login_manager, auth,
                message='You must be an admin to access this page.',
                category='danger', include_next=False,
            )
        elif admin_only and auth.token is not None and not auth.has_scope('admin'):
            response = error('This token does not have the admin scope', 'forbidden')
        else:
            response = None
        return auth, response

    def query_and_limit(request: Request):
        params = request.query_params
        query = (params.get('q') or params.get('query') or '').strip()
        try:
            limit = min(int(params.get('limit') or 20), 50)
        except (TypeError, ValueError):
            limit = 20
        return query, limit

    def search_route(provider_id: str, *, admin_only: bool, kind: bool = False,
                     disabled_message: str | None = None, meta_quest: bool = False):
        async def endpoint(request: Request):
            scope = database_scope(flask_app) if database_scope else nullcontext()
            with scope:
                auth, response = access_response(request, admin_only=admin_only)
                if response is None:
                    query, limit = query_and_limit(request)
                    if not query:
                        response = error('Query parameter q is required', 'bad_request')
                    else:
                        art_kind = None
                        if kind:
                            from oneirodex.utils.image_kinds import (
                                STEAMGRIDDB_SEARCH_KINDS, normalize_image_kind,
                            )

                            art_kind = normalize_image_kind(
                                request.query_params.get('image_type')
                                or request.query_params.get('art_kind')
                                or request.query_params.get('kind'),
                                default='cover',
                            )
                            if art_kind not in STEAMGRIDDB_SEARCH_KINDS:
                                response = error(
                                    'image_type must be cover, logo, or hero', 'bad_request'
                                )
                        if response is None:
                            try:
                                provider = data.provider(provider_id)
                                if not provider.is_enabled():
                                    if meta_quest:
                                        response = error(
                                            'Meta/Quest search requires IGDB credentials.',
                                            'unavailable', provider=provider.id,
                                            hint=provider.config_hint(),
                                        )
                                    else:
                                        response = error(
                                            disabled_message or 'Provider is not configured.',
                                            'unavailable', provider=provider.id,
                                        )
                                else:
                                    results = (
                                        provider.search_artwork(query, limit=limit, art_kind=art_kind)
                                        if kind else provider.search_covers(query, limit=limit)
                                    )
                                    payload = {
                                        'provider': provider.id,
                                        'query': query,
                                        'results': [item.to_dict() for item in results],
                                    }
                                    if kind:
                                        payload['image_type'] = art_kind
                                    if meta_quest:
                                        payload['ownership_only'] = True
                                    response = JSONResponse(payload)
                            except Exception as exc:
                                from oneirodex.utils.providers import ProviderDisabledError

                                if isinstance(exc, ProviderDisabledError):
                                    response = error(
                                        exc.message, 'unavailable', provider=exc.provider_id
                                    )
                                elif isinstance(exc, RuntimeError):
                                    response = error(
                                        str(exc), 'bad_gateway', provider=provider_id
                                    )
                                else:
                                    raise
                if auth.should_set_session_cookie and response is not None:
                    from .acquire_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
            return secure(response, request)

        router.add_api_route(
            f'/api/providers/{provider_id}/search', endpoint,
            methods=['GET', 'HEAD'], name=f'{provider_id}_artwork_search',
        )

    search_route(
        'steamgriddb', admin_only=True, kind=True,
        disabled_message='SteamGridDB is not configured. Set STEAMGRIDDB_API_KEY.',
    )
    search_route(
        'igdb', admin_only=True,
        disabled_message='IGDB is not configured. Set IGDB client ID/secret in Integrations.',
    )
    search_route(
        'giantbomb', admin_only=True,
        disabled_message='GiantBomb is not configured. Set GIANTBOMB_API_KEY.',
    )
    search_route('meta_quest', admin_only=True, meta_quest=True)

    @router.api_route('/api/providers/pcgamingwiki/search', methods=['GET', 'HEAD'])
    def pcgamingwiki_search(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = access_response(request, admin_only=False)
            if response is None:
                query, _limit = query_and_limit(request)
                if not query:
                    response = error('Query parameter q is required', 'bad_request')
                else:
                    try:
                        response = JSONResponse(data.pcgamingwiki(query))
                    except RuntimeError as exc:
                        response = error(str(exc), 'bad_gateway', provider='pcgamingwiki')
            if auth.should_set_session_cookie and response is not None:
                from .acquire_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
        return secure(response, request)

    return router


def mount_artwork_provider_search_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_artwork_provider_search_router(flask_app, **kwargs))
    return app
