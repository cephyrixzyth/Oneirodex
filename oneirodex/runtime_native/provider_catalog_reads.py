"""Native read-only artwork and patch-catalog provider listings."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class ProviderCatalogData:
    """Adapter for provider registries and the patch-catalog config snapshot."""

    def artwork_providers(self) -> list[dict]:
        from oneirodex.utils.providers import list_providers

        return list_providers()

    def patch_catalog(self, config: dict) -> dict:
        from oneirodex.utils.patch_catalog.registry import list_patch_providers

        enabled = str(config.get('ENABLE_PATCH_CATALOG', '')).lower() in (
            '1', 'true', 'yes', 'on'
        )
        return {
            'module_enabled': enabled,
            'catalog_path': (config.get('PATCH_CATALOG_PATH') or '') or None,
            'providers': list_patch_providers(),
        }


def create_provider_catalog_reads_router(
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
    data = data_access or ProviderCatalogData()

    def authenticate(request: Request):
        return request_auth_context(
            request,
            flask_app.config,
            find_user=find_user,
            find_token=find_token,
            commit_token_touch=commit_token_touch,
            load_user_id=load_user_id,
            login_manager=login_manager,
        )

    def secure(response: Response, request: Request):
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    def admin_response(request: Request):
        from oneirodex.utils.api_contract import api_error_payload
        from oneirodex.utils.role_catalog import normalize_role

        auth = authenticate(request)
        user = auth.user
        is_admin = (
            user is not None
            and bool(getattr(user, 'is_authenticated', True))
            and normalize_role(getattr(user, 'role', None) or '') == 'admin'
        )
        if user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
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
        else:
            response = None

        if auth.should_set_session_cookie and response is not None:
            from .acquire_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        return auth, response

    @router.api_route('/api/providers', methods=['GET', 'HEAD'])
    def artwork_providers(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = admin_response(request)
            if response is None:
                response = JSONResponse({'providers': data.artwork_providers()})
                if auth.should_set_session_cookie:
                    from .acquire_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
        return secure(response, request)

    @router.api_route('/api/patch-catalog/providers', methods=['GET', 'HEAD'])
    def patch_catalog_providers(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth, response = admin_response(request)
            if response is None:
                # Keep the legacy raw payload (no api_ok envelope) and field names.
                response = JSONResponse(data.patch_catalog(flask_app.config))
                if auth.should_set_session_cookie:
                    from .acquire_status import _set_session_cookie

                    _set_session_cookie(response, flask_app, auth)
        return secure(response, request)

    return router


def mount_provider_catalog_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_provider_catalog_reads_router(flask_app, **kwargs))
    return app
