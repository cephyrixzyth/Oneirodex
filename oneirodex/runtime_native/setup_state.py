"""Native read-only first-run setup state endpoint."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .request_auth import request_auth_context


def create_setup_state_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.api_route('/api/setup/state', methods=['GET', 'HEAD'])
    def setup_state(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = None
            if request.cookies or request.headers.get('authorization'):
                auth = request_auth_context(
                    request,
                    flask_app.config,
                    find_user=find_user,
                    find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id,
                    login_manager=login_manager,
                )
            from oneirodex.models import LibraryPlatform
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role
            from oneirodex.utils.setup import get_current_setup_step, is_setup_required

            required = is_setup_required()
            step = 1 if required else get_current_setup_step()
            if step is None:
                body = api_ok_payload({'complete': True, 'required': False, 'step': None})
                status = 200
            elif step > 1 and not (
                auth is not None
                and auth.user is not None
                and auth.token is None
                and normalize_role(getattr(auth.user, 'role', None) or '') == 'admin'
            ):
                body, status = api_error_payload(
                    'Sign in with the administrator account created during setup.',
                    code='unauthorized',
                )
            else:
                from oneirodex.utils.setup_projections import state_settings

                body = api_ok_payload({
                    'complete': False,
                    'required': required,
                    'step': step,
                    'platforms': [
                        {'key': item.name, 'label': item.value}
                        for item in LibraryPlatform
                    ],
                    'settings': state_settings() if step > 1 else {},
                })
                status = 200

        from oneirodex.utils.security_headers import security_header_values

        response: Response = JSONResponse(
            body,
            status_code=status,
            headers={'Cache-Control': 'no-store'},
        )
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_setup_state_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_setup_state_router(flask_app, **kwargs))
    return app
