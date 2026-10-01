from flask import Blueprint
from oneirodex import cache
from oneirodex.utils.processors import get_global_settings

apis_bp = Blueprint('apis', __name__, url_prefix='/api')

@apis_bp.context_processor
@cache.cached(timeout=500, key_prefix='global_settings')
def inject_settings():
    """Context processor to inject global settings into templates"""
    return get_global_settings()

# Import routes to register them with the blueprint
from . import arcade, account, admin_search, ai_assist, ambient_lighting, browse, calendar, chat, chat_spaces_api, client, collections, discover, download, emulator_cheats, emulator_saves, events, filters, game, game_mods_api, game_servers, health, igdb, imports_playnite, integrations, layouts, library, library_tools, licensed_catalog, locale, loading_icons, metadata_providers, metadata_search, notifications, oidc_status, ownership, ownership_admin, palette, patch_catalog, playtime, providers, quality_stats, reference_sets, related_media, retroachievements, rtc, rom_translate, saved_filters, scan, scan_match, settings, storage, support, system, tokens, updates, user, vr, wishlist, wanted, acquire, assists, wave8_11, social, malware_scan, challenge_solver, remote_play
