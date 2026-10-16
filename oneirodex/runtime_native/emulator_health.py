"""Native FastAPI read for the installed browser-emulator core inventory."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class EmulatorHealthData:
    def read(self, config):
        from oneirodex.platform import core_is_browser_playable
        from oneirodex.utils.webretro_cores import (
            deferred_core_status, get_effective_installed_cores,
        )

        cores = sorted(get_effective_installed_cores())
        return {
            'installed_cores': cores,
            'pcdos_browser': bool(config.get('ENABLE_PCDOS_BROWSER')),
            'core_checks': {core: core_is_browser_playable(core) for core in cores},
            'deferred_cores': deferred_core_status(),
        }


def create_emulator_health_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or EmulatorHealthData()

    @router.api_route('/api/emulator/health', methods=['GET', 'HEAD'])
    async def emulator_core_health(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                response = JSONResponse(data.read(flask_app.config))
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD' and response.status_code == 200:
                response.body = b''
            return response

    return router


def mount_emulator_health_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_emulator_health_router(flask_app, **kwargs))
    return app
