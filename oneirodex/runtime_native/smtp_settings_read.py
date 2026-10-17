"""Native admin read for SMTP settings without exposing the saved password."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class SmtpSettingsData:
    def read(self) -> dict:
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.smtp_settings import smtp_public_state

        return {'settings': smtp_public_state(global_settings_row())}

    def save(self, payload: dict) -> dict:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.cache import cache
        from oneirodex.utils.global_settings import global_settings_row, global_settings_row_or_create
        from oneirodex.utils.smtp_settings import smtp_public_state, validate_smtp_data

        settings = global_settings_row()
        values = validate_smtp_data(payload, settings)
        settings = settings or global_settings_row_or_create()
        for key, value in values.items():
            if key != 'smtp_password' or value:
                setattr(settings, key, value)
        db.session.commit()
        cache.delete('global_settings')
        return {'settings': smtp_public_state(settings)}

    def save_legacy(self, payload):
        """Preserve v1.1.8 POST semantics for the legacy admin endpoint.

        The current JSON API uses ``save`` and its stricter validation. The
        compatibility POST historically required the full SMTP fields only
        when enabled, did not validate disabled settings, and left the stored
        port untouched while disabled.
        """
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.global_settings import global_settings_row_or_create

        values = payload or {}
        settings = global_settings_row_or_create()
        if values.get('smtp_enabled'):
            for key, message in (
                ('smtp_server', 'SMTP server is required when SMTP is enabled'),
                ('smtp_port', 'SMTP port is required when SMTP is enabled'),
                ('smtp_username', 'SMTP username is required when SMTP is enabled'),
            ):
                if not values.get(key):
                    raise ValueError(message)
            if not values.get('smtp_password') and not settings.smtp_password:
                raise ValueError('SMTP password is required when SMTP is enabled')
            if not values.get('smtp_default_sender'):
                raise ValueError('Default sender email is required when SMTP is enabled')
            try:
                port = int(values.get('smtp_port', 587))
            except ValueError:
                raise ValueError('SMTP port must be a valid number') from None
            if port <= 0 or port > 65535:
                raise ValueError('Invalid port number. Must be between 1 and 65535')
            settings.smtp_port = port

        settings.smtp_enabled = values.get('smtp_enabled', False)
        settings.smtp_server = values.get('smtp_server')
        settings.smtp_username = values.get('smtp_username')
        if values.get('smtp_password'):
            settings.smtp_password = values.get('smtp_password')
        settings.smtp_use_tls = values.get('smtp_use_tls', True)
        settings.smtp_default_sender = values.get('smtp_default_sender')
        db.session.commit()

    def test_connection(self) -> bool | None:
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.smtp_test import SMTPTester

        settings = global_settings_row()
        if not settings or not settings.smtp_enabled:
            return None
        success, _result = SMTPTester(debug=False).test_connection(
            host=settings.smtp_server,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            timeout=10,
        )
        return bool(success)


def create_smtp_settings_router(
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
    data = data_access or SmtpSettingsData()

    @router.api_route('/api/admin/smtp/settings', methods=['GET', 'HEAD', 'PUT'])
    @router.api_route('/api/admin/smtp/test', methods=['POST'])
    @router.post('/admin/smtp_settings')
    @router.post('/admin/smtp_test')
    async def smtp_settings(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method in ('PUT', 'POST'):
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

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
                    request, flask_app.config,
                    find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
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
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif request.method == 'POST':
                    if request.url.path == '/admin/smtp_settings':
                        try:
                            body = await _legacy_json_body(request)
                            legacy_save = getattr(data, 'save_legacy', None)
                            if legacy_save is None:
                                data.save(body)
                            else:
                                legacy_save(body)
                        except ValueError as exc:
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        except Exception:
                            from oneirodex.runtime_native.db_session import native_db as db
                            import logging

                            db.session.rollback()
                            logging.getLogger(__name__).warning('SMTP settings form save failed')
                            payload, status = api_error_payload('Could not save SMTP settings', code='internal')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload({
                                'status': 'success',
                                'message': 'SMTP settings updated successfully',
                            }))
                            if auth.should_set_session_cookie:
                                from .oidc_status import _set_session_cookie
                                _set_session_cookie(response, flask_app, auth)
                    else:
                        try:
                            result = data.test_connection()
                            if request.url.path == '/admin/smtp_test':
                                if result is None:
                                    payload, status = api_error_payload(
                                        'SMTP settings not configured', code='bad_request',
                                    )
                                    response = JSONResponse(payload, status_code=status)
                                elif result:
                                    response = JSONResponse(api_ok_payload({'result': 'SMTP connection successful'}))
                                else:
                                    payload, status = api_error_payload(
                                        'SMTP connection failed. Check the saved settings and provider access.',
                                        code='bad_request', status=200,
                                    )
                                    response = JSONResponse(payload, status_code=status)
                            elif result is None:
                                payload, status = api_error_payload(
                                    'Save and enable SMTP before testing the connection',
                                    code='bad_request',
                                )
                                response = JSONResponse(payload, status_code=status)
                            elif not result:
                                payload, status = api_error_payload(
                                    'SMTP connection failed. Check the saved settings and provider access.',
                                    code='bad_gateway',
                                )
                                response = JSONResponse(payload, status_code=status)
                            else:
                                response = JSONResponse(api_ok_payload({
                                    'message': 'SMTP connection successful. No email was sent.',
                                }))
                        except Exception:
                            import logging

                            logging.getLogger(__name__).warning('SMTP connection test failed')
                            if request.url.path == '/admin/smtp_test':
                                payload, status = api_error_payload(
                                    'SMTP connection failed', code='bad_request', status=200,
                                )
                            else:
                                payload, status = api_error_payload(
                                    'SMTP connection failed. Check the saved settings and provider access.',
                                    code='bad_gateway',
                                )
                            response = JSONResponse(payload, status_code=status)
                elif request.method == 'PUT':
                    try:
                        body = await request.json()
                    except Exception:
                        body = None
                    try:
                        saved = data.save(body)
                    except ValueError as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        import logging

                        db.session.rollback()
                        logging.getLogger(__name__).warning('SMTP settings API save failed')
                        payload, status = api_error_payload(
                            'Could not save SMTP settings', code='internal'
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        response = JSONResponse(api_ok_payload(saved))
                        if auth.should_set_session_cookie:
                            from .acquire_status import _set_session_cookie

                            _set_session_cookie(response, flask_app, auth)
                else:
                    response = JSONResponse(api_ok_payload(data.read()))

        from oneirodex.utils.security_headers import security_header_values

        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_smtp_settings_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_smtp_settings_router(flask_app, **kwargs))
    return app


async def _json_body(request: Request):
    import json

    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16 * 1024:
            raise ValueError('SMTP settings request is too large')
    value = json.loads(raw or b'{}')
    if not isinstance(value, dict):
        raise ValueError('SMTP settings must be a JSON object')
    return value


async def _legacy_json_body(request: Request):
    """Read the v1.1.8-compatible JSON value for the old POST path."""
    import json

    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16 * 1024:
            raise ValueError('SMTP settings request is too large')
    return json.loads(raw or b'{}') or {}
