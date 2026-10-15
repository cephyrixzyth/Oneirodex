"""Native FastAPI exports for ES-DE and Pegasus frontends."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class LibraryExportData:
    def _games(self, user, platform):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.library_acl import apply_game_access_filters

        games = list(
            apply_game_access_filters(db.session.query(Game), user)
            .limit(500)
            .all()
        )
        if not platform:
            return games
        key = platform.upper()
        return [
            game for game in games
            if getattr(getattr(getattr(game, 'library', None), 'platform', None), 'name', None)
            and str(game.library.platform.name).upper() == key
        ]

    def _rows(self, games, flask_app):
        from oneirodex.utils.frontend_export import portable_export_path
        from oneirodex.utils.security import get_allowed_base_directories

        roots = get_allowed_base_directories(flask_app)
        return [{
            'uuid': game.uuid,
            'name': game.name,
            'summary': getattr(game, 'summary', None) or '',
            'path': portable_export_path(
                getattr(game, 'full_disk_path', None) or '', library_roots=roots,
            ) or game.name,
            'cover_url': getattr(game, 'cover', None) or '',
            'developer': '', 'publisher': '', 'genre': '',
        } for game in games], roots

    def esde(self, user, platform, flask_app):
        from oneirodex.utils.frontend_export import build_es_de_gamelist

        games = self._games(user, platform or None)
        rows, roots = self._rows(games, flask_app)
        return build_es_de_gamelist(
            rows, system=platform or 'all', library_roots=roots,
        )

    def pegasus(self, user, platform, flask_app):
        from oneirodex.utils.frontend_export import build_pegasus_metadata

        collection = platform or 'Library'
        games = self._games(user, collection if collection != 'Library' else None)
        rows, roots = self._rows(games, flask_app)
        return build_pegasus_metadata(
            rows, collection=collection, library_roots=roots,
        )


def create_library_export_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or LibraryExportData()

    @router.api_route('/api/export/esde', methods=['GET', 'HEAD'])
    async def export_esde(request: Request):
        platform = (request.query_params.get('platform') or '').strip()
        return await _export(
            request, flask_app, data, 'esde', platform, find_user, find_token,
            commit_token_touch, load_user_id, login_manager, database_scope,
        )

    @router.api_route('/api/export/pegasus', methods=['GET', 'HEAD'])
    async def export_pegasus(request: Request):
        platform = (request.query_params.get('platform') or '').strip()
        return await _export(
            request, flask_app, data, 'pegasus', platform, find_user, find_token,
            commit_token_touch, load_user_id, login_manager, database_scope,
        )

    return router


async def _export(
    request, flask_app, data, format_name, platform, find_user, find_token,
    commit_token_touch, load_user_id, login_manager, database_scope,
):
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
            try:
                if format_name == 'esde':
                    content = data.esde(auth.user, platform, flask_app)
                    filename = f'gamelist-{platform or "all"}.xml'
                    media_type = 'application/xml'
                else:
                    content = data.pegasus(auth.user, platform, flask_app)
                    collection = platform or 'Library'
                    filename = f'metadata-{collection}.pegasus.txt'
                    media_type = 'text/plain'
                response = Response(
                    content, media_type=media_type,
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'},
                )
            except Exception:  # noqa: BLE001 — export errors use shared safe API shape
                from oneirodex.utils.api_contract import api_error_payload
                payload, status = api_error_payload('Failed to export library', code='internal')
                response = JSONResponse(payload, status_code=status)
        if auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD' and response.status_code == 200:
            response.body = b''
        return response


def mount_library_export_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_library_export_router(flask_app, **kwargs))
    return app
