"""Native FastAPI read endpoint for admin *arr connector readiness."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class ArrStatusData:
    """Adapter around existing feature flags and connector readiness probes."""

    def status(self, *, config=None) -> dict:
        from oneirodex.utils.arr_connectors import connector_status
        from oneirodex.utils.arr_hardlink_pipeline import (
            hardlink_apply_allowed,
            hardlink_helpers_enabled,
            pipeline_enabled,
        )
        from oneirodex.utils.module_status import arr_module_on

        enabled = arr_module_on(config=config)
        connectors = connector_status(config=config) if enabled else []
        configured = any(connector.get('configured') for connector in connectors)
        return {
            'enabled': enabled,
            'module': 'arr',
            'status': 'ready' if enabled and configured else 'enabled' if enabled else 'disabled',
            'message': (
                'Arr module ready — configure native indexers, presets, and optional '
                'Prowlarr/Jackett hubs in Admin → Arr.'
                if enabled
                else 'Arr module is disabled. Set ENABLE_ARR_MODULE=true or enable in Admin.'
            ),
            'connectors': connectors,
            'hardlink_pipeline_enabled': pipeline_enabled(config=config),
            'hardlink_helpers_enabled': hardlink_helpers_enabled(config=config),
            'hardlink_apply_allowed': hardlink_apply_allowed(config=config),
            'indexer_warnings': next(
                (connector.get('warnings') or [] for connector in connectors
                 if connector.get('id') == 'native_indexers'),
                [],
            ),
        }


def create_arr_status_router(
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
    """Create native GET/HEAD route matching the legacy ``arr`` blueprint."""
    router = APIRouter()
    data = data_access or ArrStatusData()

    @router.api_route('/api/arr/status', methods=['GET', 'HEAD'])
    def arr_status(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _anonymous_login_redirect(
                    flask_app, request, login_manager, auth
                )
            else:
                from oneirodex.utils.role_catalog import normalize_role

                is_admin = (
                    bool(getattr(auth.user, 'is_authenticated', True))
                    and normalize_role(getattr(auth.user, 'role', None) or '') == 'admin'
                )
                if is_admin and auth.token is not None and not auth.has_scope('admin'):
                    from oneirodex.utils.api_contract import api_error_payload
                    from starlette.responses import JSONResponse

                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif not is_admin:
                    response = _admin_denied_redirect(flask_app, request, auth)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload
                    from starlette.responses import JSONResponse

                    response = JSONResponse(api_ok_payload(
                        data.status(config=flask_app.config)
                    ))

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_arr_status_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_arr_status_router(flask_app, **kwargs))
    return app


def _anonymous_login_redirect(flask_app, request, login_manager, auth_context):
    configured = getattr(login_manager, 'blueprint_login_views', {}) or {}
    view = configured.get('arr') or getattr(login_manager, 'login_view', None)
    compatible_manager = SimpleNamespace(
        login_view=view,
        blueprint_login_views={'apis': view} if view else {},
        login_message=getattr(login_manager, 'login_message', None),
        login_message_category=getattr(login_manager, 'login_message_category', 'message'),
        localize_callback=getattr(login_manager, 'localize_callback', None),
    )
    return _login_redirect(
        flask_app,
        request,
        compatible_manager,
        auth_context,
        message=compatible_manager.login_message,
        category=compatible_manager.login_message_category,
        include_next=True,
    )


def _admin_denied_redirect(flask_app, request, auth_context):
    manager = SimpleNamespace(
        login_view='login.login',
        blueprint_login_views={'apis': 'login.login'},
        login_message=None,
        login_message_category='danger',
        localize_callback=None,
    )
    return _login_redirect(
        flask_app,
        request,
        manager,
        auth_context,
        message='You must be an admin to access this page.',
        category='danger',
        include_next=False,
    )
