"""Native FastAPI member favorites listing."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from werkzeug.datastructures import MultiDict

from .acquire_status import _login_redirect
from .batch_favorite import _finish
from .browse import _flask_json_response
from .request_auth import request_auth_context


class FavoritesData:
    """Keep the legacy favorites projection while moving its HTTP dispatch."""

    def payload(self, user, args):
        from sqlalchemy import and_, select
        from sqlalchemy.orm import joinedload

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Image, user_favorites, user_game_status
        from oneirodex.utils.browse_filters import apply_item_kind_filter, apply_name_filter
        from oneirodex.utils.cover_url import resolve_game_cover_url
        from oneirodex.utils.game_details_payload import browse_trailer_fields
        from oneirodex.utils.lifecycle import web_lifecycle_fields
        from oneirodex.utils.local_metadata import has_local_images, has_local_metadata
        from oneirodex.utils.client_lifecycle import load_lifecycle_map
        from oneirodex.utils.play_url import browse_play_fields, library_platform_key
        from oneirodex.utils.secondary_scrapers import game_card_flags
        from oneirodex.utils.global_settings import global_settings_row

        page = args.get('page', 1, type=int) or 1
        per_page = min(args.get('per_page', 20, type=int) or 20, 100)
        query = apply_game_access_filters(
            select(Game)
            .join(user_favorites, user_favorites.c.game_uuid == Game.uuid)
            .where(user_favorites.c.user_id == user.id)
            .options(joinedload(Game.genres), joinedload(Game.library))
            .order_by(Game.name.asc()),
            user,
        )
        query = apply_name_filter(query, args)
        query = apply_item_kind_filter(query, args)
        from oneirodex.utils.browse_query import _native_paginate

        games, total, pages = _native_paginate(
            query, page=page, per_page=per_page, session=db.session,
        )
        uuids = [game.uuid for game in games]
        statuses, covers = {}, {}
        if uuids:
            status_rows = db.session.execute(
                select(user_game_status.c.game_uuid, user_game_status.c.status).where(and_(
                    user_game_status.c.user_id == user.id,
                    user_game_status.c.game_uuid.in_(uuids),
                ))
            ).all()
            statuses = {row[0]: row[1] for row in status_rows}
            cover_rows = db.session.execute(
                select(Image).where(
                    Image.game_uuid.in_(uuids), Image.image_type == 'cover',
                )
            ).scalars().all()
            covers = {row.game_uuid: row for row in cover_rows}

        settings = global_settings_row()
        lifecycle_map = load_lifecycle_map(user.id)
        game_data = []
        for game in games:
            cover_url = resolve_game_cover_url(game, covers.get(game.uuid))
            local_override = bool(settings) and (
                bool(settings.use_local_metadata) and has_local_metadata(
                    game.full_disk_path,
                    settings.local_metadata_filename or 'oneirodex.json',
                )
                or bool(settings.use_local_images) and has_local_images(game.full_disk_path)
            )
            platform_key = library_platform_key(game)
            library = getattr(game, 'library', None)
            platform = getattr(library, 'platform', None) if library is not None else None
            platform_label = (
                (getattr(platform, 'value', None) or platform_key)
                if platform is not None else None
            )
            game_data.append({
                'uuid': game.uuid, 'name': game.name, 'cover_url': cover_url,
                'is_favorite': True, 'has_local_override': local_override,
                'library_platform': platform_key,
                'library_platform_label': platform_label,
                'badge_title_collision': bool(platform_key),
                'freshness_status': getattr(game, 'freshness_status', None),
                **browse_play_fields(game), **browse_trailer_fields(game),
                **game_card_flags(game),
                **web_lifecycle_fields(
                    game, user_id=user.id, client_state=lifecycle_map.get(game.uuid),
                ),
                'genres': [genre.name for genre in game.genres],
                'user_status': statuses.get(game.uuid),
            })
        return {
            'games': game_data, 'total': total,
            'pages': pages, 'current_page': page,
        }


def create_favorites_router(
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
    data = data_access or FavoritesData()

    @router.api_route('/api/favorites', methods=['GET', 'HEAD'])
    def favorites(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                args = MultiDict(request.query_params.multi_items())
                response = _flask_json_response(flask_app, data.payload(auth.user, args))
                if request.method == 'HEAD':
                    response.body = b''
            _finish(response, flask_app, auth)
            return response

    return router


def mount_favorites_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_favorites_router(flask_app, **kwargs))
    return app
