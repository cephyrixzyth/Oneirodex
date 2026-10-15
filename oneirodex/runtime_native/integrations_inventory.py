"""Native read-only endpoint for the admin integrations inventory."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class IntegrationsInventoryData:
    """Adapter for readiness summaries; this endpoint does not contact providers."""

    def inventory(self) -> list[dict[str, Any]]:
        from oneirodex.utils.integrations_inventory import build_integrations_inventory

        return build_integrations_inventory()


def create_integrations_inventory_router(
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
    """Build the exact legacy payload under Flask-Login admin authorization."""
    router = APIRouter()
    data = data_access if data_access is not None else IntegrationsInventoryData()

    @router.api_route('/api/admin/integrations/inventory', methods=['GET', 'HEAD'])
    def integrations_inventory(request: Request):
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
            user = auth.user
            if user is None:
                response = _login_redirect(
                    flask_app,
                    request,
                    login_manager,
                    auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            else:
                from oneirodex.utils.role_catalog import normalize_role

                is_admin = (
                    bool(getattr(user, 'is_authenticated', True))
                    and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                )
                if is_admin and auth.token is not None and not auth.has_scope('admin'):
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
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
                else:
                    rows = data.inventory()
                    response = JSONResponse({
                        'integrations': rows,
                        'count': len(rows),
                        'hub_href': '/admin/integrations',
                    })

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_integrations_inventory_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_integrations_inventory_router(flask_app, **kwargs))
    return app
