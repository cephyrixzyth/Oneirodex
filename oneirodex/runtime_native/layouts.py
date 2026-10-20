"""Native FastAPI APIs for admin and per-member game-detail layouts."""
from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .csrf_compat import csrf_error_response
from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context
from .response_compat import flask_integer_route_not_found_response


class LayoutData:
    def get_admin(self):
        from oneirodex.utils.detail_layouts import get_detail_layout

        return get_detail_layout()

    def save_admin(self, payload):
        from oneirodex.utils.detail_layouts import save_detail_layout

        return save_detail_layout(payload)

    def get_mine(self, user_id):
        from oneirodex.utils.detail_layouts import get_user_detail_layout, user_has_detail_override

        return {
            'layout': get_user_detail_layout(user_id),
            'is_override': user_has_detail_override(user_id),
        }

    def save_mine(self, user_id, payload):
        from oneirodex.utils.detail_layouts import save_user_detail_layout

        return {'layout': save_user_detail_layout(user_id, payload), 'is_override': True}

    def clear_mine(self, user_id):
        from oneirodex.utils.detail_layouts import clear_user_detail_layout

        return {'layout': clear_user_detail_layout(user_id), 'is_override': False}

    def presets(self, user_id):
        from oneirodex.utils.detail_layouts import list_layout_presets

        return {'presets': list_layout_presets(user_id)}

    def create_preset(self, user_id, name, layout):
        from oneirodex.utils.detail_layouts import save_layout_preset

        return save_layout_preset(user_id, name, layout)

    def delete_preset(self, user_id, preset_id):
        from oneirodex.utils.detail_layouts import delete_layout_preset

        return delete_layout_preset(user_id, preset_id)


def create_layout_router(
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
    data = data_access or LayoutData()

    def finish(response, request, auth):
        if auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    def auth_error(request, auth, *, write: bool, admin: bool):
        if auth.user is None:
            return _login_redirect(
                flask_app, request, login_manager, auth,
                message=getattr(login_manager, 'login_message', None),
                category=getattr(login_manager, 'login_message_category', 'message'),
                include_next=True,
            )
        if admin:
            from oneirodex.utils.role_catalog import normalize_role

            if normalize_role(getattr(auth.user, 'role', None)) != 'admin':
                return _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            if auth.token is not None and not auth.has_scope('admin'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden',
                )
                return JSONResponse(body, status_code=status)
        return None

    def auth_scope(request):
        return database_scope(flask_app) if database_scope else nullcontext()

    def csrf_first(request, auth):
        if auth.token is not None:
            return None
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie

        cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
        session_data = load_session_cookie(
            request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
            max_age=_lifetime_seconds(
                flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
            ),
            fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
        )
        return csrf_error_response(request, session_data, flask_app.config)

    def finish_without_auth(response):
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        return response

    def make_auth(request):
        return request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )

    def error(message, code, *, detail=None):
        from oneirodex.utils.api_contract import api_error_payload

        body, status = api_error_payload(message, code=code, detail=detail)
        return JSONResponse(body, status_code=status)

    def write_scope_error(auth):
        if auth.token is None or auth.has_scope('write:library'):
            return None
        return error(
            'Missing scope: write:library', 'forbidden',
            detail={'required_scope': 'write:library'},
        )

    @router.api_route('/api/layouts/detail', methods=['GET', 'HEAD'])
    def get_admin_layout(request: Request):
        with auth_scope(request):
            auth = make_auth(request)
            response = auth_error(request, auth, write=False, admin=False)
            if response is None:
                try:
                    response = JSONResponse(data.get_admin())
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    response = error('Could not load detail layout', 'internal')
            return finish(response, request, auth)

    @router.put('/api/layouts/detail')
    async def put_admin_layout(request: Request):
        with auth_scope(request):
            auth = make_auth(request)
            response = csrf_first(request, auth)
            if response is None:
                response = auth_error(request, auth, write=False, admin=True)
            if response is None:
                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    response = JSONResponse(data.save_admin(payload))
                except ValueError as exc:
                    response = error(str(exc), 'bad_request')
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    response = error('Could not save detail layout', 'internal')
            return finish(response, request, auth)

    @router.api_route('/api/layouts/detail/mine', methods=['GET', 'HEAD'])
    def get_my_layout(request: Request):
        with auth_scope(request):
            auth = make_auth(request)
            response = auth_error(request, auth, write=False, admin=False)
            if response is None:
                try:
                    response = JSONResponse(data.get_mine(auth.user.id))
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    response = error('Could not load detail layout', 'internal')
            return finish(response, request, auth)

    @router.put('/api/layouts/detail/mine')
    async def put_my_layout(request: Request):
        with auth_scope(request):
            auth = make_auth(request)
            response = write_scope_error(auth)
            if response is None:
                response = csrf_first(request, auth)
            if response is None:
                response = auth_error(request, auth, write=False, admin=False)
            if response is None:
                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    response = JSONResponse(data.save_mine(auth.user.id, payload))
                except ValueError as exc:
                    response = error(str(exc), 'bad_request')
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    response = error('Could not save detail layout', 'internal')
            return finish(response, request, auth)

    @router.delete('/api/layouts/detail/mine')
    def delete_my_layout(request: Request):
        with auth_scope(request):
            auth = make_auth(request)
            response = write_scope_error(auth)
            if response is None:
                response = csrf_first(request, auth)
            if response is None:
                response = auth_error(request, auth, write=False, admin=False)
            if response is None:
                try:
                    response = JSONResponse(data.clear_mine(auth.user.id))
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    response = error('Could not reset detail layout', 'internal')
            return finish(response, request, auth)

    @router.api_route('/api/layouts/detail/presets', methods=['GET', 'HEAD'])
    def get_layout_presets(request: Request):
        with auth_scope(request):
            auth = make_auth(request)
            response = auth_error(request, auth, write=False, admin=False)
            if response is None:
                try:
                    response = JSONResponse(data.presets(auth.user.id))
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    response = error('Could not load detail presets', 'internal')
            return finish(response, request, auth)

    @router.post('/api/layouts/detail/presets')
    async def create_layout_preset(request: Request):
        from pydantic import ValidationError

        from oneirodex.schemas.layouts import CreateLayoutPresetBody
        from oneirodex.utils.validation import format_validation_errors

        with auth_scope(request):
            auth = make_auth(request)
            response = write_scope_error(auth)
            if response is None:
                response = csrf_first(request, auth)
            if response is None:
                response = auth_error(request, auth, write=False, admin=False)
            if response is None:
                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    body = CreateLayoutPresetBody.model_validate(payload)
                except ValidationError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    result, status = api_error_payload(
                        'Invalid request.', code='unprocessable',
                        detail=format_validation_errors(exc),
                    )
                    response = JSONResponse(result, status_code=status)
                else:
                    try:
                        response = JSONResponse(
                            data.create_preset(auth.user.id, body.name, body.layout),
                            status_code=201,
                        )
                    except ValueError as exc:
                        response = error(str(exc), 'bad_request')
                    except Exception:  # noqa: BLE001 — keep persistence detail private
                        response = error('Could not save detail preset', 'internal')
            return finish(response, request, auth)

    @router.delete('/api/layouts/detail/presets/{preset_id}')
    def delete_layout_preset(request: Request, preset_id: str):
        if not preset_id.isdecimal():
            return flask_integer_route_not_found_response(flask_app)
        preset_id = int(preset_id)
        with auth_scope(request):
            auth = make_auth(request)
            response = write_scope_error(auth)
            if response is None:
                response = csrf_first(request, auth)
            if response is None:
                response = auth_error(request, auth, write=False, admin=False)
            if response is None:
                try:
                    if not data.delete_preset(auth.user.id, preset_id):
                        response = error('Preset not found', 'not_found')
                    else:
                        response = JSONResponse({'deleted': preset_id})
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    response = error('Could not delete detail preset', 'internal')
            return finish(response, request, auth)

    return router


def mount_layout_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_layout_router(flask_app, **kwargs))
    return app
