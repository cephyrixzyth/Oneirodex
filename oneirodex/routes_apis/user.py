# /oneirodex/routes_apis/user.py
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.play_status import PLAY_STATUS_VALUES
from oneirodex.utils.avatar import DEFAULT_AVATAR
from flask import jsonify, request, url_for
from flask_login import login_required, current_user
from oneirodex import db
from oneirodex.models import (
    Game,
    GlobalSettings,
    Image,
    User,
    UserGameProgress,
    user_favorites,
    user_game_status,
    get_status_info,
)
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.browse_filters import apply_item_kind_filter, apply_name_filter
from oneirodex.utils.client_lifecycle import load_lifecycle_map
from oneirodex.utils.local_metadata import has_local_images, has_local_metadata
from oneirodex.utils.lifecycle import web_lifecycle_fields
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.game_details_payload import browse_trailer_fields
from oneirodex.utils.play_url import browse_play_fields, library_platform_key
from oneirodex.utils.secondary_scrapers import game_card_flags
from oneirodex.utils.cover_url import resolve_game_cover_url
from oneirodex.utils.library_acl import apply_game_access_filters, user_can_access_game
from oneirodex.schemas.user import CheckUsernameBody
from oneirodex.utils.icon_themes import icon_pack_css_url, list_icon_packs
from oneirodex.utils.presence import accepted_friend_ids, presence_for_user
from oneirodex.utils.validation import validate_body
from sqlalchemy import func, select, and_, delete
from sqlalchemy.orm import joinedload
from datetime import datetime, timezone
from . import apis_bp


@apis_bp.route('/users/<int:user_id>/profile', methods=['GET'])
@login_required
def member_profile(user_id: int):
    """Public member profile — ACL-filtered recent games (Wave 14b)."""
    target = db.session.get(User, user_id)
    if not target or not target.state:
        return api_error('Not found', code='not_found')
    friends = accepted_friend_ids(current_user.id)
    is_self = target.id == current_user.id
    is_friend = target.id in friends
    presence = presence_for_user(target.id, viewer=current_user)
    progress_rows = (
        db.session.execute(
            select(UserGameProgress)
            .where(UserGameProgress.user_id == target.id)
            .order_by(UserGameProgress.last_played_at.desc().nullslast())
            .limit(40)
        )
        .scalars()
        .all()
    )
    recent = []
    total_seconds = 0
    for row in progress_rows:
        total_seconds += int(row.total_seconds or 0)
        game = db.session.execute(select(Game).filter_by(uuid=row.game_uuid)).scalars().first()
        if not game or not user_can_access_game(current_user, game):
            continue
        recent.append({
            'game_uuid': row.game_uuid,
            'game_name': game.name,
            'total_seconds': int(row.total_seconds or 0),
            'last_played_at': row.last_played_at.isoformat() if row.last_played_at else None,
        })
        if len(recent) >= 12:
            break
    avatar = getattr(target, 'avatarpath', None) or DEFAULT_AVATAR
    return jsonify({
        'user': {
            'id': target.id,
            'name': target.name,
            'about': getattr(target, 'about', None),
            'avatar_url': url_for('static', filename=avatar) if avatar else None,
        },
        'presence': presence,
        'is_self': is_self,
        'is_friend': is_friend,
        'total_seconds': total_seconds,
        'recent_games': recent,
    })


@apis_bp.route('/users/<int:user_id>/compare/<int:other_id>', methods=['GET'])
@login_required
def member_profile_compare(user_id: int, other_id: int):
    """Compare playtime with a friend (Wave 14b)."""
    if current_user.id not in {user_id, other_id}:
        return api_error('Forbidden', code='forbidden')
    friends = accepted_friend_ids(current_user.id)
    peers = {user_id, other_id}
    if current_user.id not in peers:
        return api_error('Forbidden', code='forbidden')
    other = other_id if current_user.id == user_id else user_id
    if other != current_user.id and other not in friends:
        return api_error('Friends only', code='forbidden')
    left = db.session.get(User, user_id)
    right = db.session.get(User, other_id)
    if not left or not right:
        return api_error('Not found', code='not_found')
    left_rows = {
        r.game_uuid: r
        for r in db.session.execute(
            select(UserGameProgress).where(UserGameProgress.user_id == user_id)
        ).scalars().all()
    }
    right_rows = {
        r.game_uuid: r
        for r in db.session.execute(
            select(UserGameProgress).where(UserGameProgress.user_id == other_id)
        ).scalars().all()
    }
    shared = []
    for guuid in set(left_rows) & set(right_rows):
        game = db.session.execute(select(Game).filter_by(uuid=guuid)).scalars().first()
        if not game or not user_can_access_game(current_user, game):
            continue
        shared.append({
            'game_uuid': guuid,
            'game_name': game.name,
            'left_seconds': int(left_rows[guuid].total_seconds or 0),
            'right_seconds': int(right_rows[guuid].total_seconds or 0),
        })
    shared.sort(key=lambda r: r['left_seconds'] + r['right_seconds'], reverse=True)
    return jsonify({
        'left': {'id': left.id, 'name': left.name},
        'right': {'id': right.id, 'name': right.name},
        'shared_games': shared[:40],
    })


@apis_bp.route('/current_user_role', methods=['GET'])
@login_required
def get_current_user_role():
    return jsonify({'role': current_user.role}), 200


@apis_bp.route('/icon-packs', methods=['GET'])
@login_required
def list_icon_packs_api():
    current = 'outline'
    if getattr(current_user, 'preferences', None):
        current = getattr(current_user.preferences, 'icon_pack', None) or 'outline'
    packs = list_icon_packs()
    for pack in packs:
        pack['css_url'] = icon_pack_css_url(pack['id'])
    return jsonify({'packs': packs, 'current': current})


@apis_bp.route('/check_username', methods=['POST'])
@login_required
@validate_body(CheckUsernameBody)
def check_username(body: CheckUsernameBody):
    print(F"Route: /api/check_username - {current_user.name} - {current_user.role}")    
    username = body.username
    print(f"Checking username: {username}")
    existing_user = db.session.execute(select(User).filter(func.lower(User.name) == func.lower(username))).scalars().first()
    return jsonify({"exists": existing_user is not None})

@apis_bp.route('/check_favorite/<game_uuid>')
@login_required
def check_favorite(game_uuid):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    is_favorite = game in current_user.favorites
    return jsonify({'is_favorite': is_favorite})

@apis_bp.route('/toggle_favorite/<game_uuid>', methods=['POST'])
@login_required
def toggle_favorite(game_uuid):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    
    if game in current_user.favorites:
        current_user.favorites.remove(game)
        is_favorite = False
    else:
        current_user.favorites.append(game)
        is_favorite = True
    
    db.session.commit()
    return api_ok({'is_favorite': is_favorite})


@apis_bp.route('/favorites', methods=['GET'])
@login_required
def favorites():
    page = request.args.get('page', 1, type=int) or 1
    per_page = min(request.args.get('per_page', 20, type=int) or 20, 100)

    query = (
        apply_game_access_filters(
            select(Game)
            .join(user_favorites, user_favorites.c.game_uuid == Game.uuid)
            .where(user_favorites.c.user_id == current_user.id)
            .options(joinedload(Game.genres), joinedload(Game.library))
            .order_by(Game.name.asc()),
            current_user,
        )
    )
    query = apply_name_filter(query, request.args)
    query = apply_item_kind_filter(query, request.args)
    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    games = pagination.items
    game_uuids = [game.uuid for game in games]

    user_statuses = {}
    covers_by_uuid: dict[str, Image] = {}
    if game_uuids:
        status_results = db.session.execute(
            select(user_game_status.c.game_uuid, user_game_status.c.status).where(
                and_(
                    user_game_status.c.user_id == current_user.id,
                    user_game_status.c.game_uuid.in_(game_uuids),
                )
            )
        ).all()
        user_statuses = {row[0]: row[1] for row in status_results}
        cover_rows = db.session.execute(
            select(Image).where(
                Image.game_uuid.in_(game_uuids),
                Image.image_type == 'cover',
            )
        ).scalars().all()
        covers_by_uuid = {row.game_uuid: row for row in cover_rows}

    settings = global_settings_row()
    lifecycle_map = load_lifecycle_map(current_user.id)
    game_data = []
    for game in games:
        cover_image = covers_by_uuid.get(game.uuid)
        cover_url = resolve_game_cover_url(game, cover_image)

        has_local_override = False
        if settings:
            has_local_override = (
                settings.use_local_metadata
                and has_local_metadata(
                    game.full_disk_path,
                    settings.local_metadata_filename or 'oneirodex.json',
                )
            ) or (
                settings.use_local_images
                and has_local_images(game.full_disk_path)
            )

        platform_key = library_platform_key(game)
        platform_label = None
        library = getattr(game, 'library', None)
        platform = getattr(library, 'platform', None) if library is not None else None
        if platform is not None:
            platform_label = getattr(platform, 'value', None) or platform_key

        game_data.append({
            'uuid': game.uuid,
            'name': game.name,
            'cover_url': cover_url,
            'is_favorite': True,
            'has_local_override': has_local_override,
            'library_platform': platform_key,
            'library_platform_label': platform_label,
            'badge_title_collision': bool(platform_key),
            'freshness_status': getattr(game, 'freshness_status', None),
            **browse_play_fields(game),
            **browse_trailer_fields(game),
            **game_card_flags(game),
            **web_lifecycle_fields(
                game,
                user_id=current_user.id,
                client_state=lifecycle_map.get(game.uuid),
            ),
            'genres': [genre.name for genre in game.genres],
            'user_status': user_statuses.get(game.uuid),
        })

    return jsonify({
        'games': game_data,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
    })


@apis_bp.route('/get_game_status/<game_uuid>', methods=['GET'])
@login_required
def get_game_status(game_uuid):
    """Get the current user's completion status for a game"""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    # The library ACL too: a restricted (e.g. child) account must not learn
    # that a game exists, or record a status for it, outside its libraries.
    if not game or not user_can_access_game(current_user, game):
        return api_error('Game not found', code='not_found')

    # Query the status
    status_row = db.session.execute(
        select(user_game_status.c.status).where(
            and_(
                user_game_status.c.user_id == current_user.id,
                user_game_status.c.game_uuid == game_uuid
            )
        )
    ).first()

    status = status_row[0] if status_row else None
    status_info = get_status_info(status)

    return api_ok({
                'status': status,
        'status_info': status_info
    })

@apis_bp.route('/set_game_status/<game_uuid>', methods=['POST'])
@login_required
def set_game_status(game_uuid):
    """Set or update the user's completion status for a game"""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    # The library ACL too: a restricted (e.g. child) account must not learn
    # that a game exists, or record a status for it, outside its libraries.
    if not game or not user_can_access_game(current_user, game):
        return api_error('Game not found', code='not_found')

    data = request.get_json()
    status = data.get('status', '').strip()

    # Validate status
    valid_statuses = sorted(PLAY_STATUS_VALUES)
    if status not in valid_statuses:
        return api_error('Invalid status value', code='bad_request')

    # If status is empty, remove the status record
    if not status:
        db.session.execute(
            delete(user_game_status).where(
                and_(
                    user_game_status.c.user_id == current_user.id,
                    user_game_status.c.game_uuid == game_uuid
                )
            )
        )
        db.session.commit()
        return api_ok({
                        'status': None,
            'status_info': get_status_info(None),
            'message': 'Status cleared'
        })

    # Check if status already exists
    existing = db.session.execute(
        select(user_game_status).where(
            and_(
                user_game_status.c.user_id == current_user.id,
                user_game_status.c.game_uuid == game_uuid
            )
        )
    ).first()

    if existing:
        # Update existing status
        db.session.execute(
            user_game_status.update().where(
                and_(
                    user_game_status.c.user_id == current_user.id,
                    user_game_status.c.game_uuid == game_uuid
                )
            ).values(
                status=status,
                updated_at=datetime.now(timezone.utc)
            )
        )
    else:
        # Insert new status
        db.session.execute(
            user_game_status.insert().values(
                user_id=current_user.id,
                game_uuid=game_uuid,
                status=status,
                updated_at=datetime.now(timezone.utc)
            )
        )

    db.session.commit()
    status_info = get_status_info(status)

    return api_ok({
                'status': status,
        'status_info': status_info,
        'message': f'Status updated to {status_info["label"]}'
    })
