"""Native authenticated read API for the selectable theme-font catalogue."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class ThemeFontsData:
    """Read the local font inventory without calling providers or writing files."""

    def __init__(self, font_path: str | None = None):
        self.font_path = font_path

    def catalogue(self) -> dict:
        from oneirodex.utils.theme_fonts import (
            PLATFORM_FONT_HINTS,
            available_fonts,
            fonts_dir,
        )

        catalogue = available_fonts(self.font_path)
        return {
            'fonts': [
                {'id': key, **{k: v for k, v in entry.items() if k != 'file'}}
                for key, entry in sorted(catalogue.items())
            ],
            'platform_hints': PLATFORM_FONT_HINTS,
            'fonts_dir': fonts_dir(self.font_path),
            'note': (
                'Console manufacturers\' typefaces are not bundled — these are '
                'OFL/public-domain faces chosen to evoke each era. Drop your own '
                'licensed fonts in fonts_dir to have them offered here.'
            ),
        }


def create_theme_fonts_read_router(
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
    data = data_access or ThemeFontsData(flask_app.config.get('FONT_PATH') or None)

    @router.api_route('/api/theme/fonts', methods=['GET', 'HEAD'])
    def theme_fonts_catalogue(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                try:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(data.catalogue()))
                except Exception:  # noqa: BLE001 — keep filesystem details private
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(
                        'Could not retrieve the theme font catalogue', code='internal',
                    )
                    response = JSONResponse(payload, status_code=status)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)

            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_theme_fonts_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_theme_fonts_read_router(flask_app, **kwargs))
    return app
