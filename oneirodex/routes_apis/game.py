# /oneirodex/routes_apis/game.py -- search, single-game reads, move, freshness.
# The batch routes moved to game_batch.py in the v11 cycle (H-D.4); importing
# this module still registers them.
from datetime import datetime, timezone

from flask import current_app, jsonify, request, url_for
from flask_login import login_required, current_user
from oneirodex import db
from oneirodex.models import (
    Image,
    Game,
    Library,
    Genre,
    GameMode,
    PlayerPerspective,
    Theme,
)
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.game_core import get_game_by_uuid
from oneirodex.utils.game_details_payload import (
    build_game_details_payload,
    local_image_on_disk,
)
from oneirodex.utils.game_more_from import build_more_from
from oneirodex.utils.image_kinds import (
    IMAGE_KIND_ORDER,
    image_kinds_error_message,
    parse_image_kind,
)
from oneirodex.utils.rbac import librarian_required
from oneirodex.utils.library_acl import apply_game_access_filters, user_can_access_game, user_can_access_library
from sqlalchemy import func, select
from . import apis_bp

from . import game_batch  # noqa: F401  -- registers its routes on apis_bp
from oneirodex.utils.rbac import is_admin

def _refuse_inaccessible_game(game):
    """Refusal for a game the caller may not see, or ``None`` when they may.

    Five handlers spelled these four lines out, and they had already drifted:
    `game_details_api` answered 'Access denied' where the other four answered
    'Forbidden', for the identical check. Takes an already-loaded game because
    the call sites disagree on how to load it — one goes through
    `get_game_by_uuid` for its logging, the rest use a plain select.
    """
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('You do not have access to that game', code='forbidden')
    return None


@apis_bp.route('/search')
@login_required
def search():
    query = request.args.get('query', '').strip()
    results = []
    if query:
        # Sanitize input - limit length and escape special characters
        if len(query) > 100:  # Reasonable search term length limit
            return api_error('Search term too long', code='bad_request')

        # Build query with name search
        search_term = f'%{query}%'
        search_query = apply_game_access_filters(
            select(Game).filter(Game.name.ilike(search_term)),
            current_user,
        )

        # Apply active filters from request parameters
        library_uuid = request.args.get('library_uuid')
        genre = request.args.get('genre')
        rating = request.args.get('rating', type=int)
        game_mode = request.args.get('game_mode')
        player_perspective = request.args.get('player_perspective')
        theme = request.args.get('theme')

        # Apply filter logic matching routes_library.py:get_games()
        if library_uuid:
            if not user_can_access_library(current_user, library_uuid):
                return jsonify([])
            search_query = search_query.filter(Game.library_uuid == library_uuid)
        if genre:
            search_query = search_query.filter(Game.genres.any(Genre.name == genre))
        if rating is not None:
            search_query = search_query.filter(Game.rating >= rating)
        if game_mode:
            search_query = search_query.filter(Game.game_modes.any(GameMode.name == game_mode))
        if player_perspective:
            search_query = search_query.filter(Game.player_perspectives.any(PlayerPerspective.name == player_perspective))
        if theme:
            search_query = search_query.filter(Game.themes.any(Theme.name == theme))

        # Execute query and build results
        games = db.session.execute(search_query).scalars().all()
        results = [{'id': game.id, 'uuid': game.uuid, 'name': game.name} for game in games]
    return jsonify(results)


@apis_bp.route('/games/<game_uuid>/details', methods=['GET'])
@login_required
def game_details_api(game_uuid):
    """Full game details JSON for the member SPA details page."""
    game = get_game_by_uuid(game_uuid)
    refusal = _refuse_inaccessible_game(game)
    if refusal is not None:
        return refusal
    return jsonify(build_game_details_payload(game, current_user))


@apis_bp.route('/games/<game_uuid>/more_from', methods=['GET'])
@login_required
def game_more_from_api(game_uuid):
    """Other vault titles from the same developer or publisher."""
    game = get_game_by_uuid(game_uuid)
    refusal = _refuse_inaccessible_game(game)
    if refusal is not None:
        return refusal
    return api_ok(build_more_from(game, current_user))


@apis_bp.route('/games/<game_uuid>/editions', methods=['GET'])
@login_required
def game_editions_api(game_uuid):
    """Every system this title exists on in the library, with per-core launchers.

    The tile grid shows one row per library, so a household holding the same
    game on two systems sees two unrelated tiles and no way to tell they are the
    same game — let alone to choose which one to play. The preview popup asks
    this and renders the answer as a launch menu.

    Read-only, and access-filtered the same way browse is: a member only sees
    copies in libraries they can already see.
    """
    game = db.session.execute(
        select(Game).filter_by(uuid=game_uuid)
    ).scalars().first()
    refusal = _refuse_inaccessible_game(game)
    if refusal:
        return refusal

    from oneirodex.utils.game_editions import editions_preview_payload

    return api_ok(editions_preview_payload(game, current_user))


@apis_bp.route('/game_screenshots/<game_uuid>')
@login_required
def game_screenshots(game_uuid):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    refusal = _refuse_inaccessible_game(game)
    if refusal is not None:
        return refusal
    screenshots = db.session.execute(select(Image).filter_by(game_uuid=game_uuid, image_type='screenshot')).scalars().all()
    # Only rows we can actually serve.
    #
    # This listed every row unconditionally — no `is_downloaded` check and no
    # look at the filesystem — so it happily returned
    # /static/library/images/<name> for art that is not there. That is how the
    # 2026-08-31 rename cutover stayed invisible: 36,481 rows said downloaded
    # while 65 files existed, and this endpoint reported all of them as URLs.
    # `local_image_on_disk` fails open when UPLOAD_FOLDER is unset, so an
    # unconfigured instance still shows art rather than hiding all of it.
    screenshot_urls = [
        url_for('static', filename=f'library/images/{s.url}')
        for s in screenshots
        if getattr(s, 'is_downloaded', False) and s.url and local_image_on_disk(s.url)
    ]
    return jsonify(screenshot_urls)


@apis_bp.route('/game_images/<game_uuid>')
@login_required
def game_images(game_uuid):
    """List persisted images for a game; optional kind/type filter (BE-DET-10)."""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    refusal = _refuse_inaccessible_game(game)
    if refusal is not None:
        return refusal

    raw_kind = request.args.get('kind') or request.args.get('type') or request.args.get('image_type') or 'all'
    try:
        kind_filter = parse_image_kind(raw_kind, default=None, allow_all=True)
    except ValueError:
        return api_error(image_kinds_error_message(), code='bad_request')

    query = select(Image).filter_by(game_uuid=game_uuid)
    if kind_filter != 'all':
        query = query.filter(Image.image_type == kind_filter)
    query = query.order_by(Image.image_type.asc(), Image.created_at.desc())
    rows = db.session.execute(query).scalars().all()

    images = []
    for img in rows:
        local_url = None
        if img.url:
            if img.url.startswith(('http://', 'https://', '/')):
                local_url = img.url
            else:
                local_url = url_for('static', filename=f'library/images/{img.url}')
        images.append({
            'id': img.id,
            'image_type': img.image_type,
            'kind': img.image_type,
            'url': local_url,
            'download_url': img.download_url,
            'is_downloaded': bool(img.is_downloaded),
        })

    return jsonify({
        'game_uuid': game_uuid,
        'kind_filter': kind_filter,
        'allowed_kinds': list(IMAGE_KIND_ORDER),
        'images': images,
        'count': len(images),
    })


@apis_bp.route('/move_game_to_library', methods=['POST'])
@login_required
@librarian_required
def move_game_to_library():
    try:
        data = request.get_json()
        game_uuid = data.get('game_uuid')
        target_library_uuid = data.get('target_library_uuid')
        
        if not game_uuid or not target_library_uuid:
            return api_error('game_uuid and target_library_uuid are required',
                             code='bad_request')
            
        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        target_library = db.session.execute(select(Library).filter_by(uuid=target_library_uuid)).scalars().first()
        
        if not game or not target_library:
            return api_error('Game or target library not found', code='not_found')

        if not user_can_access_game(current_user, game):
            return api_error('You do not have access to that game', code='forbidden')
        if not user_can_access_library(current_user, target_library):
            return api_error('You do not have access to that library', code='forbidden')
            
        # Update the game's library
        game.library_uuid = target_library_uuid
        db.session.commit()
        
        log_system_event(f"Game {game.name} moved to library {target_library.name} by user {current_user.name}", event_type='game', event_level='information')
        
        return api_ok({'message': f'Game moved to {target_library.name}'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning('move_game_to_library failed: %s', e)
        return api_error('Could not move the game', code='internal')

@apis_bp.route('/get_next_custom_igdb_id', methods=['GET'])
@login_required
def get_next_custom_igdb_id():
    """Return the next available custom IGDB ID (above 2000000420)"""
    try:
        # Find the highest custom IGDB ID currently in use
        base_custom_id = 2000000420
        highest_custom_id = db.session.execute(
            select(func.max(Game.igdb_id)).filter(Game.igdb_id >= base_custom_id)
        ).scalar()
        
        # If no custom IDs exist yet, return the base value, otherwise return the next available ID
        next_id = base_custom_id if highest_custom_id is None else highest_custom_id + 1
        return jsonify({'next_id': next_id})
    except Exception as e:
        current_app.logger.warning('next custom IGDB id failed: %s', e)
        return api_error('Could not work out the next custom IGDB id', code='internal')


@apis_bp.route('/games/<game_uuid>/freshness', methods=['GET'])
@login_required
def game_freshness_get(game_uuid):
    """Return cached freshness snapshot for a game."""
    from oneirodex.utils.freshness import freshness_public_view

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    refusal = _refuse_inaccessible_game(game)
    if refusal is not None:
        return refusal
    return jsonify(freshness_public_view(game))


@apis_bp.route('/games/<game_uuid>/freshness/check', methods=['POST'])
@login_required
def game_freshness_check(game_uuid):
    """On-demand local vs store freshness check."""
    from oneirodex.utils.freshness import check_and_store_freshness

    game = db.session.execute(
        select(Game).filter_by(uuid=game_uuid)
    ).scalars().first()
    refusal = _refuse_inaccessible_game(game)
    if refusal is not None:
        return refusal

    try:
        # Eager-load relationships used by local/update hints
        _ = list(game.updates or [])
        _ = list(game.extras or [])
        _ = list(game.urls or [])
        result = check_and_store_freshness(game, commit=True, db_session=db.session)
        log_system_event(
            f"Freshness check for {game.name}: {result.get('status')}",
            event_type='game',
            event_level='information',
        )
        return jsonify(result)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('freshness check failed: %s', exc)
        return api_error('Freshness check failed', code='internal')


@apis_bp.route('/admin/freshness/refresh', methods=['POST'])
@login_required
def admin_freshness_refresh():
    """Bulk refresh freshness for library badges (admin).

    Body JSON:
      limit (int, default 25, max 500) — use a large value for whole-library runs
      only_stale (bool, default true) — skip games checked in the last 24h
      library_uuid (str, optional) — restrict to one library
      entire_library (bool) — when true with a library_uuid, ignore limit cap soft-stop
    """
    from oneirodex.utils.freshness import check_and_store_freshness

    if not current_user.is_authenticated or not is_admin(current_user):
        return api_error('Admin required', code='forbidden')

    data = request.get_json(silent=True) or {}
    entire = bool(data.get('entire_library') or data.get('all'))
    limit_raw = data.get('limit')
    if entire and limit_raw is None:
        limit = 500
    else:
        limit = min(int(limit_raw or 25), 500)
    only_stale = bool(data.get('only_stale', True))
    library_uuid = (data.get('library_uuid') or '').strip() or None

    query = select(Game).order_by(Game.name.asc())
    if library_uuid:
        query = query.filter(Game.library_uuid == library_uuid)
    # Over-fetch when skipping stale so we still fill the batch
    fetch_n = limit * 5 if only_stale else limit
    games = db.session.execute(query.limit(fetch_n)).scalars().all()
    updated = []
    errors = []
    skipped = 0
    now = datetime.now(timezone.utc)
    for game in games:
        if len(updated) >= limit:
            break
        if only_stale and game.freshness_checked_at and game.freshness_status:
            checked = game.freshness_checked_at
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            if (now - checked).total_seconds() < 86400:
                skipped += 1
                continue
        try:
            _ = list(game.updates or [])
            _ = list(game.extras or [])
            _ = list(game.urls or [])
            public = check_and_store_freshness(game, commit=False)
            updated.append({'uuid': game.uuid, 'name': game.name, 'status': public.get('status')})
        except Exception as exc:
            errors.append({'uuid': game.uuid, 'name': game.name, 'error': str(exc)})
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('freshness check failed: %s', exc)
        return api_error('Freshness check failed', code='internal')

    return jsonify({
        'updated': updated,
        'errors': errors,
        'count': len(updated),
        'skipped_fresh': skipped,
        'library_uuid': library_uuid,
        'limit': limit,
    })
