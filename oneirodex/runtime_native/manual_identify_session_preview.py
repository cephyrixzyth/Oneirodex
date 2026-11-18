"""Admin scan page: restore the last manual-identify candidate list."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


def create_manual_identify_session_preview_router(
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

    @router.get('/api/admin/scan/manual-identify/session-preview')
    async def manual_identify_session_preview(request: Request):
        """Return the candidate list the last manual-identify listing left
        in the signed session, so the scan page can restore it after a reload.
        """
        from oneirodex.utils.api_contract import api_ok_payload, api_error_payload
        from oneirodex.utils.role_catalog import normalize_role
        from starlette.responses import JSONResponse

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
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
            else:
                game_paths = auth.session_data.get('game_paths')
                rows = []
                if isinstance(game_paths, dict):
                    rows = [
                        {'name': name, 'full_path': path}
                        for name, path in game_paths.items()
                        if isinstance(name, str) and name.strip()
                        and isinstance(path, str) and path.strip()
                    ][:5000]
                response = JSONResponse(api_ok_payload({
                    'games': rows,
                    'library_uuid': auth.session_data.get('selected_library_uuid'),
                }), headers={'Cache-Control': 'no-store'})
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_manual_identify_session_preview_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_manual_identify_session_preview_router(flask_app, **kwargs))
    return app
