"""Native admin read/write routes for OIDC and community link settings."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import logging
import os
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context

_OIDC_ADMIN_FIELDS = {
    'oidc_enabled', 'oidc_display_name', 'oidc_issuer_url', 'oidc_client_id',
    'oidc_client_secret', 'oidc_redirect_uri', 'oidc_scopes',
    'oidc_role_claim', 'oidc_role_map',
}
_OIDC_TEXT_LIMITS = {
    'oidc_display_name': 120, 'oidc_issuer_url': 512, 'oidc_client_id': 255,
    'oidc_client_secret': 512, 'oidc_redirect_uri': 512,
    'oidc_scopes': 255, 'oidc_role_claim': 64,
}
_OIDC_ROLES = {'admin', 'librarian', 'user', 'child'}
_MAX_BODY = 16 * 1024


class IntegrationSettingsData:
    """Adapter around existing setting models and validation utilities."""

    def oidc_read(self) -> dict:
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.oidc import oidc_readiness_report

        row = global_settings_row()
        return {'settings': _oidc_public_settings(row), 'readiness': oidc_readiness_report(row)}

    def oidc_save(self, payload: dict) -> dict:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.cache import cache
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.global_settings import global_settings_row_or_create
        from oneirodex.utils.oidc import oidc_readiness_report

        row = global_settings_row_or_create()
        row.oidc_enabled = payload['oidc_enabled']
        row.oidc_display_name = payload['oidc_display_name'].strip() or 'Sign in with SSO'
        row.oidc_issuer_url = payload['oidc_issuer_url'].strip() or None
        row.oidc_client_id = payload['oidc_client_id'].strip() or None
        if payload['oidc_client_secret'].strip():
            row.oidc_client_secret = payload['oidc_client_secret'].strip()
        row.oidc_redirect_uri = payload['oidc_redirect_uri'].strip() or None
        row.oidc_scopes = payload['oidc_scopes'].strip() or 'openid email profile'
        row.oidc_role_claim = payload['oidc_role_claim'].strip() or 'groups'
        row.oidc_role_map = payload['oidc_role_map']
        row.last_updated = datetime.now(timezone.utc)
        db.session.commit()
        cache.delete('global_settings')
        log_system_event('OIDC settings updated via native integrations', event_type='audit', event_level='information')
        return {'settings': _oidc_public_settings(row), 'readiness': oidc_readiness_report(row)}

    def community_read(self) -> dict:
        from oneirodex.utils.global_settings import global_settings_row

        row = global_settings_row()
        return {
            'community_chat_url': (getattr(row, 'community_chat_url', None) or '') if row else '',
            'community_chat_label': (getattr(row, 'community_chat_label', None) or 'Open community') if row else 'Open community',
        }

    def community_save(self, url: str, label: str) -> dict:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.cache import cache
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.global_settings import global_settings_row_or_create

        row = global_settings_row_or_create()
        row.community_chat_url = url or None
        row.community_chat_label = label.strip() or 'Open community'
        db.session.commit()
        cache.delete('global_settings')
        log_system_event('Community chat link updated via integrations')
        return {
            'community_chat_url': row.community_chat_url or '',
            'community_chat_label': row.community_chat_label or 'Open community',
        }


def _oidc_public_settings(row) -> dict:
    from oneirodex.utils.oidc import oidc_readiness_report

    return {
        'oidc_enabled': bool(row and row.oidc_enabled),
        'oidc_display_name': (getattr(row, 'oidc_display_name', None) if row else None) or 'Sign in with SSO',
        'oidc_issuer_url': (getattr(row, 'oidc_issuer_url', None) if row else None) or '',
        'oidc_client_id': (getattr(row, 'oidc_client_id', None) if row else None) or '',
        'oidc_client_secret_configured': bool(
            (getattr(row, 'oidc_client_secret', None) if row else None) or os.getenv('OIDC_CLIENT_SECRET')
        ),
        'oidc_redirect_uri': (getattr(row, 'oidc_redirect_uri', None) if row else None) or '',
        'oidc_scopes': (getattr(row, 'oidc_scopes', None) if row else None) or 'openid email profile',
        'oidc_role_claim': (getattr(row, 'oidc_role_claim', None) if row else None) or 'groups',
        'oidc_role_map': (getattr(row, 'oidc_role_map', None) if row else None) or {
            'admin': 'admin', 'oneirodex-admin': 'admin', 'librarian': 'librarian',
            'oneirodex-librarian': 'librarian', 'child': 'child', 'oneirodex-child': 'child',
        },
    }


def _validate_oidc(payload):
    from oneirodex.utils.oidc import is_secure_oidc_issuer

    if not isinstance(payload, dict) or set(payload) != _OIDC_ADMIN_FIELDS:
        return 'Provide all OIDC settings fields.'
    if type(payload['oidc_enabled']) is not bool:
        return 'OIDC enabled must be a boolean.'
    for field, limit in _OIDC_TEXT_LIMITS.items():
        value = payload[field]
        if not isinstance(value, str) or len(value) > limit or any(ord(ch) < 32 and ch not in '\t' for ch in value):
            return 'OIDC text fields are invalid or too long.'
    role_map = payload['oidc_role_map']
    if (not isinstance(role_map, dict) or len(role_map) > 128
            or any(not isinstance(key, str) or not key.strip() or len(key) > 120 for key in role_map)
            or any(not isinstance(value, str) or value.strip().lower() not in _OIDC_ROLES for value in role_map.values())):
        return 'OIDC role map must map names to supported roles.'
    issuer = payload['oidc_issuer_url'].strip() or None
    if issuer and not is_secure_oidc_issuer(issuer):
        return 'OIDC issuer URL must use HTTPS.'
    if payload['oidc_enabled'] and not all((issuer, payload['oidc_client_id'].strip(), payload['oidc_redirect_uri'].strip())):
        return 'When enabling SSO, provide issuer URL, client ID and redirect URI.'
    return None


def create_integration_settings_router(
    flask_app, *, find_user: Callable[[int], Any | None], find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None], load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None, database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or IntegrationSettingsData()

    @router.api_route('/admin/integrations/oidc/save', methods=['POST'])
    @router.api_route('/admin/integrations/community', methods=['POST'])
    @router.api_route('/api/admin/integrations/oidc', methods=['GET', 'HEAD', 'PUT'])
    @router.api_route('/api/admin/integrations/community', methods=['GET', 'HEAD', 'PUT'])
    async def integration_settings(request: Request):
        is_oidc = request.url.path.endswith('/oidc') or request.url.path.endswith('/oidc/save')
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method in ('PUT', 'POST'):
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
                    response = _login_redirect(flask_app, request, login_manager, auth, message=getattr(login_manager, 'login_message', None), category=getattr(login_manager, 'login_message_category', 'message'), include_next=True)
                elif not is_admin:
                    response = _login_redirect(flask_app, request, login_manager, auth, message='You must be an admin to access this page.', category='danger', include_next=False)
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                elif request.method in ('PUT', 'POST'):
                    body = await _read_json(request)
                    if body is None:
                        payload, status = api_error_payload('Request body must be a valid JSON object.', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    elif is_oidc and (error := _validate_oidc(body)):
                        payload, status = api_error_payload(error, code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    elif not is_oidc and (error := _validate_community(body)):
                        payload, status = api_error_payload(error, code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            result = data.oidc_save(body) if is_oidc else _save_community(data, body)
                            response = JSONResponse(api_ok_payload(result))
                            if auth.should_set_session_cookie:
                                _set_session_cookie(response, flask_app, auth)
                        except Exception:
                            from oneirodex.runtime_native.db_session import native_db as db
                            db.session.rollback()
                            logging.getLogger(__name__).warning('Integration settings save failed')
                            payload, status = api_error_payload('Could not save integration settings.', code='internal')
                            response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        result = data.oidc_read() if is_oidc else data.community_read()
                        response = JSONResponse(api_ok_payload(result))
                    except Exception:
                        logging.getLogger(__name__).warning('Integration settings load failed')
                        payload, status = api_error_payload('Could not load integration settings.', code='internal')
                        response = JSONResponse(payload, status_code=status)

        from oneirodex.utils.security_headers import security_header_values
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


async def _read_json(request: Request):
    content_length = request.headers.get('content-length')
    if content_length:
        try:
            if int(content_length) > _MAX_BODY:
                return None
        except ValueError:
            return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BODY:
            return None
    import json
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def _validate_community(data):
    if not isinstance(data, dict) or set(data) != {'community_chat_url', 'community_chat_label'}:
        return 'Provide the community URL and link label.'
    url, label = data.get('community_chat_url'), data.get('community_chat_label')
    if not isinstance(url, str) or len(url) > 2048 or not isinstance(label, str) or len(label) > 120 or any(ord(ch) < 32 for ch in label):
        return 'Community settings contain invalid text.'
    from oneirodex.utils.security import validate_community_chat_url
    ok, normalized = validate_community_chat_url(url.strip())
    return None if ok else normalized


def _save_community(data, payload):
    from oneirodex.utils.security import validate_community_chat_url
    ok, normalized = validate_community_chat_url(payload['community_chat_url'].strip())
    if not ok:
        raise ValueError('Community URL failed validation after normalization.')
    return data.community_save(normalized, payload['community_chat_label'])


def mount_integration_settings_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_integration_settings_router(flask_app, **kwargs))
    return app
