"""Native FastAPI adapter for the explicitly confirmed database reset API."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


def create_admin_system_reset_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id=None,
    login_manager=None,
    database_scope=None,
    reset_service=None,
    event_logger=None,
) -> APIRouter:
    router = APIRouter()

    @router.post('/admin/api/system/reset')
    async def system_reset(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user
            if user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif normalize_role(getattr(user, 'role', '') or '') != 'admin':
                payload, status = api_error_payload('Admin access required', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden',
                )
                response = JSONResponse(payload, status_code=status)
            else:
                csrf = csrf_error_response(
                    request, auth.session_data, flask_app.config,
                ) if auth.token is None else None
                if csrf is not None:
                    response = csrf
                else:
                    try:
                        body = await request.json()
                    except Exception:
                        body = {}
                    body = body if isinstance(body, dict) else {}
                    service = reset_service or _reset_service()
                    scopes = body.get('scopes')
                    if not isinstance(scopes, list) or not scopes:
                        payload, status = api_error_payload(
                            'Choose at least one thing to reset.', code='bad_request',
                            detail={'valid_scopes': sorted(service.scopes)},
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        unknown = [value for value in scopes if value not in service.scopes]
                        if unknown:
                            payload, status = api_error_payload(
                                f"Unknown reset scope: {', '.join(sorted(unknown))}.",
                                code='bad_request',
                                detail={'valid_scopes': sorted(service.scopes)},
                            )
                            response = JSONResponse(payload, status_code=status)
                        elif body.get('confirm') is None:
                            response = JSONResponse(api_ok_payload(
                                service.plan(scopes), performed=False,
                            ))
                        else:
                            from oneirodex.product import RESET_CONFIRM_PHRASE, is_reset_confirm
                            if not is_reset_confirm(body.get('confirm')):
                                payload, status = api_error_payload(
                                    f'Type "{RESET_CONFIRM_PHRASE}" exactly to confirm.',
                                    code='unprocessable',
                                )
                                response = JSONResponse(payload, status_code=status)
                            else:
                                expanded = service.expand(scopes)
                                audit = event_logger or _event_logger
                                audit(
                                    f"System reset requested (scopes: {', '.join(expanded)})",
                                    event_type='admin_action', event_level='warning',
                                    audit_user=user.id,
                                )
                                try:
                                    result = service.perform(expanded, actor_user_id=user.id)
                                except Exception as exc:  # noqa: BLE001 — no internal details in client response
                                    flask_app.logger.exception('System reset failed')
                                    payload, status = api_error_payload(
                                        'Reset failed and nothing was changed.', code='internal',
                                        detail={'reason': type(exc).__name__},
                                    )
                                    response = JSONResponse(payload, status_code=status)
                                else:
                                    response = JSONResponse(api_ok_payload(result))

            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


class _ResetService:
    @property
    def scopes(self):
        from oneirodex.utils.system_reset import RESET_SCOPES
        return RESET_SCOPES

    def expand(self, scopes):
        from oneirodex.utils.system_reset import expand_scopes
        return expand_scopes(scopes)

    def plan(self, scopes):
        from oneirodex.utils.system_reset import plan_reset
        return plan_reset(scopes)

    def perform(self, scopes, **kwargs):
        from oneirodex.utils.system_reset import perform_reset
        return perform_reset(scopes, **kwargs)


def _reset_service():
    return _ResetService()


def _event_logger(*args, **kwargs):
    from oneirodex.utils.event_logging import log_system_event
    return log_system_event(*args, **kwargs)


def mount_admin_system_reset_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_system_reset_router(flask_app, **kwargs))
    return app
