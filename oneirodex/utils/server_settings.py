"""Framework-independent validation and public projection for server settings."""
from __future__ import annotations

import math
from pathlib import PureWindowsPath
from urllib.parse import urlsplit


FIELD_MAPPINGS = {
    'enableDeleteGameOnDisk': 'enable_delete_game_on_disk',
    'enableGameUpdates': 'enable_game_updates',
    'updateFolderName': 'update_folder_name',
    'enableGameExtras': 'enable_game_extras',
    'extrasFolderName': 'extras_folder_name',
    'siteUrl': 'site_url',
    'useTurboImageDownloads': 'use_turbo_image_downloads',
    'turboDownloadThreads': 'turbo_download_threads',
    'turboDownloadBatchSize': 'turbo_download_batch_size',
    'scanThreadCount': 'scan_thread_count',
    'enableHltbIntegration': 'enable_hltb_integration',
    'hltbRateLimitDelay': 'hltb_rate_limit_delay',
    'useLocalMetadata': 'use_local_metadata',
    'writeLocalMetadata': 'write_local_metadata',
    'useLocalImages': 'use_local_images',
    'localMetadataFilename': 'local_metadata_filename',
    'proposeOnlyScan': 'propose_only_scan',
}

MIN_SCAN_THREADS = 1
MAX_SCAN_THREADS = 4
MIN_DOWNLOAD_THREADS = 1
MAX_DOWNLOAD_THREADS = 20
MIN_BATCH_SIZE = 10
MAX_BATCH_SIZE = 1000

SERVER_BOOLEAN_FIELDS = (
    'showSystemLogo', 'showHelpButton', 'allowUsersToInviteOthers',
    'enableWebLinksOnDetailsPage', 'enableServerStatusFeature', 'enableNewsletterFeature',
    'showVersion', 'showDiscovery', 'showFavorites', 'showTrailers', 'showPlayStatus',
    'enableDeleteGameOnDisk', 'enableGameUpdates', 'enableGameExtras',
    'useTurboImageDownloads', 'enableHltbIntegration', 'useLocalMetadata',
    'writeLocalMetadata', 'useLocalImages', 'proposeOnlyScan',
)
SERVER_NUMBER_BOUNDS = {
    'scanThreadCount': {'min': MIN_SCAN_THREADS, 'max': MAX_SCAN_THREADS, 'step': 1},
    'turboDownloadThreads': {'min': MIN_DOWNLOAD_THREADS, 'max': MAX_DOWNLOAD_THREADS, 'step': 1},
    'turboDownloadBatchSize': {'min': MIN_BATCH_SIZE, 'max': MAX_BATCH_SIZE, 'step': 1},
    'hltbRateLimitDelay': {'min': 0.5, 'max': 10.0, 'step': 'any'},
}
SERVER_TEXT_LIMITS = {
    'siteUrl': 255, 'updateFolderName': 100,
    'extrasFolderName': 100, 'localMetadataFilename': 50,
}
SERVER_FIELDS = frozenset(SERVER_BOOLEAN_FIELDS) | SERVER_NUMBER_BOUNDS.keys() | SERVER_TEXT_LIMITS.keys()

SERVER_DEFAULTS = {
    'showSystemLogo': True,
    'showHelpButton': True,
    'allowUsersToInviteOthers': False,
    'enableWebLinksOnDetailsPage': True,
    'enableServerStatusFeature': True,
    'enableNewsletterFeature': True,
    'showVersion': True,
    'showDiscovery': True,
    'showFavorites': True,
    'showTrailers': True,
    'showPlayStatus': True,
    'enableDeleteGameOnDisk': True,
    'enableGameUpdates': True,
    'enableGameExtras': True,
    'useTurboImageDownloads': True,
    'enableHltbIntegration': True,
    'useLocalMetadata': True,
    'writeLocalMetadata': True,
    'useLocalImages': True,
    'proposeOnlyScan': False,
    'scanThreadCount': MIN_SCAN_THREADS,
    'turboDownloadThreads': 4,
    'turboDownloadBatchSize': 100,
    'hltbRateLimitDelay': 2.0,
    'siteUrl': 'http://127.0.0.1',
    'updateFolderName': 'updates',
    'extrasFolderName': 'extras',
    'localMetadataFilename': 'oneirodex.json',
}


def public_server_settings(record, *, current=None):
    if current is None:
        current = dict(SERVER_DEFAULTS)
        if getattr(record, 'settings', None):
            current.update(record.settings)
        for json_field, db_field in FIELD_MAPPINGS.items():
            db_value = getattr(record, db_field, None)
            if db_value is not None:
                current[json_field] = db_value
    state = {key: current.get(key, False) for key in sorted(SERVER_FIELDS)}
    try:
        url = urlsplit(state['siteUrl'])
        if url.username or url.password:
            state['siteUrl'] = url._replace(netloc=url.netloc.rsplit('@', 1)[-1]).geturl()
    except (ValueError, TypeError):
        state['siteUrl'] = SERVER_DEFAULTS['siteUrl']
    return state


def validate_server_settings(data):
    if not isinstance(data, dict) or not data or set(data) - SERVER_FIELDS:
        raise ValueError('Provide only the server settings you want to change')
    result = dict(data)
    for key, value in data.items():
        if key in SERVER_BOOLEAN_FIELDS:
            if type(value) is not bool:
                raise ValueError('Feature and interface preferences must be booleans')
        elif key in SERVER_NUMBER_BOUNDS:
            bounds = SERVER_NUMBER_BOUNDS[key]
            allowed = (int, float) if key == 'hltbRateLimitDelay' else (int,)
            if type(value) not in allowed or not bounds['min'] <= value <= bounds['max'] or not math.isfinite(value):
                raise ValueError('Numeric settings must be within their displayed bounds')
        else:
            if not isinstance(value, str) or not value.strip() or len(value) > SERVER_TEXT_LIMITS[key] or any(ord(c) < 32 for c in value):
                raise ValueError('Text settings must be nonempty and within their displayed length limits')
            result[key] = value.strip()
            if key == 'siteUrl':
                try:
                    url = urlsplit(value.strip())
                    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
                        raise ValueError
                    url.port
                except ValueError:
                    raise ValueError('Site URL must be an HTTP or HTTPS URL without embedded credentials') from None
            elif key in ('updateFolderName', 'extrasFolderName'):
                normalized = value.strip().replace('\\', '/')
                if normalized.startswith('/') or PureWindowsPath(value.strip()).drive or any(part in ('.', '..') for part in normalized.split('/')):
                    raise ValueError('Update and extras folders must be relative paths without parent traversal')
            elif key == 'localMetadataFilename':
                if '/' in value or '\\' in value:
                    raise ValueError('Metadata filename must not contain path separators')
                if not value.strip().endswith('.json'):
                    raise ValueError('Metadata filename must end with .json')
    return result
