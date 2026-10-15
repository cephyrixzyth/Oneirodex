"""FastAPI admin adapters for single and batch artwork-provider searches."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class CoverSearchData:
    def game_name(self, game_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        return game.name if game else None

    def search(self, query, providers, limit):
        from oneirodex.utils.cover_selection import search_cover_candidates
        return search_cover_candidates(query, providers=providers, limit_per_provider=limit)

    def image_path(self, config):
        from oneirodex.utils.cover_selection import image_save_path_status
        return image_save_path_status(config)

    def batch_search(self, **kwargs):
        from oneirodex.utils.cover_selection import batch_search_covers
        return batch_search_covers(**kwargs)


def create_admin_cover_search_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, database_scope=None, data_access=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or CoverSearchData()

    @router.post('/admin/api/covers/search')
    async def search_one(request: Request):
        auth, denied, scope = _authorize(
            request, flask_app, find_user, find_token, commit_token_touch,
            load_user_id, login_manager, database_scope,
        )
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
            if auth.token is None else None
        if csrf is not None:
            return _finish(csrf, flask_app, auth, scope)
        try:
            from oneirodex.schemas.admin_images import CoverSearchBody
            from oneirodex.utils.validation import format_validation_errors
            model = CoverSearchBody.model_validate(await _json_object(request))
        except ValidationError as exc:
            response = _validation_error(exc)
            return _finish(response, flask_app, auth, scope)
        game_uuid = (model.game_uuid or '').strip() or None
        query = (model.query or model.q or model.name or '').strip()
        if game_uuid and not query:
            query = data.game_name(game_uuid) or ''
            if not query:
                response = _api_error('Game not found', 'not_found', game_uuid=game_uuid)
                return _finish(response, flask_app, auth, scope)
        if not query:
            response = _api_error('query or game_uuid is required', 'bad_request')
            return _finish(response, flask_app, auth, scope)
        providers = _providers(model.providers)
        try:
            limit = min(int(model.limit or model.limit_per_provider or 8), 20)
        except (TypeError, ValueError):
            limit = 8
        result = data.search(query, providers, limit)
        result = {
            **result, 'game_uuid': game_uuid,
            'image_save_path': data.image_path(flask_app.config),
        }
        return _finish(JSONResponse(result), flask_app, auth, scope)

    @router.post('/admin/api/covers/batch/search')
    async def search_batch(request: Request):
        auth, denied, scope = _authorize(
            request, flask_app, find_user, find_token, commit_token_touch,
            load_user_id, login_manager, database_scope,
        )
        if denied is not None:
            return _finish(denied, flask_app, auth, scope)
        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
            if auth.token is None else None
        if csrf is not None:
            return _finish(csrf, flask_app, auth, scope)
        body = await _json_object(request)
        limit_games = _bounded_int(body.get('limit_games') or body.get('limit'), 25, 100)
        limit_per = _bounded_int(body.get('limit_per_provider'), 5, 15)
        result = data.batch_search(
            library_uuid=(body.get('library_uuid') or '').strip() or None,
            platform=(body.get('platform') or body.get('system') or '').strip() or None,
            service=(body.get('service') or '').strip() or None,
            missing_cover=bool(body.get('missing_cover', True)),
            limit_games=limit_games,
            providers=_providers(body.get('providers')),
            limit_per_provider=limit_per,
            config=flask_app.config,
        )
        return _finish(JSONResponse(result), flask_app, auth, scope)

    return router


def _authorize(request, app, find_user, find_token, commit_token_touch,
               load_user_id, login_manager, database_scope):
    scope = database_scope(app) if database_scope else nullcontext()
    scope.__enter__()
    try:
        auth = request_auth_context(
            request, app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
    except Exception:
        import sys
        scope.__exit__(*sys.exc_info())
        raise
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.role_catalog import normalize_role
    if auth.user is None:
        return auth, _login_redirect(app, request, login_manager, auth), scope
    if normalize_role(getattr(auth.user, 'role', '') or '') != 'admin':
        payload, status = api_error_payload('Admin access required', code='forbidden')
        return auth, JSONResponse(payload, status_code=status), scope
    if auth.token is not None and not auth.has_scope('admin'):
        payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
        return auth, JSONResponse(payload, status_code=status), scope
    return auth, None, scope


async def _json_object(request):
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _providers(raw):
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(value).strip() for value in raw if str(value).strip()]
    text = str(raw).strip()
    return [part.strip() for part in text.split(',') if part.strip()] if text else None


def _bounded_int(raw, default, maximum):
    try:
        return min(int(raw or default), maximum)
    except (TypeError, ValueError):
        return default


def _validation_error(exc):
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.validation import format_validation_errors
    payload, status = api_error_payload(
        'Invalid request.', code='unprocessable', detail=format_validation_errors(exc),
    )
    return JSONResponse(payload, status_code=status)


def _api_error(message, code, **extra):
    from oneirodex.utils.api_contract import api_error_payload
    payload, status = api_error_payload(message, code=code)
    payload.update(extra)
    return JSONResponse(payload, status_code=status)


def _finish(response, app, auth, scope):
    try:
        if auth.should_set_session_cookie:
            _set_session_cookie(response, app, auth)
        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(app.config).items():
            response.headers.setdefault(key, value)
        return response
    finally:
        scope.__exit__(None, None, None)


def mount_admin_cover_search_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_cover_search_router(flask_app, **kwargs))
    return app
