"""Native admin read for redacted *arr connector configuration."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class ArrConfigData:
    def read(self, *, config) -> dict:
        from oneirodex.utils.arr_connectors import get_arr_config, public_arr_config

        return public_arr_config(get_arr_config(config=config))

    def save(self, payload: dict, *, config) -> dict:
        from oneirodex.utils.arr_connectors import save_arr_config

        return save_arr_config(payload, config=config)


def create_arr_config_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    module_enabled: Callable[..., bool] | None = None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ArrConfigData()
    if module_enabled is None:
        from oneirodex.utils.module_status import arr_module_on

        module_enabled = arr_module_on

    @router.api_route('/api/arr/config', methods=['GET', 'HEAD', 'PUT'])
    async def arr_config(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method == 'PUT':
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            ) if csrf_response is None else None
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user if auth is not None else None
            is_admin = (
                user is not None
                and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
                response = _login_redirect(
                    flask_app,
                    request,
                    login_manager,
                    auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            elif not is_admin:
                response = _login_redirect(
                    flask_app,
                    request,
                    login_manager,
                    auth,
                    message='You must be an admin to access this page.',
                    category='danger',
                    include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden'
                )
                response = JSONResponse(payload, status_code=status)
            elif not module_enabled(config=flask_app.config):
                payload, status = api_error_payload(
                    'Arr module is disabled', code='forbidden'
                )
                response = JSONResponse(payload, status_code=status)
            elif request.method == 'PUT':
                try:
                    payload = await request.json()
                except Exception:
                    payload = {}
                try:
                    data.save(payload if isinstance(payload, dict) else {}, config=flask_app.config)
                    response = JSONResponse(api_ok_payload({
                        'status': 'saved',
                        'config': data.read(config=flask_app.config),
                    }))
                except ValueError as exc:
                    result, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(result, status_code=status)
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    import logging
                    db.session.rollback()
                    logging.getLogger(__name__).warning('Could not save Arr configuration')
                    result, status = api_error_payload('Could not save Arr configuration', code='internal')
                    response = JSONResponse(result, status_code=status)
            else:
                response = JSONResponse(data.read(config=flask_app.config))

        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_arr_config_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_arr_config_router(flask_app, **kwargs))
    return app
