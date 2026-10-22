"""Native FastAPI read APIs for shipped emulator choices."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class EmulatorReadData:
    def all(self):
        from oneirodex.platform import Emulator
        from oneirodex.utils.emulator_profiles import get_emulator_profiles

        return {'emulators': [item.value for item in Emulator], 'profiles': get_emulator_profiles()}

    def platform(self, name: str):
        from oneirodex.utils.emulator_profiles import resolve_emulators_for_platform

        return resolve_emulators_for_platform(name)

    def profiles(self):
        from oneirodex.platform import LibraryPlatform, platform_emulator_mapping
        from oneirodex.utils.emulator_profiles import get_emulator_profiles

        catalog = {
            platform.name: [item.value for item in platform_emulator_mapping.get(platform, [])]
            for platform in LibraryPlatform
            if platform_emulator_mapping.get(platform)
        }
        return {'profiles': get_emulator_profiles(), 'catalog': catalog}

    def save_profiles(self, profiles):
        from oneirodex.platform import LibraryPlatform, platform_emulator_mapping
        from oneirodex.utils.emulator_profiles import set_emulator_profiles

        saved = set_emulator_profiles(profiles)
        catalog = {
            platform.name: [item.value for item in platform_emulator_mapping.get(platform, [])]
            for platform in LibraryPlatform
            if platform_emulator_mapping.get(platform)
        }
        return {'profiles': saved, 'catalog': catalog}

    def browser_player_settings(self):
        from oneirodex.utils.browser_player import get_browser_player_settings

        return get_browser_player_settings()

    def save_browser_player_settings(self, payload):
        from oneirodex.utils.browser_player import set_browser_player_settings

        return set_browser_player_settings(payload)


def create_emulator_reads_router(
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
    data = data_access or EmulatorReadData()

    def get_response(request, platform=None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                try:
                    if platform is None:
                        response = JSONResponse(data.all())
                    elif len(platform) > 50:
                        response = _error(400, 'bad_request', 'Invalid platform parameter')
                    else:
                        try:
                            response = JSONResponse(data.platform(platform))
                        except KeyError:
                            response = _error(404, 'not_found', 'Platform not supported')
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)
                except Exception:
                    flask_app.logger.exception('Emulator choices could not be retrieved')
                    response = _error(500, 'internal', 'Unable to retrieve emulators')
            return _finish(response, flask_app, request)

    @router.api_route('/api/emulators', methods=['GET', 'HEAD'])
    def emulators(request: Request):
        return get_response(request)

    @router.api_route('/api/emulators/{platform}', methods=['GET', 'HEAD'])
    def emulators_for_platform(platform: str, request: Request):
        return get_response(request, platform)

    @router.api_route('/api/emulator-profiles', methods=['GET', 'HEAD', 'POST', 'PUT'])
    async def emulator_profiles(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            from oneirodex.utils.role_catalog import normalize_role

            is_admin = normalize_role(getattr(auth.user, 'role', None) or '') == 'admin'
            if request.method in ('POST', 'PUT'):
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                response = None
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and not is_admin:
                from .oidc_status import _login_redirect as admin_login_redirect

                response = admin_login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif response is None and auth.token is not None and not auth.has_scope('admin'):
                response = _error(403, 'forbidden', 'This token does not have the admin scope')
            elif response is None and request.method in ('POST', 'PUT'):
                body = await _json_body(request)
                profiles = body.get('profiles')
                if profiles is None:
                    profiles = {key: value for key, value in body.items() if key != 'profiles'}
                if not isinstance(profiles, dict):
                    response = _error(400, 'bad_request', 'profiles object required')
                else:
                    try:
                        response = JSONResponse(data.save_profiles(profiles))
                    except ValueError as exc:
                        response = _error(400, 'bad_request', str(exc))
            elif response is None:
                response = JSONResponse(data.profiles())
            if response is not None and auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            return _finish(response, flask_app, request)

    @router.api_route('/api/browser-player-settings', methods=['GET', 'HEAD', 'POST', 'PUT'])
    async def browser_player_settings(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            from oneirodex.utils.role_catalog import normalize_role

            is_admin = normalize_role(getattr(auth.user, 'role', None) or '') == 'admin'
            if request.method in ('POST', 'PUT'):
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                response = None
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and not is_admin:
                from .oidc_status import _login_redirect as admin_login_redirect

                response = admin_login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif response is None and auth.token is not None and not auth.has_scope('admin'):
                response = _error(403, 'forbidden', 'This token does not have the admin scope')
            elif response is None and request.method in ('POST', 'PUT'):
                payload = (await _json_any(request)) or {}
                if not isinstance(payload, dict):
                    response = _error(400, 'bad_request', 'JSON object required')
                else:
                    try:
                        saved = data.save_browser_player_settings(payload)
                    except ValueError as exc:
                        response = _error(400, 'bad_request', str(exc))
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload(saved))
            elif response is None:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload(data.browser_player_settings()))
            if response is not None and auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            return _finish(response, flask_app, request)

    return router


def mount_emulator_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_emulator_reads_router(flask_app, **kwargs))
    return app


def _error(status, code, message):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)


def _finish(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
    return response


async def _json_body(request):
    import json

    try:
        value = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


async def _json_any(request):
    import json

    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type != 'application/json' and not (
        content_type.startswith('application/') and content_type.endswith('+json')
    ):
        return None
    try:
        return json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        return None
