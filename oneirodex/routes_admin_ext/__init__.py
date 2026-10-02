from flask import Blueprint
from oneirodex import cache
from oneirodex.utils.processors import get_global_settings

admin2_bp = Blueprint('admin2', __name__)

@admin2_bp.context_processor
@cache.cached(timeout=500, key_prefix='global_settings')
def inject_settings():
    """Context processor to inject global settings into templates"""
    return get_global_settings()

# Import routes to register them with the blueprint
from . import themes, libraries, system, invites, filters, extensions, help, users, whitelist, newsletter, settings, igdb, images, attract_mode, hltb, library_tools, announcements, chat_emoji, reference_sets, features, art_studio, remote_play, scan_jobs, scan_management, game_images, game_delete, library_delete, unmatched_folders, ownership
