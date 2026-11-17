from flask import Blueprint

apis_bp = Blueprint('apis', __name__, url_prefix='/api')

# Import routes to register them with the blueprint
from . import account, admin_search, admin_themes, ai_assist, browse, calendar, chat, chat_spaces_api, client, collections, discover, download, emulator_cheats, events, filters, game, game_mods_api, game_servers, health, igdb, imports_playnite, integrations, layouts, library, library_tools, licensed_catalog, metadata_search, notifications, oidc_status, ownership, ownership_admin, patch_catalog, playtime, preferences, providers, quality_stats, reference_sets, related_media, retroachievements, rtc, saved_filters, scan, settings, setup, storage, support, system, tokens, updates, user, vr, wishlist, wanted, acquire, assists, wave8_11, social, malware_scan
