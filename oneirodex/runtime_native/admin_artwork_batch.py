"""FastAPI compatibility route for bounded missing-cover AI generation."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class ArtworkBatchData:
    def enabled(self, config):
        return bool(config.get('ENABLE_AI_ARTWORK', False))

    def generate(self, app, body):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Image
        from oneirodex.utils.ai_artwork import generate_and_store_cover

        try:
            limit = min(max(int(body.get('limit') or 10), 1), 50)
        except (TypeError, ValueError):
            raise ValueError('limit must be a number') from None
        query = select(Game)
        if body.get('library_uuid'):
            query = query.filter(Game.library_uuid == body['library_uuid'])
        candidates = db.session.execute(query).scalars().all()
        generated, skipped, errors = [], 0, []
        for game in candidates:
            if len(generated) >= limit:
                break
            cover = db.session.execute(
                select(Image).filter_by(game_uuid=game.uuid, image_type='cover')
            ).scalars().first()
            if cover is not None:
                skipped += 1
                continue
            try:
                result = generate_and_store_cover(
                    game.uuid, image_type='cover', config=app.config,
                )
            except Exception:  # noqa: BLE001 — preserve item-level continuation without leaking internals
                errors.append({'uuid': game.uuid, 'name': game.name, 'error': 'Artwork generation failed'})
                continue
            generated.append({
                'uuid': game.uuid, 'name': game.name,
                'filename': result.get('filename'),
            })
        return {
            'considered': len(candidates), 'generated': len(generated),
            'skipped': skipped, 'failed': len(errors),
            'games': generated, 'errors': errors[:20],
        }


def create_admin_artwork_batch_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, database_scope=None, data_access=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ArtworkBatchData()

    @router.post('/admin/api/artwork/generate/batch')
    async def generate_batch(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif normalize_role(getattr(auth.user, 'role', '') or '') != 'admin':
                payload, status = api_error_payload('Admin access required', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            else:
                csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
                    if auth.token is None else None
                if csrf is not None:
                    response = csrf
                elif not data.enabled(flask_app.config):
                    payload, status = api_error_payload(
                        'Generated artwork is off. Set ENABLE_AI_ARTWORK=true and AI_ARTWORK_URL.',
                        code='forbidden',
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        body = await request.json()
                    except Exception:
                        body = {}
                    try:
                        result = data.generate(flask_app, body if isinstance(body, dict) else {})
                    except ValueError as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    except Exception:
                        payload, status = api_error_payload('Artwork batch generation failed', code='internal')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        response = JSONResponse(api_ok_payload(result))
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_admin_artwork_batch_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_artwork_batch_router(flask_app, **kwargs))
    return app
