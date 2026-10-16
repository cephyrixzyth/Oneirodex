"""FastAPI mutations for the admin manual-identify editor."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .request_auth import request_auth_context


class ManualIdentifyMutationData:
    """Database and filesystem boundary for manual game identification."""

    def update(self, app, game_uuid: str, body, actor):
        import os
        from datetime import datetime, timezone

        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import (
            Category, Developer, Game, GameMode, Genre, Library, Platform,
            PlayerPerspective, Publisher, Status, Theme,
        )
        from oneirodex.utils.security import get_allowed_base_directories, is_safe_path

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if not game:
            return _failure('Game could not be found.', 'not_found')
        from oneirodex.utils.scanning import is_scan_job_running
        if is_scan_job_running():
            return _failure('A scan is running. Editing games is available again when it finishes.', 'conflict')
        library = db.session.get(Library, body.library_uuid)
        if not library:
            return _failure('Choose a valid library.', 'bad_request')
        allowed_bases = get_allowed_base_directories(app)
        if not allowed_bases:
            return _failure('Game editing is unavailable until a storage root is configured.', 'unavailable')
        safe, _path_error = is_safe_path(body.full_disk_path, allowed_bases, logger=app.logger)
        if not safe:
            return _failure('The selected game path is outside configured storage roots.', 'forbidden')
        if not os.path.isdir(body.full_disk_path) or not os.access(body.full_disk_path, os.R_OK):
            return _failure('The selected game folder does not exist or cannot be read.', 'bad_request')
        if body.igdb_id != game.igdb_id:
            duplicate = db.session.execute(
                select(Game).where(Game.igdb_id == body.igdb_id, Game.id != game.id).with_for_update()
            ).scalars().first()
            if duplicate:
                return _failure('That IGDB ID is already used by another game.', 'conflict')

        relations = (
            ('genre_ids', 'genres', Genre),
            ('game_mode_ids', 'game_modes', GameMode),
            ('theme_ids', 'themes', Theme),
            ('platform_ids', 'platforms', Platform),
            ('player_perspective_ids', 'player_perspectives', PlayerPerspective),
        )
        resolved = {}
        for input_key, relation_key, model in relations:
            ids = getattr(body, input_key)
            rows = db.session.execute(select(model).where(model.id.in_(ids))).scalars().all() if ids else []
            if len(rows) != len(set(ids)):
                return _failure('One or more selected metadata options are no longer available.', 'bad_request')
            resolved[relation_key] = rows

        igdb_changed = game.igdb_id != body.igdb_id
        game.igdb_id = body.igdb_id
        game.name = body.name[:255]
        game.summary = body.summary[:4096] or None
        game.storyline = body.storyline[:4096] or None
        game.url = body.url[:4096] or None
        game.full_disk_path = body.full_disk_path
        game.library_uuid = library.uuid
        game.video_urls = body.video_urls[:4096] or None
        game.aggregated_rating = body.aggregated_rating
        game.first_release_date = datetime.combine(
            body.first_release_date, datetime.min.time(), tzinfo=timezone.utc,
        ) if body.first_release_date else None
        game.status = Status[body.status] if body.status else None
        game.category = Category[body.category] if body.category else None
        game.item_kind = normalize_item_kind(body.item_kind) if body.item_kind else game.item_kind
        game.genres = resolved['genres']
        game.game_modes = resolved['game_modes']
        game.themes = resolved['themes']
        game.platforms = resolved['platforms']
        game.player_perspectives = resolved['player_perspectives']
        for raw_name, model, relation in ((body.developer, Developer, 'developer'), (body.publisher, Publisher, 'publisher')):
            name = sanitize_string_input(raw_name, 255) if raw_name and raw_name != 'Not Found' else ''
            entity = db.session.execute(select(model).filter_by(name=name)).scalars().first() if name else None
            if name and not entity:
                entity = model(name=name)
                db.session.add(entity)
                db.session.flush()
            setattr(game, relation, entity)
        try:
            from oneirodex.utils.library_health import mark_game_path_ok
            from oneirodex.utils.game_provider_urls import apply_provider_urls
            from oneirodex.utils.helpers.fs import get_folder_size_in_bytes_updates, read_first_nfo_content
            from oneirodex.utils.rom_language import apply_rom_language_fields

            mark_game_path_ok(game)
            apply_rom_language_fields(game, body.full_disk_path or body.name)
            game.size = get_folder_size_in_bytes_updates(
                game.full_disk_path, allowed_bases=allowed_bases, logger=app.logger,
            )
            game.nfo_content = read_first_nfo_content(
                game.full_disk_path, allowed_bases=allowed_bases, logger=app.logger,
            )
            provider_data = {f'provider_url_{key}': value for key, value in body.provider_urls.items()}
            apply_provider_urls(game, provider_data)
            if body.igdb_id < 2_000_000_420:
                from oneirodex.utils.game_core import ensure_manual_identify_taxonomy
                ensure_manual_identify_taxonomy(game, body.igdb_id)
            game.date_identified = datetime.now(timezone.utc)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return _failure('A game with this catalog ID already exists.', 'conflict')
        except (SQLAlchemyError, OSError, ValueError):
            db.session.rollback()
            app.logger.exception('Manual game edit failed')
            return _failure('The game could not be updated. Check the game details and try again.', 'internal')

        _event(f'Game {game.name} updated by admin {actor.name}', actor)
        if igdb_changed:
            from oneirodex.utils.background import run_in_background
            from oneirodex.utils.scanning import refresh_images_in_background
            run_in_background(app, refresh_images_in_background, game_uuid, name=f'oneirodex-refresh-images-{game_uuid[:8]}')
        return {'game_uuid': game_uuid, 'redirect_url': '/libraries'}

    def create(self, app, body, actor, *, from_unmatched: bool):
        import os
        from datetime import datetime, timezone

        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError, SQLAlchemyError

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import (
            Category, Developer, Game, GameMode, GameURL, Genre, Library,
            Platform, PlayerPerspective, Publisher, Status, Theme, UnmatchedFolder,
        )
        from oneirodex.utils.security import (
            get_allowed_base_directories, is_safe_path, sanitize_path_for_logging,
        )
        from oneirodex.utils.event_logging import log_system_event

        library = db.session.get(Library, body.library_uuid)
        if not library:
            return _failure('Choose a valid library.', 'bad_request')
        allowed_bases = get_allowed_base_directories(app)
        if not allowed_bases:
            return _failure('Manual identify is unavailable until a storage root is configured.', 'unavailable')
        safe, _path_error = is_safe_path(body.full_disk_path, allowed_bases, logger=app.logger)
        if not safe:
            log_system_event(
                f'Manual identify path validation failed for admin {actor.name}: {sanitize_path_for_logging(body.full_disk_path)}',
                event_type='security', event_level='warning', audit_user=getattr(actor, 'id', None),
            )
            return _failure('The selected game path is outside configured storage roots.', 'forbidden')
        if not os.path.isdir(body.full_disk_path) or not os.access(body.full_disk_path, os.R_OK):
            return _failure('The selected game folder does not exist or cannot be read.', 'bad_request')

        is_custom_game = body.igdb_id >= 2_000_000_420
        if not is_custom_game:
            from oneirodex.utils.game_core import check_existing_game_by_igdb_id
            if check_existing_game_by_igdb_id(body.igdb_id):
                return _failure('A game with this IGDB ID already exists.', 'conflict')
        relations = (
            ('genre_ids', 'genres', Genre),
            ('game_mode_ids', 'game_modes', GameMode),
            ('theme_ids', 'themes', Theme),
            ('platform_ids', 'platforms', Platform),
            ('player_perspective_ids', 'player_perspectives', PlayerPerspective),
        )
        resolved = {}
        for input_key, relation_key, model in relations:
            ids = getattr(body, input_key)
            rows = db.session.execute(select(model).where(model.id.in_(ids))).scalars().all() if ids else []
            if len(rows) != len(set(ids)):
                return _failure('One or more selected metadata options are no longer available.', 'bad_request')
            resolved[relation_key] = rows

        from oneirodex.utils.functions import read_first_nfo_content, sanitize_string_input
        from oneirodex.utils.item_kind import normalize_item_kind
        cover = None
        if is_custom_game:
            root_path = (app.config.get('APPLICATION_ROOT') or '').rstrip('/')
            cover = f'{root_path}{app.static_url_path or "/static"}/newstyle/default_cover.jpg'
        game = Game(
            igdb_id=body.igdb_id, name=body.name, summary=body.summary or None,
            storyline=body.storyline or None, url=body.url or None,
            full_disk_path=body.full_disk_path, cover=cover,
            category=Category[body.category] if body.category else None,
            status=Status[body.status] if body.status else None,
            first_release_date=datetime.combine(body.first_release_date, datetime.min.time(), tzinfo=timezone.utc) if body.first_release_date else None,
            video_urls=body.video_urls or None, aggregated_rating=body.aggregated_rating,
            library_uuid=library.uuid,
            item_kind=normalize_item_kind(body.item_kind) if body.item_kind else ('game' if is_custom_game else None),
            nfo_content=read_first_nfo_content(
                body.full_disk_path, allowed_bases=allowed_bases, logger=app.logger,
            ),
            **resolved,
        )
        if not is_custom_game:
            from oneirodex.utils.game_core import ensure_manual_identify_taxonomy
            ensure_manual_identify_taxonomy(game, body.igdb_id)
        for raw_name, model, relation in (
            (body.developer, Developer, 'developer'), (body.publisher, Publisher, 'publisher'),
        ):
            name = sanitize_string_input(raw_name, 255) if raw_name and raw_name != 'Not Found' else ''
            if name:
                row = db.session.execute(select(model).filter_by(name=name)).scalars().first()
                if not row:
                    row = model(name=name)
                    db.session.add(row)
                    db.session.flush()
                setattr(game, relation, row)
        try:
            try:
                from oneirodex.utils.rom_language import apply_rom_language_fields
                apply_rom_language_fields(game, body.full_disk_path or body.name)
            except Exception:
                pass
            db.session.add(game)
            for provider, link in body.provider_urls.items():
                if link:
                    db.session.add(GameURL(game=game, url_type=provider, url=link.strip()))
            unmatched = db.session.execute(
                select(UnmatchedFolder).filter_by(folder_path=body.full_disk_path)
            ).scalars().first()
            if unmatched:
                db.session.delete(unmatched)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return _failure('A game with this catalog ID already exists.', 'conflict')
        except SQLAlchemyError:
            db.session.rollback()
            log_system_event(
                f'Database error manually identifying game for admin {actor.name}',
                event_type='error', event_level='error', audit_user=getattr(actor, 'id', None),
            )
            return _failure('The game could not be saved. Please try again.', 'internal')

        try:
            from oneirodex.utils.global_settings import global_settings_row
            from oneirodex.utils.local_metadata import write_local_metadata
            settings = global_settings_row()
            if settings and settings.write_local_metadata:
                write_local_metadata(
                    full_disk_path=body.full_disk_path, igdb_id=body.igdb_id,
                    game_title=body.name, manually_verified=True,
                    filename=settings.local_metadata_filename or 'oneirodex.json',
                    allowed_bases=allowed_bases,
                )
        except Exception:
            app.logger.exception('Could not write local metadata for manually identified game')

        game_uuid = game.uuid
        from oneirodex.utils.background import run_in_background
        from oneirodex.utils.scanning import refresh_images_in_background
        run_in_background(app, refresh_images_in_background, game_uuid,
                          name=f'oneirodex-refresh-images-{str(game_uuid)[:8]}')
        log_system_event(
            f"Game '{body.name}' added manually by admin {actor.name}",
            event_type='game', event_level='information', audit_user=getattr(actor, 'id', None),
        )
        return {'game_uuid': game_uuid,
                'redirect_url': '/admin/unmatched' if from_unmatched else '/libraries'}


def create_manual_identify_mutation_router(
    app, *, find_user: Callable[[int], Any | None], find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None], load_user_id=None, login_manager=None,
    data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ManualIdentifyMutationData()

    @router.post('/api/admin/manual-identify', include_in_schema=False)
    async def create(request: Request):
        return await _write(request, app, data, 'create', find_user, find_token,
                            commit_token_touch, load_user_id, login_manager, database_scope)

    @router.put('/api/admin/manual-identify/{game_uuid}', include_in_schema=False)
    async def update(game_uuid: str, request: Request):
        return await _write(request, app, data, 'update', find_user, find_token,
                            commit_token_touch, load_user_id, login_manager, database_scope,
                            game_uuid=game_uuid)

    return router


async def _write(request, app, data, action, find_user, find_token, commit_token_touch,
                 load_user_id, login_manager, database_scope, game_uuid=None):
    scope = database_scope(app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        from .csrf_compat import csrf_error_response
        from .acquire_status import _login_redirect
        from oneirodex.utils.role_catalog import normalize_role
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        from oneirodex.utils.security_headers import security_header_values
        from pydantic import ValidationError

        response = csrf_error_response(request, auth.session_data, app.config) if auth.token is None else None
        if response is None and auth.user is None:
            response = _login_redirect(app, request, login_manager, auth)
        if response is None and (
            normalize_role(getattr(auth.user, 'role', None)) != 'admin'
            or (auth.token is not None and not auth.has_scope('admin'))
        ):
            payload, status = api_error_payload('Admin required', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        if response is None:
            from oneirodex.schemas.manual_identify import ManualIdentifyBody
            from oneirodex.utils.validation import format_validation_errors
            try:
                raw = await request.json()
            except Exception:
                raw = {}
            try:
                body = ManualIdentifyBody.model_validate(raw if isinstance(raw, dict) else {})
            except ValidationError as exc:
                payload, status = api_error_payload(
                    'Invalid request.', code='unprocessable', detail=format_validation_errors(exc),
                )
                response = JSONResponse(payload, status_code=status)
            else:
                if action == 'create':
                    result = data.create(
                        app, body, auth.user,
                        from_unmatched=request.query_params.get('from_unmatched') == 'true',
                    )
                else:
                    result = data.update(app, game_uuid, body, auth.user)
                if 'error' in result:
                    payload, status = api_error_payload(
                        result['error'], code=result['code'], status=result.get('status'),
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    response = JSONResponse(api_ok_payload(result), status_code=201 if action == 'create' else 200)
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie
            _set_session_cookie(response, app, auth)
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(app.config).items():
            response.headers.setdefault(key, value)
        return response


def mount_manual_identify_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_manual_identify_mutation_router(flask_app, **kwargs))
    return app


def _failure(message, code):
    return {'error': message, 'code': code}


def _event(message, actor):
    from oneirodex.utils.event_logging import log_system_event
    log_system_event(
        message, event_type='game', event_level='information',
        audit_user=getattr(actor, 'id', None),
    )


def normalize_item_kind(value):
    from oneirodex.utils.item_kind import normalize_item_kind as normalize
    return normalize(value)


def sanitize_string_input(value, max_length):
    from oneirodex.utils.functions import sanitize_string_input as sanitize
    return sanitize(value, max_length)
