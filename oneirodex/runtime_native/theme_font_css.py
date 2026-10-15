"""Native public theme-font stylesheet with Flask-session compatibility."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import Response

from .request_auth import request_auth_context


def create_theme_font_router(
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

    @router.api_route('/api/theme/fonts.css', methods=['GET', 'HEAD'])
    def theme_fonts(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            query = parse_qs(request.scope.get('query_string', b'').decode('ascii', 'replace'))
            chosen = query.get('font', [None])[0]
            if chosen is None:
                chosen = getattr(getattr(auth.user, 'preferences', None), 'font', None)

            from oneirodex.utils.theme_fonts import theme_font_stylesheet

            body = theme_font_stylesheet(
                chosen, flask_app.config.get('FONT_PATH') or None,
            ).encode('utf-8')
            response = Response(
                content=body,
                media_type='text/css',
                headers={
                    'Cache-Control': 'public, max-age=60',
                    'Content-Length': str(len(body)),
                },
            )
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_theme_font_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_theme_font_router(flask_app, **kwargs))
    return app
