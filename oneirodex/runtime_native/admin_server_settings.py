"""FastAPI admin API for the scoped Server Settings form."""
from __future__ import annotations

from contextlib import nullcontext

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .request_auth import request_auth_context


class AdminServerSettingsData:
    def state(self):
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.server_settings import (
            SERVER_NUMBER_BOUNDS,
            SERVER_TEXT_LIMITS,
            public_server_settings,
        )

        return {
            'settings': public_server_settings(global_settings_row()),
            'bounds': SERVER_NUMBER_BOUNDS,
            'text_limits': SERVER_TEXT_LIMITS,
        }

    def save(self, payload):
        from datetime import datetime, timezone

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.cache import cache
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.global_settings import global_settings_row_or_create
        from oneirodex.utils.server_settings import (
            FIELD_MAPPINGS,
            validate_server_settings,
        )

        try:
            changes = validate_server_settings(payload)
        except ValueError as exc:
            return None, str(exc), 'bad_request'
        try:
            record = global_settings_row_or_create()
            merged = dict(record.settings or {})
            merged.update(changes)
            for key, value in changes.items():
                if key in FIELD_MAPPINGS:
                    setattr(record, FIELD_MAPPINGS[key], value)
            record.settings = merged
            record.last_updated = datetime.now(timezone.utc)
            db.session.commit()
            log_system_event(
                f'Server settings updated: {", ".join(sorted(changes))}',
                event_type='audit', event_level='information',
            )
            cache.delete('global_settings')
            return self.state(), None, None
        except Exception:  # noqa: BLE001 — keep persistence details private
            db.session.rollback()
            return None, 'Could not save server settings', 'internal'


def create_admin_server_settings_router(
    flask_app, *, find_user, find_token, commit_token_touch,
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
):
    from .acquire_status import _login_redirect

    router = APIRouter()
    data = data_access or AdminServerSettingsData()

    @router.api_route('/admin/settings', methods=['POST'])
    @router.api_route('/admin/new_server_settings', methods=['POST'])
    @router.api_route('/api/admin/server-settings', methods=['GET', 'HEAD', 'PUT'])
    async def server_settings(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            if request.method in ('PUT', 'POST'):
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                response = csrf_error_response(request, session_data, flask_app.config)
                auth = None
            else:
                response = None
                auth = None
            if response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user,
                    find_token=find_token, commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                )
                if auth.user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                else:
                    from oneirodex.utils.role_catalog import normalize_role

                    if normalize_role(getattr(auth.user, 'role', None)) != 'admin' or (
                        auth.token is not None and not auth.has_scope('admin')
                    ):
                        response = _error('Admin required', 'forbidden', 403)
            if response is None:
                if request.method in ('PUT', 'POST'):
                    payload = await _json_object(request)
                    if request.method == 'POST' and request.url.path in (
                        '/admin/settings', '/admin/new_server_settings',
                    ) and payload == {}:
                        response = _error('No settings data provided', 'bad_request', 400)
                    else:
                        result, message, code = data.save(payload)
                        if message:
                            response = _error(message, code, 500 if code == 'internal' else 400)
                        else:
                            response = _ok({'settings': result['settings'],
                                            'bounds': result['bounds'],
                                            'text_limits': result['text_limits']})
                else:
                    try:
                        response = _ok(data.state())
                    except Exception:  # noqa: BLE001 — safe settings read failure
                        response = _error('Could not load server settings', 'internal', 500)
                response.headers['Cache-Control'] = 'no-store'
            if auth is not None and auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                headers = dict(response.headers)
                headers.setdefault('content-length', str(len(getattr(response, 'body', b''))))
                return Response(content=b'', status_code=response.status_code, headers=headers)
            return response

    return router


def mount_admin_server_settings_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_server_settings_router(flask_app, **kwargs))
    return app


async def _json_object(request):
    import json

    try:
        value = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _ok(payload):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload))


def _error(message, code, status):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)
