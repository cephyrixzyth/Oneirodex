"""Admin-only search endpoints for the Identify / Find-and-Link workflow."""

from flask import jsonify, request
from flask_login import login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.utils.api_response import api_error
from oneirodex.utils.admin_search import GAMES_SEARCH_RESULT_LIMIT
from oneirodex.utils.auth import admin_required

from . import apis_bp

@apis_bp.route('/admin/games_search', methods=['GET'])
@login_required
@admin_required
def admin_games_search():
    """Search existing library games by name for the 'link existing game' flow.

    Unlike the public /api/search endpoint, this is admin-only and returns
    full_disk_path, which regular users should not be able to see.
    """
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    if len(query) > 100:
        return api_error('Search term too long', code='bad_request')

    search_term = f'%{query}%'
    games = db.session.execute(
        select(Game)
        .filter(Game.name.ilike(search_term))
        .order_by(Game.name)
        .limit(GAMES_SEARCH_RESULT_LIMIT)
    ).scalars().all()

    results = [
        {
            'uuid': game.uuid,
            'name': game.name,
            'full_disk_path': game.full_disk_path,
        }
        for game in games
    ]
    return jsonify(results)
