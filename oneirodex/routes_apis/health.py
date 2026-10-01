"""Library health API."""

from flask import jsonify, request
from flask_login import login_required, current_user
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.utils.library_health import score_game, summarize_library_health
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.api_response import api_error

from . import apis_bp
from oneirodex.utils.rbac import is_admin


@apis_bp.route('/health/library', methods=['GET'])
@login_required
def library_health_summary():
    if not is_admin(current_user):
        return api_error('Admin required', code='forbidden')
    try:
        limit = min(int(request.args.get('limit') or 200), 2000)
    except (TypeError, ValueError):
        limit = 200
    library_uuid = (request.args.get('library_uuid') or '').strip() or None
    return jsonify(summarize_library_health(limit=limit, library_uuid=library_uuid))


@apis_bp.route('/health/games/<game_uuid>', methods=['GET'])
@login_required
def game_health_detail(game_uuid: str):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    return jsonify(score_game(game))
