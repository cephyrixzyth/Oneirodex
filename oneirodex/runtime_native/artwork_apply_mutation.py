"""Native admin artwork-apply mutation with bounded input and adapter seams."""
from __future__ import annotations

from contextlib import nullcontext
import json
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class ArtworkApplyData:
    def game_exists(self, game_uuid: str) -> bool:
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(select(Game.uuid).filter_by(uuid=game_uuid)).scalar_one_or_none() is not None

    def apply(self, game_uuid: str, url: str, *, provider_id: str, image_type: str):
        from oneirodex.utils.artwork_apply import apply_cover_from_url

        return apply_cover_from_url(
            game_uuid, url, provider_id=provider_id, image_type=image_type,
        )


def create_artwork_apply_router(
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
    data = data_access or ArtworkApplyData()

    @router.post('/api/games/{game_uuid}/artwork/steamgriddb')
    async def apply_artwork(game_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from .csrf_compat import csrf_error_response
            from .request_auth import _lifetime_seconds
            from .session_compat import load_session_cookie
            from oneirodex.utils.api_contract import api_error_payload

            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session = load_session_cookie(
                request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            response = csrf_error_response(request, session, flask_app.config)
            auth = None
            if response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user,
                    find_token=find_token, commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                )
                from oneirodex.utils.role_catalog import normalize_role
                if auth.user is None:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'),
                        include_next=True,
                    )
                elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden',
                    )
                    response = JSONResponse(payload, status_code=status)

            if response is None:
                try:
                    content_length = int(request.headers.get('content-length') or '0')
                except ValueError:
                    content_length = 0
                if content_length > 16 * 1024:
                    payload, status = api_error_payload('Request payload is too large', code='payload_too_large')
                    response = JSONResponse(payload, status_code=status)
                else:
                    raw = bytearray()
                    media_type = str(request.headers.get('content-type') or '').partition(';')[0].strip().lower()
                    is_json = media_type == 'application/json' or (
                        media_type.startswith('application/') and media_type.endswith('+json')
                    )
                    if is_json:
                        async for chunk in request.stream():
                            raw.extend(chunk)
                            if len(raw) > 16 * 1024:
                                break
                    if len(raw) > 16 * 1024:
                        payload, status = api_error_payload('Request payload is too large', code='payload_too_large')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            body = json.loads(raw) if raw else {}
                            if not isinstance(body, dict):
                                body = {}
                            from oneirodex.schemas.providers import ApplyArtworkBody
                            from oneirodex.utils.validation import format_validation_errors
                            model = ApplyArtworkBody.model_validate(body)
                        except (ValueError, UnicodeDecodeError, ValidationError) as exc:
                            payload, status = api_error_payload(
                                'Invalid request.', code='unprocessable',
                                detail=format_validation_errors(exc) if isinstance(exc, ValidationError) else {'__root__': 'Invalid JSON object'},
                            )
                            response = JSONResponse(payload, status_code=status)

                if response is None:
                    if not data.game_exists(game_uuid):
                        payload, status = api_error_payload('Game not found', code='not_found', game_uuid=game_uuid)
                        response = JSONResponse(payload, status_code=status)
                    else:
                        from oneirodex.utils.image_kinds import image_kinds_error_message, parse_image_kind
                        provider_id = (model.provider or 'steamgriddb').strip().lower() or 'steamgriddb'
                        try:
                            image_type = parse_image_kind(model.image_type or model.kind, default='cover')
                        except ValueError:
                            payload, status = api_error_payload(image_kinds_error_message(), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        if response is None and provider_id not in ('steamgriddb', 'igdb'):
                            payload, status = api_error_payload('provider must be steamgriddb or igdb', code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        if response is None and provider_id == 'igdb' and image_type != 'cover':
                            payload, status = api_error_payload('IGDB only supports image_type=cover', code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        if response is None:
                            try:
                                result = data.apply(game_uuid, model.url, provider_id=provider_id, image_type=image_type)
                                response = JSONResponse(result, status_code=200)
                            except ValueError as exc:
                                payload, status = api_error_payload(str(exc), code='bad_request', game_uuid=game_uuid)
                                response = JSONResponse(payload, status_code=status)
                            except LookupError as exc:
                                payload, status = api_error_payload(str(exc), code='not_found', game_uuid=game_uuid)
                                response = JSONResponse(payload, status_code=status)
                            except Exception as exc:
                                from oneirodex.utils.providers import ProviderDisabledError
                                if isinstance(exc, ProviderDisabledError):
                                    payload, status = api_error_payload(
                                        exc.message, code='unavailable', provider=exc.provider_id,
                                    )
                                    response = JSONResponse(payload, status_code=status)
                                elif isinstance(exc, RuntimeError):
                                    payload, status = api_error_payload(
                                        str(exc), code='unavailable', game_uuid=game_uuid,
                                    )
                                    response = JSONResponse(payload, status_code=status)
                                else:
                                    from oneirodex.runtime_native.db_session import native_db as db
                                    db.session.rollback()
                                    payload, status = api_error_payload(
                                        'Failed to apply artwork', code='bad_gateway', game_uuid=game_uuid,
                                    )
                                    response = JSONResponse(payload, status_code=status)

            if auth is not None and auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)

        from oneirodex.utils.security_headers import security_header_values
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        return response

    return router


def mount_artwork_apply_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_artwork_apply_router(flask_app, **kwargs))
    return app
