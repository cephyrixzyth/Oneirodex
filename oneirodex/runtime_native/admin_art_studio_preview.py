"""Native FastAPI compatibility route for the deterministic art preview."""
from __future__ import annotations

import base64
import io
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class ArtStudioPreviewData:
    def render(self, **kwargs):
        from oneirodex.utils.cover_art_studio import clamp_title_scale, render_cover_art

        width, height = kwargs['width'], kwargs['height']
        variant = kwargs['variant']
        title, system = kwargs['title'], kwargs['system']
        artistic = kwargs['artistic']
        image = render_cover_art(
            width, height, title=title, system=system, variant=variant,
            artistic=artistic,
            headline_override=kwargs['headline_override'],
            subtitle_override=kwargs['subtitle_override'],
            title_scale=clamp_title_scale(kwargs['title_scale']),
        )
        output = io.BytesIO()
        image.save(output, format='WEBP' if kwargs['format'] == 'webp' else 'PNG', quality=88)
        return output.getvalue()


def create_admin_art_studio_preview_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id=None,
    login_manager=None,
    database_scope=None,
    preview_data=None,
) -> APIRouter:
    router = APIRouter()
    data = preview_data or ArtStudioPreviewData()

    @router.post('/admin/api/art-studio/preview')
    async def preview(request: Request):
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
                from .acquire_status import _login_redirect
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
                        from oneirodex.schemas.admin_art_studio import ArtStudioPreviewBody
                        from oneirodex.utils.validation import format_validation_errors

                        model = ArtStudioPreviewBody.model_validate(body)
                    except ValidationError as exc:
                        from oneirodex.utils.validation import format_validation_errors

                        payload, status = api_error_payload(
                            'Invalid request.', code='unprocessable',
                            detail=format_validation_errors(exc),
                        )
                        response = JSONResponse(payload, status_code=status)
                    except TypeError:
                        payload, status = api_error_payload(
                            'Invalid request.', code='unprocessable', detail={},
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        result, error = _render_preview(model, data)
                        if error is not None:
                            payload, status = api_error_payload(
                                'Invalid request.', code='unprocessable', detail=error,
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(result)

            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def _render_preview(body, data):
    title = body.title
    system = (body.system or '').strip() or None
    try:
        width = int(body.width or 400)
        height = int(body.height or 600)
    except (TypeError, ValueError):
        return None, {'width': 'Input should be a valid integer'}
    width = max(64, min(width, 2048))
    height = max(64, min(height, 2048))
    fmt = (body.format or 'webp').lower()
    if fmt not in ('webp', 'png'):
        fmt = 'webp'
    variant = 'square' if width == height else ('wide' if width > height * 1.4 else 'tile')
    raw = body.artistic
    artistic = raw.strip().lower() not in ('0', 'false', 'no', 'off') \
        if isinstance(raw, str) else bool(raw)
    try:
        content = data.render(
            title=title, system=system, width=width, height=height,
            format=fmt, variant=variant, artistic=artistic,
            headline_override=body.headline, subtitle_override=body.subtitle,
            title_scale=body.title_scale,
        )
    except ValidationError as exc:
        return None, format_validation_errors(exc)
    mime = 'image/webp' if fmt == 'webp' else 'image/png'
    return {
        'preview': f'data:{mime};base64,{base64.b64encode(content).decode("ascii")}',
        'width': width, 'height': height, 'artistic': artistic, 'variant': variant,
    }, None


def mount_admin_art_studio_preview_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_art_studio_preview_router(flask_app, **kwargs))
    return app
