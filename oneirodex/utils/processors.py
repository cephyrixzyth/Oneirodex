from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.models import GlobalSettings
from sqlalchemy import select
from oneirodex import app_version
import json

def get_loc(page):
    
    with open(f'oneirodex/static/localization/en/{page}.json', 'r', encoding='utf8') as f:
            loc_data = json.load(f)    
    return loc_data

def get_global_settings():
    """Helper function to get global settings with defaults"""
    settings_record = global_settings_row()
    default_settings = {
        'showSystemLogo': True,
        'showHelpButton': True,
        'allowUsersToInviteOthers': False,
        'enableGameUpdates': True,
        'updateFolderName': 'updates',
        'enableGameExtras': True,
        'extrasFolderName': 'extras',
        'siteUrl': 'http://127.0.0.1',
        'showSystemLogo': True,
        'showHelpButton': True,
        'enableWebLinksOnDetailsPage': True,
        'enableServerStatusFeature': True,
        'enableNewsletterFeature': True,
        'showVersion': True,
        'enableDeleteGameOnDisk': True,
        'enableGameUpdates': True,
        'enableGameExtras': True,
        'siteUrl': 'http://127.0.0.1'
    }
    
    settings = default_settings.copy()
    
    if settings_record and settings_record.settings:
        settings.update(settings_record.settings)
        return {
            'show_logo': settings.get('showSystemLogo'),
            # Explicit True defaults: a missing JSON key must not hide Help /
            # Trailers (dataset.showX === 'true' is false when the attr is absent).
            'show_help_button': settings.get('showHelpButton', True),
            'enable_web_links': settings.get('enableWebLinksOnDetailsPage'),
            'enable_server_status': settings_record.settings.get('enableServerStatusFeature', False),
            'enable_newsletter': settings_record.settings.get('enableNewsletterFeature', False),
            'show_version': settings_record.settings.get('showVersion', False),
            'show_discovery': settings.get('showDiscovery', True),
            'show_favorites': settings.get('showFavorites', True),
            'show_trailers': settings.get('showTrailers', True),
            'show_play_status': settings.get('showPlayStatus', True),
            'enable_delete_game_on_disk': settings_record.settings.get('enableDeleteGameOnDisk', True),
            'enable_game_updates': settings_record.settings.get('enableGameUpdates', True),
            'enable_game_extras': settings_record.settings.get('enableGameExtras', True),
            'app_version': app_version
        }
    
    # Return default values if no settings_record is found
    return {
        'show_logo': True,
        'show_help_button': True,
        'enable_web_links': True,
        'enable_server_status': True,
        'enable_newsletter': True,
        'show_version': True,
        'show_discovery': True,
        'show_favorites': True,
        'show_trailers': True,
        'show_play_status': True,
        'enable_delete_game_on_disk': True,
        'enable_game_updates': True,
        'enable_game_extras': True,
        'app_version': app_version
    }