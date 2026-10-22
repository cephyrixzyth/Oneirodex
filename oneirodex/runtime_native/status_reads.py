"""Native FastAPI read-only status endpoints for Storage, malware scan, and RTC."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class StorageStatusData:
    def status(self, *, config=None) -> dict:
        from oneirodex.utils.hardlinks import build_storage_status

        app_config = config or {}
        helpers = _flag(app_config.get('ENABLE_HARDLINK_HELPERS'))
        apply_allowed = helpers and _flag(app_config.get('ALLOW_HARDLINK_APPLY'))
        return build_storage_status(
            helpers_enabled=helpers,
            allow_apply=apply_allowed,
            games_path=app_config.get('DATA_FOLDER_GAMES') or '',
        )


class MalwareScanStatusData:
    def status(self, *, config=None) -> dict:
        from oneirodex.utils.malware_scan import module_status

        return module_status(config=config)


class RtcStatusData:
    def status(self, *, config=None) -> dict:
        from oneirodex.utils.livekit_rtc import livekit_config, livekit_enabled

        rtc_config = livekit_config()
        enabled = livekit_enabled(config=config or {})
        return {
            'enabled': enabled and bool(
                rtc_config['url'] and rtc_config['api_key'] and rtc_config['api_secret']
            ),
            'url': rtc_config['url'] if enabled else None,
        }

    def token_config(self):
        from oneirodex.utils.livekit_rtc import livekit_config

        return livekit_config()

    def may_join(self, user, room: str) -> bool:
        from oneirodex.utils.livekit_rtc import user_may_join_room

        return user_may_join_room(user, room)

    def normalize_room(self, room: str) -> str:
        from oneirodex.utils.livekit_rtc import normalize_room_name

        return normalize_room_name(room)

    def mint(self, *, identity, name, room, ttl_seconds, can_publish, can_subscribe):
        from oneirodex.utils.livekit_rtc import mint_livekit_token

        return mint_livekit_token(
            identity=identity, name=name, room=room, ttl_seconds=ttl_seconds,
            can_publish=can_publish, can_subscribe=can_subscribe,
        )


def create_status_reads_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    storage_data=None,
    malware_data=None,
    rtc_data=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    """Build three native status reads with their existing auth boundaries."""
    router = APIRouter()
    storage = storage_data or StorageStatusData()
    malware = malware_data or MalwareScanStatusData()
    rtc = rtc_data or RtcStatusData()

    def auth_context(request: Request):
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

    def admin_denied_response(auth, request: Request):
        from oneirodex.utils.role_catalog import normalize_role

        user = auth.user
        is_admin = (
            bool(getattr(user, 'is_authenticated', True))
            and normalize_role(getattr(user, 'role', None) or '') == 'admin'
        )
        if is_admin and auth.token is not None and not auth.has_scope('admin'):
            from oneirodex.utils.api_contract import api_error_payload
            from starlette.responses import JSONResponse

            payload, status = api_error_payload(
                'This token does not have the admin scope', code='forbidden'
            )
            return JSONResponse(payload, status_code=status)
        if not is_admin:
            return _login_redirect(
                flask_app, request, login_manager, auth,
                message='You must be an admin to access this page.',
                category='danger',
                include_next=False,
            )
        return None

    def response_for(request: Request, data, *, admin_only: bool):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = auth_context(request)
            if auth.user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            else:
                response = admin_denied_response(auth, request) if admin_only else None
                if response is None:
                    from starlette.responses import JSONResponse

                    response = JSONResponse(data.status(config=flask_app.config))
            return secure(response, request)

    @router.api_route('/api/storage/status', methods=['GET', 'HEAD'])
    def storage_status(request: Request):
        return response_for(request, storage, admin_only=True)

    @router.api_route('/api/admin/malware-scan/status', methods=['GET', 'HEAD'])
    def malware_scan_status(request: Request):
        return response_for(request, malware, admin_only=True)

    @router.api_route('/api/rtc/status', methods=['GET', 'HEAD'])
    def rtc_status(request: Request):
        return response_for(request, rtc, admin_only=False)

    @router.post('/api/rtc/token')
    async def rtc_token(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from .csrf_compat import csrf_error_response
            auth = auth_context(request)
            response = (
                None if auth.token is not None
                else csrf_error_response(request, auth.session_data, flask_app.config)
            )
            if response is None:
                assert auth is not None
                if auth.user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                else:
                    response = await _rtc_token_request(
                        request, flask_app, rtc, auth.user,
                    )
            if auth is not None and auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            return secure(response, request)

    return router


def mount_status_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_status_reads_router(flask_app, **kwargs))
    return app


def _flag(value) -> bool:
    return str(value or '').lower() in {'1', 'true', 'yes', 'on'}


async def _rtc_token_request(request: Request, flask_app, data, user):
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.role_catalog import normalize_role
    from oneirodex.utils.livekit_rtc import livekit_enabled
    from starlette.responses import JSONResponse

    if not livekit_enabled(config=flask_app.config):
        return _status_error('LiveKit is disabled', 'forbidden', 403)
    config = data.token_config()
    if not (config['url'] and config['api_key'] and config['api_secret']):
        return _status_error('LiveKit is not configured', 'unavailable', 503)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        payload, status = api_error_payload('Expected a JSON object', code='bad_request')
        return JSONResponse(payload, status_code=status)
    room = data.normalize_room(body.get('room') or 'household:lobby')
    if not data.may_join(user, room):
        return _status_error('Forbidden for this room', 'forbidden', 403)
    role = normalize_role(getattr(user, 'role', None))
    spectator = bool(body.get('spectator'))
    if role == 'child' and bool(body.get('video') or body.get('screenshare')):
        return _status_error('Camera/screenshare disabled for child accounts', 'forbidden', 403)
    try:
        token = data.mint(
            identity=f'user-{user.id}',
            name=getattr(user, 'name', None) or f'user-{user.id}',
            room=room,
            ttl_seconds=int(body.get('ttl') or 3600),
            can_publish=not spectator,
            can_subscribe=True,
        )
    except RuntimeError:
        return _status_error('LiveKit is not configured', 'unavailable', 503)
    except (TypeError, ValueError):
        payload, status = api_error_payload('Invalid token lifetime', code='bad_request')
        return JSONResponse(payload, status_code=status)
    return JSONResponse({
        'token': token, 'url': config['url'], 'room': room,
        'identity': f'user-{user.id}', 'spectator': spectator,
        'can_publish': not spectator,
    })


def _status_error(message: str, code: str, status: int):
    from oneirodex.utils.api_contract import api_error_payload
    from starlette.responses import JSONResponse

    payload, _ = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=status)
