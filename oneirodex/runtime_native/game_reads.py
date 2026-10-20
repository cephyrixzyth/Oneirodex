"""Native FastAPI reads for the member game-detail surfaces."""
from __future__ import annotations

import re
import email.utils
import mimetypes
import os
import uuid
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, Response, StreamingResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


class GameReadData:
    """Adapter over existing game payload builders and access policy."""

    def game(self, game_uuid: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

    def can_access(self, user, game) -> bool:
        from oneirodex.utils.library_acl import user_can_access_game

        return bool(user_can_access_game(user, game))

    def allowed_bases(self, app):
        from oneirodex.utils.security import get_allowed_base_directories

        return get_allowed_base_directories(app)

    def safe_path(self, path, allowed_bases):
        from oneirodex.utils.security import is_safe_path

        return is_safe_path(path, allowed_bases)

    def local_image_path(self, root, image_type, index):
        from oneirodex.utils.local_metadata import get_local_cover_path, get_local_screenshots

        if image_type == 'cover':
            return get_local_cover_path(root)
        if image_type == 'screenshot':
            screenshots = get_local_screenshots(root)
            return screenshots[index] if 0 <= index < len(screenshots) else None
        return None

    def open_local_image(self, root, path):
        from oneirodex.utils.security import open_plain_file_within

        return open_plain_file_within(root, path, base_is_resolved=True)

    def library(self, library_uuid: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library

        return db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalars().first()

    def can_access_library(self, user, library) -> bool:
        from oneirodex.utils.library_acl import user_can_access_library

        return bool(user_can_access_library(user, getattr(library, 'uuid', None)))

    def move_game(self, game, target_library, user):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.event_logging import log_system_event

        game.library_uuid = target_library.uuid
        db.session.commit()
        log_system_event(
            f'Game {game.name} moved to library {target_library.name} by user {user.name}',
            event_type='game', event_level='information',
            audit_user=getattr(user, 'id', None),
        )
        return {'message': f'Game moved to {target_library.name}'}

    def set_input_family(self, game, input_family):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.secondary_scrapers import game_input_family

        game.input_family = input_family
        db.session.commit()
        from oneirodex.utils.secondary_scrapers import INPUT_FAMILY_VALUES

        return {
            'uuid': game.uuid,
            'input_family': game_input_family(game),
            'families': list(INPUT_FAMILY_VALUES),
        }

    def next_custom_igdb_id(self):
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        base_custom_id = 2000000420
        highest_custom_id = db.session.execute(
            select(func.max(Game.igdb_id)).filter(Game.igdb_id >= base_custom_id)
        ).scalar()
        return base_custom_id if highest_custom_id is None else highest_custom_id + 1

    def details(self, game, user):
        from oneirodex.utils.game_details_payload import build_game_details_payload

        return build_game_details_payload(game, user)

    def more_from(self, game, user):
        from oneirodex.utils.game_more_from import build_more_from

        return build_more_from(game, user)

    def editions(self, game, user):
        from oneirodex.utils.game_editions import editions_preview_payload

        return editions_preview_payload(game, user)

    def versions(self, game, _user):
        from oneirodex.utils.game_versions import list_game_versions

        versions = list_game_versions(game)
        return {
            'game_uuid': game.uuid,
            'versions': [
                {
                    'kind': version['kind'],
                    'id': version['id'],
                    'uuid': version['uuid'],
                    'label': version['label'],
                    'is_default': version['is_default'],
                    'size': version.get('size'),
                    'path_missing': bool(version.get('path_missing')),
                    'downloadable': bool(version.get('downloadable')),
                }
                for version in versions
            ],
        }

    def freshness(self, game, _user):
        from oneirodex.utils.freshness import freshness_public_view

        return freshness_public_view(game)

    def check_freshness(self, game, user):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.freshness import check_and_store_freshness

        _ = list(game.updates or [])
        _ = list(game.extras or [])
        _ = list(game.urls or [])
        result = check_and_store_freshness(game, commit=True, db_session=db.session)
        log_system_event(
            f"Freshness check for {game.name}: {result.get('status')}",
            event_type='game', event_level='information',
            audit_user=getattr(user, 'id', None) or 'system',
        )
        return result

    def search(self, args, user):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, GameMode, Genre, PlayerPerspective, Theme
        from oneirodex.utils.library_acl import (
            apply_game_access_filters,
            user_can_access_library,
        )

        query = args.get('query', '').strip()
        if not query:
            return []
        statement = apply_game_access_filters(
            select(Game).filter(Game.name.ilike(f'%{query}%')),
            user,
        )
        library_uuid = args.get('library_uuid')
        genre = args.get('genre')
        rating = args.get('rating', type=int)
        game_mode = args.get('game_mode')
        player_perspective = args.get('player_perspective')
        theme = args.get('theme')

        if library_uuid:
            if not user_can_access_library(user, library_uuid):
                return []
            statement = statement.filter(Game.library_uuid == library_uuid)
        if genre:
            statement = statement.filter(Game.genres.any(Genre.name == genre))
        if rating is not None:
            statement = statement.filter(Game.rating >= rating)
        if game_mode:
            statement = statement.filter(Game.game_modes.any(GameMode.name == game_mode))
        if player_perspective:
            statement = statement.filter(
                Game.player_perspectives.any(PlayerPerspective.name == player_perspective)
            )
        if theme:
            statement = statement.filter(Game.themes.any(Theme.name == theme))
        games = db.session.execute(statement).scalars().all()
        return [{'id': game.id, 'uuid': game.uuid, 'name': game.name} for game in games]

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def screenshots(self, game_uuid: str, _user):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Image
        from oneirodex.utils.game_details_payload import (
            _static_image_url,
            local_image_on_disk,
        )

        rows = db.session.execute(select(Image).filter_by(
            game_uuid=game_uuid, image_type='screenshot',
        )).scalars().all()
        return [
            _static_image_url(row.url)
            for row in rows
            if getattr(row, 'is_downloaded', False) and row.url
            and local_image_on_disk(row.url)
        ]

    def assists_enabled(self, *, config=None):
        from oneirodex.utils.assist_packs import assists_enabled

        return bool(assists_enabled(config=config))

    def assists(self, game, _user, *, config=None, package_root=None):
        from oneirodex.utils.assist_packs import load_assist_pack, overlay_links_for

        pack = load_assist_pack(game.uuid, config=config, package_root=package_root)
        return {'enabled': True, 'pack': pack, 'overlay_links': overlay_links_for(game, pack)}

    def save_assists(self, game, body, *, config=None, package_root=None):
        import json

        from oneirodex.utils.assist_packs import load_assist_pack, overlay_links_for, pack_path

        pack = {
            'title': body.title or game.name,
            'policy': 'single_player_offline_only',
            'toggles': [item.model_dump(exclude_none=True) for item in body.toggles],
            'overlay_links': [item.model_dump() for item in body.overlay_links],
        }
        with open(pack_path(game.uuid, config=config, package_root=package_root), 'w', encoding='utf-8') as stream:
            json.dump(pack, stream, indent=2)
        saved = load_assist_pack(game.uuid, config=config, package_root=package_root)
        return {'pack': saved, 'overlay_links': overlay_links_for(game, saved)}

    def images(self, game_uuid: str, _user, *, raw_kind: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Image
        from oneirodex.utils.game_details_payload import _static_image_url
        from oneirodex.utils.image_kinds import (
            IMAGE_KIND_ORDER,
            image_kinds_error_message,
            parse_image_kind,
        )

        try:
            kind_filter = parse_image_kind(raw_kind, default=None, allow_all=True)
        except ValueError as exc:
            raise ValueError(image_kinds_error_message()) from exc
        statement = select(Image).filter_by(game_uuid=game_uuid)
        if kind_filter != 'all':
            statement = statement.filter(Image.image_type == kind_filter)
        rows = db.session.execute(
            statement.order_by(Image.image_type.asc(), Image.created_at.desc())
        ).scalars().all()
        images = []
        for image in rows:
            local_url = None
            if image.url:
                if image.url.startswith(('http://', 'https://', '/')):
                    local_url = image.url
                else:
                    local_url = _static_image_url(image.url)
            images.append({
                'id': image.id,
                'image_type': image.image_type,
                'kind': image.image_type,
                'url': local_url,
                'download_url': image.download_url,
                'is_downloaded': bool(image.is_downloaded),
            })
        return {
            'game_uuid': game_uuid,
            'kind_filter': kind_filter,
            'allowed_kinds': list(IMAGE_KIND_ORDER),
            'images': images,
            'count': len(images),
        }


def create_game_reads_router(
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
    uses_native_data = data_access is None
    data = data_access or GameReadData()

    def request_scope():
        return database_scope(flask_app) if database_scope else nullcontext()

    def assists_enabled():
        return data.assists_enabled(config=flask_app.config) if uses_native_data else data.assists_enabled()

    def save_assists_payload(game, body):
        if uses_native_data:
            return data.save_assists(game, body, config=flask_app.config, package_root=flask_app.root_path)
        return data.save_assists(game, body)

    def read(request: Request, game_uuid: str, operation: str, *, required_scope=None, operation_args=None):
        with request_scope():
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None and required_scope and not auth.has_scope(required_scope):
                response = _api_error(
                    f'Missing scope: {required_scope}', 'forbidden',
                    detail={'required_scope': required_scope},
                )
            if response is None:
                if operation == 'assists' and not assists_enabled():
                    response = JSONResponse({'enabled': False, 'pack': None})
                    game = None
                elif operation == 'versions' and not _UUID_RE.fullmatch(game_uuid):
                    response = _api_error('Invalid game UUID', 'bad_request')
                    game = None
                else:
                    game = data.game(game_uuid)
                if response is not None:
                    pass
                elif game is None:
                    if response is None:
                        response = _api_error('Game not found', 'not_found')
                elif response is None and not data.can_access(auth.user, game):
                    message = 'Access denied' if operation == 'versions' else 'You do not have access to that game'
                    response = _api_error(message, 'forbidden')
                elif response is None:
                    try:
                        if operation == 'screenshots':
                            payload = data.screenshots(game_uuid, auth.user)
                        elif operation == 'images':
                            payload = data.images(game_uuid, auth.user, **(operation_args or {}))
                        else:
                            if operation == 'assists' and uses_native_data:
                                payload = data.assists(game, auth.user, config=flask_app.config, package_root=flask_app.root_path)
                            else:
                                payload = getattr(data, operation)(game, auth.user)
                    except ValueError as exc:
                        response = _api_error(str(exc), 'bad_request')
                        payload = None
                    if response is None and operation not in (
                        'details', 'versions', 'freshness', 'screenshots', 'images', 'assists',
                    ):
                        from oneirodex.utils.api_contract import api_ok_payload

                        payload = api_ok_payload(payload)
                    if response is None:
                        response = JSONResponse(payload)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/game/{game_uuid}/local_image/{image_type}', methods=['GET', 'HEAD'])
    def local_game_image(game_uuid: str, image_type: str, request: Request):
        from .oidc_status import _set_session_cookie
        from .response_compat import flask_http_error_response

        with request_scope():
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            handle = None
            if response is None:
                try:
                    uuid.UUID(game_uuid, version=4)
                except (TypeError, ValueError, AttributeError):
                    response = flask_http_error_response(400, 'Invalid game UUID', head=request.method == 'HEAD')
            if response is None:
                game = data.game(game_uuid)
                if game is None:
                    response = flask_http_error_response(404, 'Game not found', head=request.method == 'HEAD')
                elif not data.can_access(auth.user, game):
                    response = flask_http_error_response(403, head=request.method == 'HEAD')
            if response is None:
                allowed_bases = data.allowed_bases(flask_app)
                if not allowed_bases:
                    response = flask_http_error_response(500, 'Server configuration error', head=request.method == 'HEAD')
                else:
                    try:
                        real_game = os.path.realpath(game.full_disk_path)
                    except (OSError, TypeError, ValueError):
                        real_game = game.full_disk_path
                    safe, _reason = data.safe_path(real_game, allowed_bases)
                    if not safe:
                        response = flask_http_error_response(403, 'Access denied', head=request.method == 'HEAD')
                    elif image_type not in {'cover', 'screenshot'}:
                        response = flask_http_error_response(400, 'Invalid image type', head=request.method == 'HEAD')
                    else:
                        try:
                            index = int(request.query_params.get('index', '0'))
                        except (TypeError, ValueError):
                            index = 0
                        image_path = data.local_image_path(real_game, image_type, index)
                        if image_path:
                            try:
                                handle = data.open_local_image(real_game, image_path)
                            except (FileNotFoundError, OSError, ValueError):
                                handle = None
                        if handle is None:
                            response = flask_http_error_response(404, 'Image not found', head=request.method == 'HEAD')
                        else:
                            response = _local_image_response(request, handle, image_path)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.api_route('/api/games/{game_uuid}/details', methods=['GET', 'HEAD'])
    def game_details(game_uuid: str, request: Request):
        return read(request, game_uuid, 'details')

    @router.api_route('/api/get_next_custom_igdb_id', methods=['GET', 'HEAD'])
    def next_custom_igdb_id(request: Request):
        with request_scope():
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                try:
                    response = JSONResponse({'next_id': data.next_custom_igdb_id()})
                except Exception:  # noqa: BLE001 — retain the legacy generic failure
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(
                        'Could not work out the next custom IGDB id', code='internal',
                    )
                    response = JSONResponse(payload, status_code=status)
            _finish(response, flask_app, request, auth)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/move_game_to_library')
    async def move_game_to_library(request: Request):
        with request_scope():
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            from oneirodex.utils.role_catalog import role_at_least

            if response is None and (
                not role_at_least(getattr(auth.user, 'role', None), 'librarian')
                or (auth.token is not None and not auth.has_scope('admin'))
            ):
                response = _api_error('Librarian required', 'forbidden')
            if response is None:
                payload = await _json_object(request)
                game_uuid = payload.get('game_uuid')
                target_library_uuid = payload.get('target_library_uuid')
                if not game_uuid or not target_library_uuid:
                    response = _api_error(
                        'game_uuid and target_library_uuid are required', 'bad_request',
                    )
            if response is None:
                game = data.game(game_uuid)
                target_library = data.library(target_library_uuid)
                if game is None or target_library is None:
                    response = _api_error('Game or target library not found', 'not_found')
                elif not data.can_access(auth.user, game):
                    response = _api_error('You do not have access to that game', 'forbidden')
                elif not data.can_access_library(auth.user, target_library):
                    response = _api_error('You do not have access to that library', 'forbidden')
                else:
                    try:
                        response = _success(data.move_game(game, target_library, auth.user))
                    except Exception:  # noqa: BLE001 — retain the legacy generic failure
                        data.rollback()
                        flask_app.logger.warning('move_game_to_library failed')
                        response = _api_error('Could not move the game', 'internal')
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/search', methods=['GET', 'HEAD'])
    def game_search(request: Request):
        from werkzeug.datastructures import MultiDict

        with request_scope():
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                args = MultiDict(request.query_params.multi_items())
                query = args.get('query', '').strip()
                if len(query) > 100:
                    response = _api_error('Search term too long', 'bad_request')
                else:
                    response = JSONResponse(data.search(args, auth.user))
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/games/{game_uuid}/more_from', methods=['GET', 'HEAD'])
    def game_more_from(game_uuid: str, request: Request):
        return read(request, game_uuid, 'more_from')

    @router.api_route('/api/games/{game_uuid}/editions', methods=['GET', 'HEAD'])
    def game_editions(game_uuid: str, request: Request):
        return read(request, game_uuid, 'editions')

    @router.api_route('/api/games/{game_uuid}/versions', methods=['GET', 'HEAD'])
    def game_versions(game_uuid: str, request: Request):
        return read(request, game_uuid, 'versions', required_scope='read:library')

    @router.api_route('/api/games/{game_uuid}/freshness', methods=['GET', 'HEAD'])
    def game_freshness(game_uuid: str, request: Request):
        return read(request, game_uuid, 'freshness')

    @router.api_route('/api/games/{game_uuid}/assists', methods=['GET', 'HEAD'])
    def game_assists(game_uuid: str, request: Request):
        return read(request, game_uuid, 'assists')

    @router.patch('/api/games/{game_uuid}/input_family')
    async def set_game_input_family(game_uuid: str, request: Request):
        with request_scope():
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            from oneirodex.utils.role_catalog import role_at_least

            if response is None and (
                not role_at_least(getattr(auth.user, 'role', None), 'librarian')
                or (auth.token is not None and not auth.has_scope('admin'))
            ):
                response = _api_error('Librarian required', 'forbidden')
            if response is None:
                try:
                    from oneirodex.schemas.arcade import InputFamilyBody
                    from oneirodex.utils.validation import format_validation_errors

                    body = InputFamilyBody.model_validate(await _json_object(request))
                except ValidationError as exc:
                    response = _api_error(
                        'Invalid request.', 'unprocessable',
                        detail=format_validation_errors(exc),
                    )
                except ValueError:
                    response = _api_error('Invalid request.', 'bad_request')
                if response is None:
                    game = data.game(game_uuid)
                    if game is None:
                        response = _api_error('Game not found', 'not_found')
                    elif not data.can_access(auth.user, game):
                        response = _api_error('Forbidden', 'forbidden')
                    else:
                        try:
                            payload = data.set_input_family(game, body.input_family)
                            response = _success(payload)
                        except Exception:  # noqa: BLE001 — match the legacy safe failure contract
                            data.rollback()
                            flask_app.logger.warning('input_family save failed for %s', game_uuid)
                            response = _api_error("Couldn't save the control family.", 'internal')
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/games/{game_uuid}/assists', methods=['POST', 'PUT'])
    async def save_game_assists(game_uuid: str, request: Request):
        with request_scope():
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            from oneirodex.utils.role_catalog import normalize_role

            if response is None and (
                normalize_role(getattr(auth.user, 'role', None)) != 'admin'
                or (auth.token is not None and not auth.has_scope('admin'))
            ):
                response = _api_error('Admin required', 'forbidden')
            if response is None and not assists_enabled():
                response = _api_error('ENABLE_GAME_ASSISTS is off', 'forbidden')
            if response is None:
                try:
                    from oneirodex.schemas.assists import AssistPackBody
                    from oneirodex.utils.validation import format_validation_errors

                    body = AssistPackBody.model_validate(await _json_object(request))
                except ValidationError as exc:
                    response = _api_error(
                        'Invalid request.', 'unprocessable',
                        detail=format_validation_errors(exc),
                    )
                if response is None:
                    game = data.game(game_uuid)
                    if game is None:
                        response = _api_error('Game not found', 'not_found')
                    else:
                        response = _success(save_assists_payload(game, body))
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/games/{game_uuid}/freshness/check')
    def game_freshness_check(game_uuid: str, request: Request):
        with request_scope():
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.token is not None and not auth.has_scope('write:library'):
                response = _api_error('Missing scope: write:library', 'forbidden')
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                game = data.game(game_uuid)
                if game is None:
                    response = _api_error('Game not found', 'not_found')
                elif not data.can_access(auth.user, game):
                    response = _api_error('You do not have access to that game', 'forbidden')
                else:
                    try:
                        response = _flask_json_response(
                            flask_app, data.check_freshness(game, auth.user),
                        )
                    except Exception:  # noqa: BLE001 — preserve legacy safe failure response
                        data.rollback()
                        flask_app.logger.warning('freshness check failed for game %s', game_uuid)
                        response = _api_error('Freshness check failed', 'internal')
            _finish(response, flask_app, request, auth)
            return response

    @router.api_route('/api/game_screenshots/{game_uuid}', methods=['GET', 'HEAD'])
    def game_screenshots(game_uuid: str, request: Request):
        return read(request, game_uuid, 'screenshots')

    @router.api_route('/api/game_images/{game_uuid}', methods=['GET', 'HEAD'])
    def game_images(game_uuid: str, request: Request):
        raw_kind = (
            _first_query_value(request, 'kind')
            or _first_query_value(request, 'type')
            or _first_query_value(request, 'image_type')
            or 'all'
        )
        return read(
            request, game_uuid, 'images', operation_args={'raw_kind': raw_kind},
        )

    return router


def mount_game_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_game_reads_router(flask_app, **kwargs))
    return app


def _api_error(message: str, code: str, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, detail=detail)
    return JSONResponse(payload, status_code=status)


def _local_image_response(request, handle, path):
    """Serve the already-vetted descriptor with validators and byte ranges."""
    info = os.fstat(handle.fileno())
    size = info.st_size
    etag = f'"{info.st_mtime_ns:x}-{size:x}"'
    modified = email.utils.formatdate(info.st_mtime, usegmt=True)
    mime_type = mimetypes.guess_type(path)[0] or 'image/jpeg'
    headers = {
        'Accept-Ranges': 'bytes', 'ETag': etag, 'Last-Modified': modified,
        'Content-Type': mime_type, 'Content-Length': str(size),
    }
    inm = request.headers.get('if-none-match')
    if inm:
        candidates = [item.strip() for item in inm.split(',')]
        if '*' in candidates or any(item.removeprefix('W/').strip() == etag for item in candidates):
            handle.close()
            return Response(status_code=304, headers={k: v for k, v in headers.items() if k != 'Content-Length'})
    else:
        ims = request.headers.get('if-modified-since')
        if ims:
            try:
                parsed = email.utils.parsedate_to_datetime(ims).timestamp()
                if int(info.st_mtime) <= int(parsed):
                    handle.close()
                    return Response(status_code=304, headers={k: v for k, v in headers.items() if k != 'Content-Length'})
            except (TypeError, ValueError, OverflowError):
                pass

    start, end = 0, max(size - 1, 0)
    range_header = request.headers.get('range')
    if_range = request.headers.get('if-range')
    if range_header and (not if_range or if_range == etag or if_range == modified):
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header.strip())
        if not match or size == 0:
            handle.close()
            return Response(status_code=416, headers={'Content-Range': f'bytes */{size}', 'Accept-Ranges': 'bytes'})
        first, last = match.groups()
        if not first:
            suffix = int(last or '0')
            if suffix <= 0:
                handle.close()
                return Response(status_code=416, headers={'Content-Range': f'bytes */{size}', 'Accept-Ranges': 'bytes'})
            start, end = max(size - suffix, 0), size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
            if start >= size or end < start:
                handle.close()
                return Response(status_code=416, headers={'Content-Range': f'bytes */{size}', 'Accept-Ranges': 'bytes'})
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
        headers['Content-Length'] = str(end - start + 1)
        status = 206
    else:
        status = 200

    if request.method == 'HEAD':
        handle.close()
        return Response(status_code=status, headers=headers)

    def body():
        remaining = end - start + 1 if size else 0
        try:
            handle.seek(start)
            while remaining:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            handle.close()

    return StreamingResponse(body(), status_code=status, headers=headers,
                             background=BackgroundTask(handle.close))


def _success(payload, *, status=200):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload), status_code=status)


async def _json_object(request):
    try:
        content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        is_json = content_type == 'application/json' or (
            content_type.startswith('application/') and content_type.endswith('+json')
        )
        return await request.json() if is_json else {}
    except Exception:  # noqa: BLE001 — silent JSON parsing matches Flask's helper
        return {}


def _flask_json_response(flask_app, payload):
    from starlette.responses import Response

    flask_response = flask_app.json.response(payload)
    return Response(
        content=flask_response.get_data(), status_code=flask_response.status_code,
        headers={'Content-Type': flask_response.headers.get('Content-Type', 'application/json')},
    )


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)


def _first_query_value(request: Request, name: str) -> str | None:
    values = request.query_params.getlist(name)
    return values[0] if values else None
