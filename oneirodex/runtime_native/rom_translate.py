"""Native admin read for the offline ROM translation capability catalogue."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .acquire_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


def create_rom_translate_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.api_route('/api/rom-translate/capabilities', methods=['GET', 'HEAD'])
    def capabilities(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.role_catalog import normalize_role
                from oneirodex.utils.rom_translate import list_rom_translate_capabilities

                role = normalize_role(getattr(auth.user, 'role', None) or '')
                if role == 'admin' and auth.token is not None and not auth.has_scope('admin'):
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden',
                    )
                    response = JSONResponse(payload, status_code=status)
                elif role != 'admin':
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append(('danger', 'You must be an admin to access this page.'))
                    auth.session_data['_flashes'] = flashes
                    login_path = next(
                        (rule.rule for rule in flask_app.url_map.iter_rules('login.login')),
                        '/login',
                    )
                    response = RedirectResponse(login_path, status_code=302)
                    _set_session_cookie(response, flask_app, auth)
                else:
                    response = JSONResponse({
                        'offline_enabled': False,
                        'note': (
                            'Offline dump→MT→rebuild is stubbed. Prefer RetroArch AI Service overlay '
                            'or curated translation patches. See docs/user/translation-patches.md'
                        ),
                        'platforms': list_rom_translate_capabilities(),
                    })

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_rom_translate_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_rom_translate_router(flask_app, **kwargs))
    return app
