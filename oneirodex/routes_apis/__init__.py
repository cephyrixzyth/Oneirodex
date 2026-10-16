from flask import Blueprint

apis_bp = Blueprint('apis', __name__, url_prefix='/api')

# Import routes to register them with the blueprint
from . import arcade, account, admin_search, admin_statistics, admin_themes, ai_assist, ambient_lighting, browse, calendar, chat, chat_spaces_api, client, collections, discover, download, emulator_cheats, emulator_saves, events, filters, game, game_mods_api, game_servers, health, igdb, imports_playnite, integrations, layouts, library, library_tools, licensed_catalog, locale, loading_icons, manual_identify, metadata_providers, metadata_search, notifications, oidc_status, ownership, ownership_admin, palette, patch_catalog, playtime, preferences, providers, quality_stats, reference_sets, related_media, retroachievements, rtc, rom_translate, saved_filters, scan, scan_match, settings, setup, storage, support, system, tokens, updates, user, vr, wishlist, wanted, acquire, assists, wave8_11, social, malware_scan, challenge_solver, remote_play
