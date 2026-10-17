"""Native FastAPI status reads for challenge-solver and ambient-lighting devices."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response
from werkzeug.datastructures import MultiDict

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class ChallengeSolverStatusData:
    uses_explicit_config = True

    def status(self, *, probe: bool, config=None) -> dict:
        from oneirodex.utils.challenge_solver import challenge_solver_status

        return challenge_solver_status(probe=probe, config=config)

    def read_config(self, *, config=None) -> dict:
        from oneirodex.utils.challenge_solver import get_challenge_config

        return get_challenge_config(config)

    def save_config(self, payload: dict, *, config=None) -> dict:
        from oneirodex.utils.challenge_solver import save_challenge_config

        return save_challenge_config(payload, config=config)


class AmbientLightingStatusData:
    uses_explicit_config = True

    def status(self, *, probe: bool, config=None) -> dict:
        from oneirodex.utils.ambient_lighting import ambient_lighting_status

        return ambient_lighting_status(probe=probe, config=config)

    def read_config(self, *, config=None) -> dict:
        from oneirodex.utils.ambient_lighting import get_ambient_config

        return get_ambient_config(config)

    def save_config(self, payload: dict, *, config=None) -> dict:
        from oneirodex.utils.ambient_lighting import save_ambient_config

        return save_ambient_config(payload, config=config)


def create_device_status_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    challenge_data=None,
    ambient_data=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    """Create native admin status, configuration, and probe actions."""
    router = APIRouter()
    challenge = challenge_data if challenge_data is not None else ChallengeSolverStatusData()
    ambient = ambient_data if ambient_data is not None else AmbientLightingStatusData()

    def status_response(request: Request, data):
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
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
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
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger',
                        include_next=False,
                    )
                else:
                    # Match Werkzeug MultiDict's first-value query semantics.
                    args = MultiDict(request.query_params.multi_items())
                    probe = args.get('probe', '').lower() in ('1', 'true', 'yes')
                    from starlette.responses import JSONResponse

                    if getattr(data, 'uses_explicit_config', False):
                        payload = data.status(probe=probe, config=flask_app.config)
                    else:
                        payload = data.status(probe=probe)
                    response = JSONResponse(payload)

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    async def action_response(request: Request, data, action: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if request.method not in ('GET', 'HEAD') and auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)

            if response is None:
                from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
                from oneirodex.utils.role_catalog import normalize_role

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
                        'This token does not have the admin scope', code='forbidden',
                    )
                    response = JSONResponse(payload, status_code=status)
                elif action == 'config' and request.method == 'HEAD':
                    from oneirodex.utils.api_contract import api_error_payload
                    from .runtime_context import native_json_response

                    payload, status = api_error_payload('No fields to update', code='bad_request')
                    response = native_json_response(
                        payload, config=flask_app.config, status=status,
                    )
                elif action == 'config' and request.method == 'GET':
                    response = JSONResponse(data.read_config(config=flask_app.config))
                elif action == 'config':
                    try:
                        payload = await request.json()
                    except Exception:
                        payload = {}
                    if not isinstance(payload, dict) or not payload:
                        payload, status = api_error_payload('No fields to update', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            saved = data.save_config(payload, config=flask_app.config)
                            response = JSONResponse(api_ok_payload({'status': 'saved', **saved}))
                        except ValueError as exc:
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                else:
                    response = JSONResponse(data.status(probe=True, config=flask_app.config))

            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/admin/challenge-solver/status', methods=['GET', 'HEAD'])
    def challenge_solver_status(request: Request):
        return status_response(request, challenge)

    @router.api_route('/api/admin/ambient-lighting/status', methods=['GET', 'HEAD'])
    def ambient_lighting_status(request: Request):
        return status_response(request, ambient)

    @router.api_route('/api/admin/challenge-solver/config', methods=['GET', 'HEAD', 'PUT'])
    async def challenge_solver_config(request: Request):
        return await action_response(request, challenge, 'config')

    @router.post('/api/admin/challenge-solver/test')
    async def challenge_solver_test(request: Request):
        return await action_response(request, challenge, 'test')

    @router.api_route('/api/admin/ambient-lighting/config', methods=['GET', 'HEAD', 'PUT'])
    async def ambient_lighting_config(request: Request):
        return await action_response(request, ambient, 'config')

    @router.post('/api/admin/ambient-lighting/test')
    async def ambient_lighting_test(request: Request):
        return await action_response(request, ambient, 'test')

    return router


def mount_device_status_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_device_status_router(flask_app, **kwargs))
    return app
