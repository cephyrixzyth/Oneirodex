"""Native FastAPI routes for patch catalog search and guide attachment."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class PatchCatalogData:
    """Adapter isolating provider lookups and DB writes from the router."""

    def enabled(self, app) -> bool:
        return str(app.config.get('ENABLE_PATCH_CATALOG', '')).lower() in {'1', 'true', 'yes', 'on'}

    def game(self, game_uuid: str):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from sqlalchemy import select

        return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

    def search(self, query: str, *, platform=None, region=None, target_lang=None, limit=20):
        from oneirodex.utils.patch_catalog.registry import search_all_patch_providers

        return search_all_patch_providers(query, platform=platform, region=region,
                                           target_lang=target_lang, limit=limit)

    def can_access_game(self, user, game) -> bool:
        from oneirodex.utils.library_acl import user_can_access_game

        return user_can_access_game(user, game)

    def attach(self, game, **kwargs):
        from oneirodex.utils.patch_catalog.attach import attach_patch_guide

        return attach_patch_guide(game, **kwargs)


def create_patch_catalog_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or PatchCatalogData()

    @router.api_route('/api/patch-catalog/search', methods=['GET', 'HEAD'])
    @router.post('/api/patch-catalog/attach')
    async def patch_catalog(request: Request):
        is_search = request.url.path.endswith('/search')
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method == 'POST':
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session, flask_app.config)
            auth = None
            if csrf_response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            if csrf_response is not None:
                response = csrf_response
            else:
                user = auth.user
                is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                if user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth, message=getattr(login_manager, 'login_message', None), category=getattr(login_manager, 'login_message_category', 'message'), include_next=True)
                elif not is_admin:
                    response = _login_redirect(flask_app, request, login_manager, auth, message='You must be an admin to access this page.', category='danger', include_next=False)
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                elif not data.enabled(flask_app):
                    extra = {'hits': []} if is_search else {}
                    payload, status = api_error_payload('Patch catalog is disabled. Set ENABLE_PATCH_CATALOG=true.', code='forbidden', **extra)
                    response = JSONResponse(payload, status_code=status)
                elif is_search:
                    response = _search(request, data, api_error_payload)
                else:
                    body = await _read_json(request)
                    response = _attach(body, auth.user, data, api_error_payload, api_ok_payload)
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)

        from oneirodex.utils.security_headers import security_header_values
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def _search(request, data, api_error_payload):
    params = request.query_params
    query = (params.get('q') or params.get('query') or '').strip()
    game_uuid = (params.get('game_uuid') or '').strip()
    platform = (params.get('platform') or '').strip() or None
    region = (params.get('region') or '').strip() or None
    target_lang = (params.get('target_lang') or '').strip() or None
    if game_uuid and not query:
        game = data.game(game_uuid)
        if game:
            query = getattr(game, 'name', None) or ''
            if not region:
                region = getattr(game, 'rom_region', None)
            if not platform:
                library = getattr(game, 'library', None)
                platform_row = getattr(library, 'platform', None) if library else None
                platform = getattr(platform_row, 'name', None) if platform_row else None
    if not query:
        payload, status = api_error_payload('Query parameter q (or game_uuid) is required', code='bad_request')
        return JSONResponse(payload, status_code=status)
    try:
        limit = min(int(params.get('limit') or 20), 50)
    except (TypeError, ValueError):
        limit = 20
    hits = data.search(query, platform=platform, region=region, target_lang=target_lang, limit=limit)
    from starlette.responses import JSONResponse
    return JSONResponse({'query': query, 'platform': platform, 'region': region,
                         'target_lang': target_lang, 'hits': [hit.to_dict() for hit in hits]})


async def _read_json(request):
    import json
    try:
        length = int(request.headers.get('content-length') or '0')
        if length > 12 * 1024:
            return None
        chunks = bytearray()
        async for part in request.stream():
            chunks.extend(part)
            if len(chunks) > 12 * 1024:
                return None
        value = json.loads(chunks)
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _attach(body, user, data, api_error_payload, api_ok_payload):
    from oneirodex.schemas.patch_catalog import AttachPatchGuideBody
    from pydantic import ValidationError
    try:
        model = AttachPatchGuideBody.model_validate(body)
    except ValidationError as exc:
        errors = exc.errors()
        missing_required_fields = all(
            error.get('type') == 'missing'
            and tuple(error.get('loc') or ()) in {('game_uuid',), ('source_url',)}
            for error in errors
        )
        if missing_required_fields:
            payload, status = api_error_payload(
                'Provide a game UUID and source URL.', code='bad_request'
            )
        else:
            from oneirodex.utils.validation import format_validation_errors

            payload, status = api_error_payload(
                'Invalid request.', code='unprocessable',
                detail=format_validation_errors(exc),
            )
        return JSONResponse(payload, status_code=status)
    game = data.game(model.game_uuid)
    if not game:
        payload, status = api_error_payload('Game not found', code='not_found')
        return JSONResponse(payload, status_code=status)
    if not data.can_access_game(user, game):
        payload, status = api_error_payload('You do not have access to that game', code='forbidden')
        return JSONResponse(payload, status_code=status)
    try:
        result = data.attach(
            game, source_url=model.source_url, notes=model.notes or None,
            target_language=model.target_language or None, patch_format=model.patch_format or None,
        )
    except ValueError as exc:
        payload, status = api_error_payload(str(exc), code='bad_request')
        return JSONResponse(payload, status_code=status)
    return JSONResponse(api_ok_payload(result), status_code=201)


def mount_patch_catalog_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_patch_catalog_router(flask_app, **kwargs))
    return app
