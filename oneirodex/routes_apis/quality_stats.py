"""Quality profile + playtime share-card APIs."""

from __future__ import annotations

from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.api_tokens import require_api_token_scope
from flask import Response, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, UserGameProgress
from oneirodex.utils.auth import admin_required
from oneirodex.utils.quality_profiles import (
    create_quality_profile,
    delete_quality_profile,
    get_quality_profile,
    list_quality_profiles,
    save_quality_profile,
    score_release_title,
    set_active_quality_profile,
    update_quality_profile,
)
from oneirodex.utils.stats_share import build_playtime_share_svg
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.schemas.quality_stats import ScoreReleaseBody, SetActiveQualityProfileBody
from oneirodex.utils.validation import validate_body

from . import apis_bp


@apis_bp.route('/quality-profiles', methods=['GET'])
@login_required
@admin_required
def quality_profiles_get():
    """List profiles + flattened active fields (legacy admin form compatible)."""
    return jsonify(list_quality_profiles())


@apis_bp.route('/quality-profiles', methods=['POST'])
@login_required
@admin_required
def quality_profiles_create():
    data = request.get_json(silent=True) or {}
    try:
        created = create_quality_profile(data)
    except (TypeError, ValueError) as exc:
        return api_error(str(exc), code='bad_request')
    return jsonify(created), 201


@apis_bp.route('/quality-profiles', methods=['PUT'])
@login_required
@admin_required
def quality_profiles_put():
    """Update the active profile (legacy single-object PUT)."""
    data = request.get_json(silent=True) or {}
    try:
        saved = save_quality_profile(data)
    except KeyError as exc:
        return api_error(str(exc), code='not_found')
    except (TypeError, ValueError) as exc:
        return api_error(str(exc), code='bad_request')
    return jsonify(saved)


@apis_bp.route('/quality-profiles/active', methods=['PUT', 'POST'])
@login_required
@admin_required
@validate_body(SetActiveQualityProfileBody)
def quality_profiles_set_active(body: SetActiveQualityProfileBody):
    profile_id = (body.id or body.active_id or body.profile_id or '').strip()
    try:
        saved = set_active_quality_profile(profile_id)
    except KeyError as exc:
        return api_error(str(exc), code='not_found')
    return jsonify(saved)


@apis_bp.route('/quality-profiles/<profile_id>', methods=['GET'])
@login_required
@admin_required
def quality_profiles_get_one(profile_id: str):
    profile = get_quality_profile(profile_id)
    if profile.get('id') != profile_id:
        return api_error(f'profile not found: {profile_id}', code='not_found')
    return jsonify(profile)


@apis_bp.route('/quality-profiles/<profile_id>', methods=['PUT', 'PATCH'])
@login_required
@admin_required
def quality_profiles_update_one(profile_id: str):
    data = request.get_json(silent=True) or {}
    try:
        saved = update_quality_profile(profile_id, data)
    except KeyError as exc:
        return api_error(str(exc), code='not_found')
    except (TypeError, ValueError) as exc:
        return api_error(str(exc), code='bad_request')
    return jsonify(saved)


@apis_bp.route('/quality-profiles/<profile_id>', methods=['DELETE'])
@login_required
@admin_required
def quality_profiles_delete_one(profile_id: str):
    try:
        saved = delete_quality_profile(profile_id)
    except KeyError as exc:
        return api_error(str(exc), code='not_found')
    return jsonify(saved)


@apis_bp.route('/quality-profiles/score', methods=['POST'])
@login_required
@admin_required
@validate_body(ScoreReleaseBody)
def quality_profiles_score(body: ScoreReleaseBody):
    title = body.title
    size = body.size_bytes
    try:
        size_bytes = int(size) if size is not None else None
    except (TypeError, ValueError):
        size_bytes = None
    profile_id = (body.profile_id or body.id or '').strip() or None
    return jsonify(score_release_title(title, size_bytes=size_bytes, profile_id=profile_id))


@apis_bp.route('/playtime/share/<game_uuid>.svg', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def playtime_share_card(game_uuid: str):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    row = db.session.execute(
        select(UserGameProgress).filter_by(user_id=current_user.id, game_uuid=game_uuid),
    ).scalars().first()
    total = int(row.total_seconds) if row else 0
    sessions = int(row.session_count) if row else 0
    svg = build_playtime_share_svg(
        username=current_user.name,
        game_name=game.name,
        total_seconds=total,
        session_count=sessions,
    )
    return Response(svg, mimetype='image/svg+xml')
