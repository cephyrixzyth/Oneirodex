"""Native path-availability API with the legacy allowed-root policy."""
from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class PathAvailabilityData:
    def allowed_bases(self, flask_app):
        from oneirodex.utils.security import get_allowed_base_directories

        return get_allowed_base_directories(flask_app)

    def validate(self, path, bases, logger=None):
        from oneirodex.utils.security import is_safe_path

        return is_safe_path(path, bases, logger=logger)

    def exists(self, path):
        return Path(path).resolve().exists()


def create_system_path_check_router(
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
    data = data_access or PathAvailabilityData()

    @router.api_route('/api/check_path_availability', methods=['GET', 'HEAD'])
    def check_path_availability(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                path = (request.query_params.get('full_disk_path') or '').strip()
                if not path:
                    response = _error(400, 'bad_request', 'Path parameter required', available=False)
                else:
                    try:
                        bases = data.allowed_bases(flask_app)
                        if not bases:
                            flask_app.logger.error('No allowed base directories configured')
                            response = _error(500, 'internal', 'Service configuration error', available=False)
                        else:
                            safe, message = data.validate(path, bases, flask_app.logger)
                            if not safe:
                                response = _error(403, 'forbidden', message, available=False)
                            else:
                                response = JSONResponse({'available': bool(data.exists(path))})
                    except (OSError, ValueError):
                        flask_app.logger.warning('Path existence check failed for validated path')
                        response = _error(500, 'internal', 'Unable to check path', available=False)
                    except Exception:
                        flask_app.logger.exception('Path availability check failed')
                        response = _error(500, 'internal', 'Unable to check path', available=False)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_system_path_check_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_system_path_check_router(flask_app, **kwargs))
    return app


def _error(status, code, message, **extra):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, **extra)
    return JSONResponse(payload, status_code=resolved)
