"""Native member identity and shared icon-pack catalogue reads."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request

from .acquire_status import _login_redirect
from .batch_favorite import _finish
from .request_auth import request_auth_context


class MemberMetaData:
    def username_exists(self, username):
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        return db.session.execute(
            select(User).filter(func.lower(User.name) == func.lower(username))
        ).scalars().first() is not None

    def icon_packs(self, user, *, static_url_path='/static'):
        from oneirodex.utils.icon_themes import icon_pack_css_url, list_icon_packs

        current = 'outline'
        if getattr(user, 'preferences', None):
            current = getattr(user.preferences, 'icon_pack', None) or 'outline'
        packs = list_icon_packs()
        for pack in packs:
            pack['css_url'] = icon_pack_css_url(
                pack['id'], static_url_path=static_url_path,
            )
        return {'packs': packs, 'current': current}


def create_member_meta_router(
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
    data = data_access or MemberMetaData()

    def authenticate(request: Request):
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
        )
        response = None
        if auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        return auth, response

    @router.api_route('/api/current_user_role', methods=['GET', 'HEAD'])
    def current_user_role(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = authenticate(request)
            if response is None:
                from starlette.responses import JSONResponse

                response = JSONResponse({'role': auth.user.role})
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/icon-packs', methods=['GET', 'HEAD'])
    def icon_packs(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = authenticate(request)
            if response is None:
                from starlette.responses import JSONResponse

                response = JSONResponse(data.icon_packs(
                    auth.user,
                    static_url_path=getattr(flask_app, 'static_url_path', None) or '/static',
                ))
            _finish(response, flask_app, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/check_username')
    async def check_username(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = authenticate(request)
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                csrf_response = csrf_error_response(request, auth.session_data, flask_app.config)
                if csrf_response is not None:
                    response = csrf_response
            if response is None:
                from pydantic import ValidationError

                from oneirodex.schemas.user import CheckUsernameBody
                from oneirodex.utils.validation import format_validation_errors

                try:
                    body = CheckUsernameBody.model_validate(await _json_object(request))
                except ValidationError as exc:
                    from oneirodex.utils.api_contract import api_error_payload
                    from starlette.responses import JSONResponse

                    payload, status = api_error_payload(
                        'Invalid request.', code='unprocessable',
                        detail=format_validation_errors(exc),
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    from starlette.responses import JSONResponse

                    response = JSONResponse({
                        'exists': data.username_exists(body.username),
                    })
            _finish(response, flask_app, auth)
            return response

    return router


def mount_member_meta_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_member_meta_router(flask_app, **kwargs))
    return app


async def _json_object(request):
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json' and not (
            content_type.startswith('application/') and content_type.endswith('+json')
        ):
            return {}
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001 — match Flask silent JSON handling
        return {}
