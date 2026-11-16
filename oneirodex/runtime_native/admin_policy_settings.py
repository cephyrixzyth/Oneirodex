"""Native admin configuration reads/writes for scan-match and remote play."""
from __future__ import annotations

from contextlib import nullcontext
import logging
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminPolicySettingsData:
    def remote_read(self):
        from oneirodex.utils.remote_play import get_remote_play_config
        return get_remote_play_config(admin=True)

    def remote_save(self, data):
        from oneirodex.utils.remote_play import save_remote_play_config
        return save_remote_play_config(data)

    def scan_match_read(self):
        from oneirodex.utils.scan_match_settings import get_scan_match_config
        return get_scan_match_config()

    def scan_match_save(self, data):
        from oneirodex.utils.scan_match_settings import save_scan_match_config
        return save_scan_match_config(data)


def create_admin_policy_settings_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminPolicySettingsData()

    @router.api_route('/api/admin/remote-play/config', methods=['GET', 'HEAD', 'PUT'])
    @router.api_route('/api/admin/scan-match/config', methods=['GET', 'HEAD', 'PUT'])
    async def settings(request: Request):
        remote = request.url.path.endswith('/remote-play/config')
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method == 'PUT':
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie
                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session, flask_app.config)
            auth = None
            if csrf_response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role
            if csrf_response is not None:
                response = csrf_response
            else:
                user = auth.user
                is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                if user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'), include_next=True)
                elif not is_admin:
                    response = _login_redirect(flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.', category='danger', include_next=False)
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                elif request.method == 'HEAD':
                    from .runtime_context import native_json_response

                    payload, status = api_error_payload('No fields to update', code='bad_request')
                    response = native_json_response(
                        payload, config=flask_app.config, status=status,
                    )
                elif request.method == 'PUT':
                    body = await _read_json(request)
                    if not body:
                        payload, status = api_error_payload('No fields to update', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            if remote:
                                saved = data.remote_save(body)
                                result = api_ok_payload({'status': 'saved', **saved})
                            else:
                                result = data.scan_match_save(body)
                            response = JSONResponse(result)
                            if auth.should_set_session_cookie:
                                _set_session_cookie(response, flask_app, auth)
                        except ValueError as exc:
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        except Exception:
                            from oneirodex.runtime_native.db_session import native_db as db
                            db.session.rollback()
                            logging.getLogger(__name__).warning('Admin policy settings save failed')
                            payload, status = api_error_payload('Could not save settings.', code='internal')
                            response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        result = data.remote_read() if remote else data.scan_match_read()
                        response = JSONResponse(result)
                    except Exception:
                        logging.getLogger(__name__).warning('Admin policy settings read failed')
                        payload, status = api_error_payload('Could not load settings.', code='internal')
                        response = JSONResponse(payload, status_code=status)
        from oneirodex.utils.security_headers import security_header_values
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


async def _read_json(request):
    import json
    try:
        length = int(request.headers.get('content-length') or '0')
        if length > 16 * 1024:
            return None
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16 * 1024:
                return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def mount_admin_policy_settings_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_policy_settings_router(flask_app, **kwargs))
    return app
