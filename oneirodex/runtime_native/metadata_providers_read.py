"""Native admin read for metadata-provider configuration."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class MetadataProvidersData:
    def read(self) -> dict:
        from oneirodex.utils.metadata_providers import get_metadata_providers_config

        return get_metadata_providers_config()

    def save(self, payload: dict) -> dict:
        from oneirodex.utils.metadata_providers import save_metadata_providers

        return save_metadata_providers(payload)


def create_metadata_providers_read_router(
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
    data = data_access or MetadataProvidersData()

    @router.api_route('/api/admin/integrations/metadata-providers', methods=['GET', 'HEAD', 'PUT'])
    async def metadata_providers_read(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method == 'PUT':
                from oneirodex.runtime_native.csrf_compat import csrf_error_response
                from oneirodex.runtime_native.request_auth import _lifetime_seconds
                from oneirodex.runtime_native.session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name),
                    flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(
                        flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                    ),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = None
            if csrf_response is None:
                auth = request_auth_context(
                    request,
                    flask_app.config,
                    find_user=find_user,
                    find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id,
                    login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            if csrf_response is not None:
                response = csrf_response
            else:
                assert auth is not None
                user = auth.user
                is_admin = (
                    user is not None
                    and bool(getattr(user, 'is_authenticated', True))
                    and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                )
                if user is None:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'),
                        include_next=True,
                    )
                elif not is_admin:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger',
                        include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif request.method == 'GET' or request.method == 'HEAD':
                    response = JSONResponse(api_ok_payload(data.read()))
                else:
                    try:
                        body = await request.json()
                    except Exception:  # noqa: BLE001 — Flask get_json(silent=True)
                        body = None
                    payload_body = body if isinstance(body, dict) else {}
                    if not payload_body:
                        payload, status = api_error_payload(
                            'No fields to update', code='bad_request'
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            saved = data.save(payload_body)
                        except ValueError as exc:
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        except Exception:  # noqa: BLE001 — keep configuration details private
                            from oneirodex.runtime_native.db_session import native_db as db

                            db.session.rollback()
                            import logging

                            logging.getLogger(__name__).exception(
                                'Could not save metadata-provider settings'
                            )
                            payload, status = api_error_payload(
                                'Could not save metadata-provider settings', code='internal'
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload(saved))
                if auth.should_set_session_cookie:
                    from .acquire_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)

        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_metadata_providers_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_metadata_providers_read_router(flask_app, **kwargs))
    return app
