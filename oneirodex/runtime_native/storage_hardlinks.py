"""Native admin API for guarded hardlink preview and apply."""
from __future__ import annotations

from contextlib import nullcontext
import logging
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class StorageHardlinksData:
    def paths_allowed(self, source: str, dest: str, *, app) -> tuple[bool, str | None]:
        from oneirodex.utils.security import get_allowed_base_directories, is_safe_path

        bases = get_allowed_base_directories(app)
        ok_source, source_error = is_safe_path(source, bases, logger=logging.getLogger(__name__))
        if not ok_source:
            return False, source_error or 'Unsafe source path'
        ok_dest, dest_error = is_safe_path(dest, bases, logger=logging.getLogger(__name__))
        if not ok_dest:
            return False, dest_error or 'Unsafe destination path'
        return True, None

    def preview(self, source: str, dest: str):
        from oneirodex.utils.hardlinks import preview_hardlink

        return preview_hardlink(source, dest)

    def apply(self, source: str, dest: str):
        from oneirodex.utils.hardlinks import apply_hardlink

        return apply_hardlink(source, dest)

    def audit(self, source: str, dest: str, *, audit_user: int | str | None = None):
        from oneirodex.utils.event_logging import log_system_event

        log_system_event(
            f'Hardlink created: {source} -> {dest}',
            event_type='audit', event_level='information', audit_user=audit_user,
        )


def create_storage_hardlinks_router(
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
    data = data_access or StorageHardlinksData()

    @router.post('/api/storage/hardlink/preview')
    @router.post('/api/storage/hardlink/apply')
    async def hardlink(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from .csrf_compat import csrf_error_response
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            csrf_response = (
                None if auth.token is not None
                else csrf_error_response(request, auth.session_data, flask_app.config)
            )
            if csrf_response is not None:
                response = csrf_response
            else:
                assert auth is not None
                from oneirodex.utils.role_catalog import normalize_role

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
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    response = _api_error('This token does not have the admin scope', 'forbidden', 403)
                else:
                    response = await _handle_hardlink_request(request, flask_app, data, auth.user)

            if auth is not None and auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            response.headers.setdefault('Cache-Control', 'no-store')
            response.headers.setdefault('Vary', 'Cookie')
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


async def _handle_hardlink_request(request: Request, flask_app, data, actor) -> JSONResponse:
    from oneirodex.schemas.storage import HardlinkBody
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.validation import format_validation_errors

    is_apply = request.url.path.endswith('/apply')
    config = flask_app.config
    enabled = str(config.get('ENABLE_HARDLINK_HELPERS', '')).lower() in {'1', 'true', 'yes', 'on'}
    apply_enabled = enabled and str(config.get('ALLOW_HARDLINK_APPLY', '')).lower() in {
        '1', 'true', 'yes', 'on',
    }
    try:
        body_data = await request.json()
    except Exception:
        body_data = {}
    try:
        body = HardlinkBody.model_validate(body_data if isinstance(body_data, dict) else {})
    except ValidationError as exc:
        payload, status = api_error_payload(
            'Invalid request.', code='unprocessable', detail=format_validation_errors(exc),
        )
        return JSONResponse(payload, status_code=status)
    if is_apply and not apply_enabled:
        return _api_error('Hardlink apply is disabled. Set ALLOW_HARDLINK_APPLY=true.', 'forbidden', 403)
    if not is_apply and not enabled:
        return _api_error('Hardlink helpers are disabled', 'forbidden', 403)
    try:
        allowed, error = data.paths_allowed(body.source, body.dest, app=flask_app)
    except Exception:
        logging.getLogger(__name__).exception('Hardlink path policy evaluation failed')
        return _api_error('Could not validate hardlink paths', 'internal', 500)
    if not allowed:
        return _api_error(error or 'Unsafe path', 'forbidden', 403)
    if not is_apply:
        try:
            return JSONResponse(data.preview(body.source, body.dest))
        except Exception:
            return _api_error('Could not preview hardlink', 'internal', 500)
    try:
        result = data.apply(body.source, body.dest)
    except ValueError as exc:
        return _api_error(str(exc), 'bad_request', 400)
    except OSError:
        return _api_error('Hardlink failed', 'internal', 500)
    try:
        data.audit(
            result.get('source', body.source), result.get('dest', body.dest),
            audit_user=getattr(actor, 'id', None),
        )
    except Exception:
        pass
    return JSONResponse(result, status_code=201)


def _api_error(message: str, code: str, status: int) -> JSONResponse:
    from oneirodex.utils.api_contract import api_error_payload

    payload, _ = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=status)


def mount_storage_hardlinks_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_storage_hardlinks_router(flask_app, **kwargs))
    return app
