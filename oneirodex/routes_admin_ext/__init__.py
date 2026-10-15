from flask import Blueprint

admin2_bp = Blueprint('admin2', __name__)

# Import routes to register them with the blueprint
from . import themes, libraries, system, invites, filters, extensions, help, users, whitelist, newsletter, settings, igdb, images, attract_mode, hltb, library_tools, announcements, chat_emoji, reference_sets, features, art_studio, remote_play, scan_jobs, scan_management, game_images, game_delete, library_delete, unmatched_folders, ownership
