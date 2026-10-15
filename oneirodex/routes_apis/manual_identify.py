"""Native admin API for the manual game-identification form."""

from __future__ import annotations

from datetime import datetime, timezone
import os

from flask import current_app, request, url_for
from flask_login import login_required, current_user
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from werkzeug.datastructures import MultiDict

from oneirodex import db
from oneirodex.models import (
    Category, Developer, Game, GameMode, Genre, Library, Platform,
    GameURL, PlayerPerspective, Publisher, Status, Theme, UnmatchedFolder,
)
from oneirodex.schemas.manual_identify import ManualIdentifyBody
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.functions import read_first_nfo_content, sanitize_string_input
from oneirodex.utils.game_core import check_existing_game_by_igdb_id, ensure_manual_identify_taxonomy
from oneirodex.utils.item_kind import normalize_item_kind
from oneirodex.utils.security import get_allowed_base_directories, is_safe_path, sanitize_path_for_logging
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _no_store(response):
    response[0].headers['Cache-Control'] = 'no-store'
    return response


@apis_bp.route('/admin/manual-identify/options', methods=['GET'])
@login_required
@admin_required
def manual_identify_options():
    """Return the same library and taxonomy choices as the legacy form."""
    taxonomies = {
        'genres': Genre,
        'game_modes': GameMode,
        'themes': Theme,
        'platforms': Platform,
        'player_perspectives': PlayerPerspective,
    }
    payload = {
        'libraries': [
            {'uuid': row.uuid, 'name': row.name, 'platform_name': row.platform.name if row.platform else ''}
            for row in db.session.execute(select(Library).order_by(Library.name)).scalars().all()
        ],
        'taxonomies': {
            key: [{'id': row.id, 'name': row.name} for row in db.session.execute(select(model).order_by(model.name)).scalars().all()]
            for key, model in taxonomies.items()
        },
        'categories': [{'value': value.name, 'label': value.value} for value in Category],
        'statuses': [{'value': value.name, 'label': value.value} for value in Status],
    }
    return _no_store(api_ok(payload))


@apis_bp.route('/admin/manual-identify/<game_uuid>', methods=['GET'])
@login_required
@admin_required
def manual_identify_edit_state(game_uuid: str):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game could not be found.', code='not_found')
    from oneirodex.utils.game_provider_urls import provider_url_fields
    payload = {
        'game': {
            'uuid': game.uuid,
            'igdb_id': game.igdb_id,
            'name': game.name,
            'summary': game.summary or '',
            'storyline': game.storyline or '',
            'url': game.url or '',
            'full_disk_path': game.full_disk_path or '',
            'library_uuid': game.library_uuid,
            'video_urls': game.video_urls or '',
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
        'scan_running': __import__('oneirodex.utils.scanning', fromlist=['is_scan_job_running']).is_scan_job_running(),
    }
    return _no_store(api_ok(payload))


@apis_bp.route('/admin/manual-identify/<game_uuid>', methods=['PUT'])
@login_required
@admin_required
@validate_body(ManualIdentifyBody)
def update_manual_identified_game(game_uuid: str, body: ManualIdentifyBody):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game could not be found.', code='not_found')
    from oneirodex.utils.scanning import is_scan_job_running
    if is_scan_job_running():
        return api_error('A scan is running. Editing games is available again when it finishes.', code='conflict')
    library = db.session.get(Library, body.library_uuid)
    if not library:
        return api_error('Choose a valid library.', code='bad_request')
    allowed_bases = get_allowed_base_directories(current_app)
    if not allowed_bases:
        return api_error('Game editing is unavailable until a storage root is configured.', code='unavailable')
    safe, _path_error = is_safe_path(body.full_disk_path, allowed_bases)
    if not safe:
        return api_error('The selected game path is outside configured storage roots.', code='forbidden')
    if not os.path.isdir(body.full_disk_path) or not os.access(body.full_disk_path, os.R_OK):
        return api_error('The selected game folder does not exist or cannot be read.', code='bad_request')
    if body.igdb_id != game.igdb_id:
        duplicate = db.session.execute(
            select(Game).where(Game.igdb_id == body.igdb_id, Game.id != game.id).with_for_update()
        ).scalars().first()
        if duplicate:
            return api_error('That IGDB ID is already used by another game.', code='conflict')

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
            return api_error('One or more selected metadata options are no longer available.', code='bad_request')
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
    game.first_release_date = datetime.combine(body.first_release_date, datetime.min.time(), tzinfo=timezone.utc) if body.first_release_date else None
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
        from oneirodex.utils.functions import get_folder_size_in_bytes_updates
        from oneirodex.utils.rom_language import apply_rom_language_fields
        mark_game_path_ok(game)
        apply_rom_language_fields(game, body.full_disk_path or body.name)
        game.size = get_folder_size_in_bytes_updates(game.full_disk_path)
        game.nfo_content = read_first_nfo_content(game.full_disk_path)
        provider_data = MultiDict({f'provider_url_{key}': value for key, value in body.provider_urls.items()})
        apply_provider_urls(game, provider_data)
        if body.igdb_id < 2_000_000_420:
            ensure_manual_identify_taxonomy(game, body.igdb_id)
        game.date_identified = datetime.now(timezone.utc)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return api_error('A game with this catalog ID already exists.', code='conflict')
    except (SQLAlchemyError, OSError, ValueError):
        db.session.rollback()
        current_app.logger.exception('Manual game edit failed')
        return api_error('The game could not be updated. Check the game details and try again.', code='internal')
    log_system_event(f"Game {game.name} updated by admin {current_user.name}", event_type='game', event_level='information')
    if igdb_changed:
        from oneirodex.utils.background import run_in_background
        from oneirodex.utils.scanning import refresh_images_in_background
        run_in_background(current_app._get_current_object(), refresh_images_in_background, game_uuid, name=f'oneirodex-refresh-images-{game_uuid[:8]}')
    return api_ok({'game_uuid': game_uuid, 'redirect_url': '/libraries'})


@apis_bp.route('/admin/manual-identify', methods=['POST'])
@login_required
@admin_required
@validate_body(ManualIdentifyBody)
def create_manual_identified_game(body: ManualIdentifyBody):
    """Create a catalog game using the legacy identify route's side effects."""
    library = db.session.get(Library, body.library_uuid)
    if not library:
        return api_error('Choose a valid library.', code='bad_request')

    allowed_bases = get_allowed_base_directories(current_app)
    if not allowed_bases:
        return api_error('Manual identify is unavailable until a storage root is configured.', code='unavailable')
    safe, path_error = is_safe_path(body.full_disk_path, allowed_bases)
    if not safe:
        log_system_event(
            f"Manual identify path validation failed for admin {current_user.name}: {sanitize_path_for_logging(body.full_disk_path)}",
            event_type='security', event_level='warning',
        )
        return api_error('The selected game path is outside configured storage roots.', code='forbidden')
    if not os.path.isdir(body.full_disk_path) or not os.access(body.full_disk_path, os.R_OK):
        return api_error('The selected game folder does not exist or cannot be read.', code='bad_request')

    is_custom_game = body.igdb_id >= 2_000_000_420
    if not is_custom_game and check_existing_game_by_igdb_id(body.igdb_id):
        return api_error('A game with this IGDB ID already exists.', code='conflict')

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
            return api_error('One or more selected metadata options are no longer available.', code='bad_request')
        resolved[relation_key] = rows

    game = Game(
        igdb_id=body.igdb_id,
        name=body.name,
        summary=body.summary or None,
        storyline=body.storyline or None,
        url=body.url or None,
        full_disk_path=body.full_disk_path,
        cover=url_for('static', filename='newstyle/default_cover.jpg') if is_custom_game else None,
        category=Category[body.category] if body.category else None,
        status=Status[body.status] if body.status else None,
        first_release_date=datetime.combine(body.first_release_date, datetime.min.time(), tzinfo=timezone.utc) if body.first_release_date else None,
        video_urls=body.video_urls or None,
        aggregated_rating=body.aggregated_rating,
        library_uuid=library.uuid,
        item_kind=normalize_item_kind(body.item_kind) if body.item_kind else ('game' if is_custom_game else None),
        nfo_content=read_first_nfo_content(body.full_disk_path),
        **resolved,
    )
    if not is_custom_game:
        ensure_manual_identify_taxonomy(game, body.igdb_id)

    for raw_name, model, relation in (
        (body.developer, Developer, 'developer'),
        (body.publisher, Publisher, 'publisher'),
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
        return api_error('A game with this catalog ID already exists.', code='conflict')
    except SQLAlchemyError:
        db.session.rollback()
        log_system_event(
            f"Database error manually identifying game for admin {current_user.name}",
            event_type='error', event_level='error',
        )
        return api_error('The game could not be saved. Please try again.', code='internal')

    try:
        from oneirodex.utils.local_metadata import write_local_metadata
        from oneirodex.utils.global_settings import global_settings_row
        settings = global_settings_row()
        if settings and settings.write_local_metadata:
            write_local_metadata(
                full_disk_path=body.full_disk_path,
                igdb_id=body.igdb_id,
                game_title=body.name,
                manually_verified=True,
                filename=settings.local_metadata_filename or 'oneirodex.json',
            )
    except Exception:
        current_app.logger.exception('Could not write local metadata for manually identified game')

    game_uuid = game.uuid
    from oneirodex.utils.background import run_in_background
    from oneirodex.utils.scanning import refresh_images_in_background
    run_in_background(
        current_app._get_current_object(), refresh_images_in_background, game_uuid,
        name=f'oneirodex-refresh-images-{str(game_uuid)[:8]}',
    )
    log_system_event(
        f"Game '{body.name}' added manually by admin {current_user.name}",
        event_type='game', event_level='information',
    )
    return api_ok({'game_uuid': game_uuid, 'redirect_url': '/admin/unmatched' if request.args.get('from_unmatched') == 'true' else '/libraries'}, status=201)
