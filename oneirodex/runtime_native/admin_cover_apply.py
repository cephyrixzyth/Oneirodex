"""FastAPI admin action for applying a provider cover URL to a game."""
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


class CoverApplyData:
    def path_status(self, config):
        from oneirodex.utils.cover_selection import image_save_path_status
        return image_save_path_status(config)

    def apply(self, app, game_uuid, url, provider_id):
        from oneirodex.utils.artwork_apply import apply_cover_from_url
        return apply_cover_from_url(
            game_uuid, url, provider_id=provider_id, image_type='cover',
            config=app.config,
        )


def create_admin_cover_apply_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, database_scope=None, data_access=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or CoverApplyData()

    @router.post('/admin/api/covers/apply')
    async def apply_cover(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload
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
                else:
                    try:
                        from oneirodex.schemas.admin_images import ApplyCoverBody
                        from oneirodex.utils.validation import format_validation_errors
                        body = await request.json()
                        model = ApplyCoverBody.model_validate(body)
                    except ValidationError as exc:
                        payload, status = api_error_payload(
                            'Invalid request.', code='unprocessable',
                            detail=format_validation_errors(exc),
                        )
                        response = JSONResponse(payload, status_code=status)
                    except Exception:
                        payload, status = api_error_payload(
                            'Invalid request.', code='unprocessable',
                            detail={'__root__': 'Invalid JSON object'},
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        path_status = data.path_status(flask_app.config)
                        if not path_status.get('writable'):
                            payload, status = api_error_payload(
                                path_status.get('error') or 'IMAGE_SAVE_PATH is not writable',
                                code='unavailable', image_save_path=path_status,
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            game_uuid = model.game_uuid
                            provider_id = (model.provider or 'steamgriddb').strip().lower() or 'steamgriddb'
                            try:
                                result = data.apply(
                                    flask_app, game_uuid, model.url, provider_id,
                                )
                                response = JSONResponse({**result, 'image_save_path': path_status})
                            except ValueError as exc:
                                payload, status = api_error_payload(
                                    str(exc), code='bad_request', game_uuid=game_uuid,
                                )
                                response = JSONResponse(payload, status_code=status)
                            except LookupError as exc:
                                payload, status = api_error_payload(
                                    str(exc), code='not_found', game_uuid=game_uuid,
                                )
                                response = JSONResponse(payload, status_code=status)
                            except Exception as exc:
                                from oneirodex.utils.providers import ProviderDisabledError
                                if isinstance(exc, ProviderDisabledError):
                                    payload, status = api_error_payload(
                                        exc.message, code='unavailable', provider=exc.provider_id,
                                    )
                                elif isinstance(exc, RuntimeError):
                                    payload, status = api_error_payload(
                                        str(exc), code='unavailable', game_uuid=game_uuid,
                                    )
                                else:
                                    payload, status = api_error_payload(
                                        'Failed to apply artwork', code='bad_gateway',
                                        game_uuid=game_uuid,
                                    )
                                response = JSONResponse(payload, status_code=status)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            response.headers.setdefault('Cache-Control', 'no-store')
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_admin_cover_apply_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_cover_apply_router(flask_app, **kwargs))
    return app
