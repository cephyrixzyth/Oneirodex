"""Native admin reads for manual-identify editor choices and state."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class ManualIdentifyReadData:
    def options(self):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import (
            Category, GameMode, Genre, Library, Platform, PlayerPerspective,
            Status, Theme,
        )

        taxonomies = {
            'genres': Genre, 'game_modes': GameMode, 'themes': Theme,
            'platforms': Platform, 'player_perspectives': PlayerPerspective,
        }
        return {
            'libraries': [
                {'uuid': row.uuid, 'name': row.name,
                 'platform_name': row.platform.name if row.platform else ''}
                for row in db.session.execute(select(Library).order_by(Library.name)).scalars().all()
            ],
            'taxonomies': {
                key: [{'id': row.id, 'name': row.name}
                      for row in db.session.execute(select(model).order_by(model.name)).scalars().all()]
                for key, model in taxonomies.items()
            },
            'categories': [{'value': value.name, 'label': value.value} for value in Category],
            'statuses': [{'value': value.name, 'label': value.value} for value in Status],
        }

    def game_state(self, game_uuid: str):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.game_provider_urls import provider_url_fields
        from oneirodex.utils.scanning import is_scan_job_running

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if not game:
            return None
        return {
            'game': {
                'uuid': game.uuid, 'igdb_id': game.igdb_id, 'name': game.name,
                'summary': game.summary or '', 'storyline': game.storyline or '',
                'url': game.url or '', 'full_disk_path': game.full_disk_path or '',
                'library_uuid': game.library_uuid, 'video_urls': game.video_urls or '',
                'aggregated_rating': game.aggregated_rating,
                'first_release_date': game.first_release_date.date().isoformat() if game.first_release_date else '',
                'status': game.status.name if game.status else '',
                'category': game.category.name if game.category else '',
                'developer': game.developer.name if game.developer else '',
                'publisher': game.publisher.name if game.publisher else '',
                'item_kind': game.item_kind or '',
                'genre_ids': [row.id for row in game.genres],
                'game_mode_ids': [row.id for row in game.game_modes],
                'theme_ids': [row.id for row in game.themes],
                'platform_ids': [row.id for row in game.platforms],
                'player_perspective_ids': [row.id for row in game.player_perspectives],
                'provider_urls': {row['key']: row['value'] or '' for row in provider_url_fields(game)},
            },
            'scan_running': is_scan_job_running(),
        }


def create_manual_identify_read_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ManualIdentifyReadData()

    @router.api_route('/api/admin/manual-identify/options', methods=['GET', 'HEAD'])
    def options(request: Request):
        return _read(request, flask_app, data, 'options', None, find_user,
                      find_token, commit_token_touch, load_user_id,
                      login_manager, database_scope)

    @router.api_route('/api/admin/manual-identify/{game_uuid}', methods=['GET', 'HEAD'])
    def game_state(game_uuid: str, request: Request):
        return _read(request, flask_app, data, 'game_state', game_uuid, find_user,
                      find_token, commit_token_touch, load_user_id,
                      login_manager, database_scope)

    return router


def _read(request, flask_app, data, operation, game_uuid, find_user, find_token,
          commit_token_touch, load_user_id, login_manager, database_scope):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        from oneirodex.utils.role_catalog import normalize_role
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload

        user = auth.user
        is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and normalize_role(getattr(user, 'role', None) or '') == 'admin'
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
            payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        else:
            payload = data.options() if operation == 'options' else data.game_state(game_uuid)
            if payload is None:
                payload, status = api_error_payload('Game could not be found.', code='not_found')
                response = JSONResponse(payload, status_code=status)
            else:
                response = JSONResponse(api_ok_payload(payload))
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie
                    _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values
    response.headers.setdefault('Cache-Control', 'no-store')
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
    return response


def mount_manual_identify_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_manual_identify_read_router(flask_app, **kwargs))
    return app
