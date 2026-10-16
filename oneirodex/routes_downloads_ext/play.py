import os
import uuid
from flask import redirect, url_for, flash, current_app
from flask_login import login_required
from oneirodex.utils.member_spa import render_member_spa, current_user
from oneirodex import db
from oneirodex.models import Game
from sqlalchemy import select
from oneirodex.utils.api_response import api_error
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.play_url import browse_play_fields
from oneirodex.utils.security import is_safe_path, get_allowed_base_directories
from . import download_bp

@download_bp.route('/play_game/<game_uuid>', methods=['GET'])
@login_required
def play_game(game_uuid):
    """Redirect to WebRetro when the title is browser-playable; else game details."""
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        flash('Game not found.', 'error')
        return redirect(url_for('library.library'))
    if not user_can_access_game(current_user, game):
        flash('You do not have access to this game.', 'error')
        return redirect(url_for('library.library'))
    fields = browse_play_fields(game)
    play_url = fields.get('play_url')
    if fields.get('can_play_in_browser') and play_url:
        return redirect(play_url)
    flash('This title is not playable in the browser. Open details for download/install.', 'info')
    return redirect(url_for('games.game_details', game_uuid=game_uuid))

@download_bp.route('/playromtest', methods=['GET'])
@login_required
def playromtest():
    """Legacy test route — prefer /play_game/<uuid> → WebRetro."""
    flash("Use Play from a game details page for browser emulation.", "info")
    return render_member_spa()

# NOTE: This API route is now handled by ASGI for async streaming  
# This Flask route should not be reached as ASGI intercepts it first
@download_bp.route('/api/downloadrom/<string:guid>', methods=['GET'])
@login_required
def downloadrom(guid):
    """
    ROM download route - now handled by ASGI for async streaming.
    This Flask route should not be reached.
    """
    # This route should not be reached as ASGI intercepts download routes
    log_system_event(f"Flask ROM download route reached unexpectedly for UUID: {guid}", 
                    event_type='system', event_level='warning')
    return api_error('ROM download route should be handled by ASGI', code='internal')
