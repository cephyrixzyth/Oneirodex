"""Native admin API for the optional single-game artwork generator."""
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


class ArtworkGenerationData:
    def enabled(self, config):
        return bool(config.get('ENABLE_AI_ARTWORK', False))

    def generate(self, game_uuid, image_type, config=None):
        from oneirodex.utils.ai_artwork import generate_and_store_cover
        return generate_and_store_cover(
            game_uuid, image_type=image_type, config=config,
        )


def create_admin_artwork_generation_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, database_scope=None, data_access=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ArtworkGenerationData()

    @router.post('/admin/api/artwork/generate')
    async def generate(request: Request):
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
                payload, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden',
                )
                response = JSONResponse(payload, status_code=status)
            else:
                csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
                    if auth.token is None else None
                if csrf is not None:
                    response = csrf
                else:
                    try:
                        body = await request.json()
                    except Exception:
                        body = {}
                    try:
                        from oneirodex.schemas.admin_images import GenerateArtworkBody
                        from oneirodex.utils.validation import format_validation_errors
                        model = GenerateArtworkBody.model_validate(body)
                    except ValidationError as exc:
                        payload, status = api_error_payload(
                            'Invalid request.', code='unprocessable',
                            detail=format_validation_errors(exc),
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        if not data.enabled(flask_app.config):
                            payload, status = api_error_payload(
                                'Generated artwork is off. Set ENABLE_AI_ARTWORK=true and AI_ARTWORK_URL.',
                                code='forbidden',
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            try:
                                result = data.generate(
                                    model.game_uuid, model.image_type or 'cover',
                                    config=flask_app.config,
                                )
                                response = JSONResponse(api_ok_payload(result))
                            except LookupError:
                                payload, status = api_error_payload('Game not found', code='not_found')
                                response = JSONResponse(payload, status_code=status)
                            except ValueError as exc:
                                payload, status = api_error_payload(str(exc), code='bad_request')
                                response = JSONResponse(payload, status_code=status)
                            except Exception as exc:
                                from oneirodex.utils.ai_artwork import ArtworkGenerationError
                                if isinstance(exc, ArtworkGenerationError):
                                    payload, status = api_error_payload(str(exc), code='bad_gateway')
                                    response = JSONResponse(payload, status_code=status)
                                else:
                                    raise
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_admin_artwork_generation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_artwork_generation_router(flask_app, **kwargs))
    return app
