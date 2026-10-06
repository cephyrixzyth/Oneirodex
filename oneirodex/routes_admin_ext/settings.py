# /oneirodex/routes_admin_ext/settings.py
import json
import logging
import os
from datetime import datetime, timezone

from oneirodex.utils.api_response import api_error, api_ok
from flask import render_template, request, jsonify, abort, current_app, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import select

from oneirodex import db, cache
from oneirodex.utils.auth import admin_required
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.oidc import is_secure_oidc_issuer
from oneirodex.utils.igdb_api import make_igdb_api_request
from oneirodex.utils.providers import get_steamgriddb_api_key, mask_api_key
from . import admin2_bp

# Configuration constants
MIN_SCAN_THREADS = 1
MAX_SCAN_THREADS = 4
MIN_DOWNLOAD_THREADS = 1
MAX_DOWNLOAD_THREADS = 20
MIN_BATCH_SIZE = 10
MAX_BATCH_SIZE = 1000
# Unraid-safe defaults; runtime hard-capped further via worker_caps (≤4 / ≤100)
DEFAULT_BATCH_SIZE = 100
DEFAULT_DOWNLOAD_THREADS = 4

# Default settings configuration
DEFAULT_SETTINGS = {
    'showSystemLogo': True,
    'showHelpButton': True,
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
    'siteUrl': 'http://127.0.0.1',
    'updateFolderName': 'updates',
    'extrasFolderName': 'extras',
    'useTurboImageDownloads': True,
    'turboDownloadThreads': DEFAULT_DOWNLOAD_THREADS,
    'turboDownloadBatchSize': DEFAULT_BATCH_SIZE,
    'scanThreadCount': 1,
    'enableHltbIntegration': True,
    'hltbRateLimitDelay': 2.0,
    'useLocalMetadata': True,
    'writeLocalMetadata': True,
    'useLocalImages': True,
    'localMetadataFilename': 'oneirodex.json',
    'proposeOnlyScan': False,
    # W20-4 Scan / match policy (also GET|PUT /api/admin/scan-match/config)
    'matchHighThreshold': 0.92,
    'matchAmbiguousGap': 0.08,
    'dupeTitleThreshold': 0.85,
    'peelProfile': 'conservative',
    'enableYearDropVariant': True,
    'enablePackPeelVariant': True,
    'enableEditionPeelVariant': True,
    'enableSequelNumeralVariant': True,
}

# Settings hub sections rendered as one-click cards on /admin/settings.
# 'icon' is a semantic key for the Jinja SVG macro in templates/partials/icons.html,
# not a Font Awesome class.
SETTINGS_SHELL_SECTIONS = {
    'server': {
        'label': 'Server Settings',
        'icon': 'cogs',
        'description': 'Scan threads, download batching, folder names, and site metadata.',
        'endpoint': 'admin2.new_server_settings',
    },
    'scan_match': {
        'label': 'Scan / match policy',
        'icon': 'clipboard-list',
        'description': 'Propose-only default, dupe/match thresholds, and peel profile.',
        'endpoint': 'admin2.scan_match_settings_page',
    },
    'attract': {
        'label': 'Attract Mode',
        'icon': 'tv',
        'description': 'Configure the idle-screen trailer slideshow and its filters.',
        'endpoint': 'admin2.attract_mode_settings_page',
    },
    'integrations': {
        'label': 'Integrations',
        'icon': 'plug',
        'description': 'Email (SMTP), IGDB API credentials, community chat, and artwork providers.',
        'endpoint': 'admin2.integrations',
    },
    'emulators': {
        'label': 'Emulator profiles',
        'icon': 'gamepad',
        'description': 'Preferred WebRetro cores per console platform for Play Now.',
        'endpoint': 'admin2.emulator_profiles_page',
    },
    'reference_sets': {
        'label': 'ROM reference sets',
        'icon': 'list',
        'description': 'Upload No-Intro/Redump DAT files for regional set completeness.',
        'endpoint': 'admin2.reference_sets_admin',
    },
    'arr': {
        'label': 'Arr module',
        'icon': 'magnet',
        'description': 'Prowlarr/Jackett search and download clients (on by default; disable under Features).',
        'endpoint': 'arr.arr_admin_page',
    },
    'features': {
        'label': 'Features',
        'icon': 'sliders',
        'description': 'Turn product modules off. Auth/SSO stays off until Integrations.',
        'endpoint': 'admin2.features_settings_page',
    },
    'quality': {
        'label': 'Quality profiles',
        'icon': 'sliders',
        'description': 'Preferred/blocked release groups and size bands for Arr scoring.',
        'endpoint': 'admin2.quality_profiles_page',
    },
    'layouts': {
        'label': 'Detail layout',
        'icon': 'layout',
        'description': 'Reorder and show/hide game details sections.',
        'endpoint': 'admin2.detail_layout_page',
    },
    'ai': {
        'label': 'AI assist',
        'icon': 'robot',
        'description': 'Ollama triage and library-doctor notes (suggestions only).',
        'endpoint': 'admin2.ai_assist_page',
    },
    'storage': {
        'label': 'Storage / hardlinks',
        'icon': 'link',
        'description': 'Preview and optionally apply same-volume hardlinks.',
        'endpoint': 'admin2.storage_page',
    },
    'themes': {
        'label': 'Themes',
        'icon': 'palette',
        'description': 'Upload, activate, and manage installed UI themes.',
        'endpoint': 'admin2.manage_themes',
    },
    'art_studio': {
        'label': 'Art studio',
        'icon': 'palette',
        'description': 'Generate branded cover placeholders and fallback packs.',
        'endpoint': 'admin2.art_studio_page',
    },
    'remote_play': {
        'label': 'Remote play',
        'icon': 'gamepad',
        'description': 'BYO Sunshine or Wolf host for Moonlight streaming.',
        'endpoint': 'admin2.remote_play_page',
    },
}
DEFAULT_SETTINGS_SHELL_SECTION = 'server'

# Field mappings for database columns
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
    'proposeOnlyScan': 'propose_only_scan'
}


def validate_settings_data(settings_data):
    """Validate settings data and return errors if any."""
    errors = []
    
    if not isinstance(settings_data, dict):
        errors.append("Settings data must be a JSON object")
        return errors
    
    # Validate scan thread count
    scan_threads = settings_data.get('scanThreadCount')
    if scan_threads is not None:
        if not isinstance(scan_threads, int) or not (MIN_SCAN_THREADS <= scan_threads <= MAX_SCAN_THREADS):
            errors.append(f"Scan thread count must be between {MIN_SCAN_THREADS} and {MAX_SCAN_THREADS}")
    
    # Validate download threads
    download_threads = settings_data.get('turboDownloadThreads')
    if download_threads is not None:
        if not isinstance(download_threads, int) or not (MIN_DOWNLOAD_THREADS <= download_threads <= MAX_DOWNLOAD_THREADS):
            errors.append(f"Download threads must be between {MIN_DOWNLOAD_THREADS} and {MAX_DOWNLOAD_THREADS}")
    
    # Validate batch size
    batch_size = settings_data.get('turboDownloadBatchSize')
    if batch_size is not None:
        if not isinstance(batch_size, int) or not (MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE):
            errors.append(f"Batch size must be between {MIN_BATCH_SIZE} and {MAX_BATCH_SIZE}")
    
    # Validate folder names
    for folder_field in ['updateFolderName', 'extrasFolderName']:
        folder_name = settings_data.get(folder_field)
        if folder_name is not None:
            if not isinstance(folder_name, str) or not folder_name.strip():
                errors.append(f"{folder_field} must be a non-empty string")
            elif len(folder_name) > 100:
                errors.append(f"{folder_field} must be less than 100 characters")
    
    # Validate site URL
    site_url = settings_data.get('siteUrl')
    if site_url is not None:
        if not isinstance(site_url, str) or not site_url.strip():
            errors.append("Site URL must be a non-empty string")
        elif len(site_url) > 500:
            errors.append("Site URL must be less than 500 characters")

    # Validate HLTB rate limit delay
    hltb_delay = settings_data.get('hltbRateLimitDelay')
    if hltb_delay is not None:
        if not isinstance(hltb_delay, (int, float)) or not (0.5 <= hltb_delay <= 10.0):
            errors.append("HLTB rate limit delay must be between 0.5 and 10.0 seconds")

    # Validate local metadata filename
    metadata_filename = settings_data.get('localMetadataFilename')
    if metadata_filename is not None:
        if not isinstance(metadata_filename, str):
            errors.append("Local metadata filename must be a string")
        elif not metadata_filename.strip():
            errors.append("Local metadata filename cannot be empty")
        elif not metadata_filename.endswith('.json'):
            errors.append("Local metadata filename must end with .json")
        elif len(metadata_filename) > 50:
            errors.append("Local metadata filename too long (max 50 characters)")
        elif '/' in metadata_filename or '\\' in metadata_filename:
            errors.append("Local metadata filename cannot contain path separators")

    # W20-4 scan/match policy (also validated on dedicated API)
    for thr_field, label in (
        ('matchHighThreshold', 'Match high threshold'),
        ('matchAmbiguousGap', 'Match ambiguous gap'),
        ('dupeTitleThreshold', 'Dupe title threshold'),
        ('match_high_threshold', 'Match high threshold'),
        ('match_ambiguous_gap', 'Match ambiguous gap'),
        ('dupe_title_threshold', 'Dupe title threshold'),
    ):
        value = settings_data.get(thr_field)
        if value is not None:
            if not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 1.0):
                errors.append(f"{label} must be a number between 0 and 1")

    peel = settings_data.get('peelProfile', settings_data.get('peel_profile'))
    if peel is not None:
        if str(peel).strip().lower() not in ('conservative', 'aggressive'):
            errors.append("Peel profile must be 'conservative' or 'aggressive'")

    return errors


def get_or_create_settings_record():
    """Get existing settings record or create a new one.

    Creates through the shared helper rather than adding a row by hand: the
    table now carries the single-row unique index, so a first-boot race here no
    longer yields a harmless duplicate — it raises IntegrityError, which this
    function did not handle and which would 500 the save and poison the
    caller's transaction. global_settings_row_or_create() wraps the insert in a
    SAVEPOINT and hands back the winner's row.
    """
    settings_record = global_settings_row_or_create()
    if settings_record.settings is None:
        # Callers index into `.settings` — a fresh row must start as a dict, not
        # NULL, which is what the direct GlobalSettings(settings={}) gave it.
        settings_record.settings = {}
    return settings_record


def update_settings_fields(settings_record, new_settings):
    """Update individual database fields from settings data."""
    for json_field, db_field in FIELD_MAPPINGS.items():
        if json_field in new_settings:
            # Skip scanThreadCount here - it will be handled with validation below
            if json_field == 'scanThreadCount':
                continue
            setattr(settings_record, db_field, new_settings[json_field])
    
    # Apply validation for specific fields
    scan_threads = new_settings.get('scanThreadCount')
    if scan_threads is not None and MIN_SCAN_THREADS <= scan_threads <= MAX_SCAN_THREADS:
        settings_record.scan_thread_count = scan_threads
    
    # Update the settings JSON field and timestamp
    settings_record.settings = new_settings
    settings_record.last_updated = datetime.now(timezone.utc)


def build_current_settings(settings_record):
    """Build current settings dictionary from database record."""
    if not settings_record:
        return DEFAULT_SETTINGS.copy()
    
    # Start with stored JSON settings
    current_settings = settings_record.settings.copy() if settings_record.settings else {}
    
    # Merge with default settings for any missing keys
    for key, default_value in DEFAULT_SETTINGS.items():
        if key not in current_settings:
            current_settings[key] = default_value
    
    # Override with individual database field values
    for json_field, db_field in FIELD_MAPPINGS.items():
        db_value = getattr(settings_record, db_field, None)
        if db_value is not None:
            current_settings[json_field] = db_value
    
    return current_settings


def update_settings():
    """Handle POST requests for updating settings."""
    try:
        # Validate request has JSON content
        if not request.is_json:
            return api_error('Request must be JSON', code='bad_request')

        new_settings = request.get_json()
        if not new_settings:
            return api_error('No settings data provided', code='bad_request')

        # Validate settings data
        validation_errors = validate_settings_data(new_settings)
        if validation_errors:
            return jsonify({'errors': validation_errors}), 400

        logging.info(f"Updating settings: {list(new_settings.keys())}")

        # Get or create settings record
        settings_record = get_or_create_settings_record()

        # Update settings fields
        update_settings_fields(settings_record, new_settings)

        # Commit changes
        db.session.commit()

        # Log and clear cache
        log_system_event(
            f"Global settings updated by {current_user.name}. Updated fields: {', '.join(new_settings.keys())}",
            event_type='audit',
            event_level='information'
        )
        cache.delete('global_settings')

        return api_ok({'message': 'Settings updated successfully'})

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating settings: {str(e)}")
        return api_error('Failed to update settings', code='internal')


@admin2_bp.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    """
    Main settings endpoint.
    GET: Render the Settings hub, a grid of cards that link straight to each
         settings page. A known ?section= value redirects to that page directly
         so older links (and bookmarks) also cost a single click; unknown values
         fall through to the hub.
    POST: Handle settings update (used by admin_manage_server_settings.js).
    """
    if request.method == 'GET':
        section = request.args.get('section')
        if section in SETTINGS_SHELL_SECTIONS:
            return redirect(url_for(SETTINGS_SHELL_SECTIONS[section]['endpoint']))
        from oneirodex.utils.module_status import settings_hub_module_status

        return render_template(
            'admin/admin_settings_shell.html',
            sections=SETTINGS_SHELL_SECTIONS,
            module_status=settings_hub_module_status(),
        )
    else:
        return update_settings()


@admin2_bp.route('/admin/new_server_settings', methods=['GET', 'POST'])
@login_required
@admin_required
def new_server_settings():
    """Handle server settings page."""
    if request.method == 'POST':
        return update_settings()
    else:
        try:
            settings_record = global_settings_row()
            current_settings = build_current_settings(settings_record)
            return render_template('admin/new_server_settings.html', current_settings=current_settings)
        except Exception as e:
            logging.error(f"Error retrieving settings: {str(e)}")
            abort(500)


@admin2_bp.route('/admin/integrations', methods=['GET'])
@login_required
@admin_required
def integrations():
    """Handle integrations page with tabbed email, IGDB, community, artwork, and OIDC settings."""
    try:
        # Get global settings for all integrations
        settings_record = global_settings_row()

        # Build current settings for JavaScript consumption
        current_settings = build_current_settings(settings_record)

        api_key = get_steamgriddb_api_key()
        env_key = (os.getenv('STEAMGRIDDB_API_KEY') or '').strip()
        steamgriddb_status = {
            'enabled': bool(api_key),
            'source': 'env' if env_key else ('database' if api_key else None),
            'masked_key': mask_api_key(api_key),
        }

        community_chat_url = ''
        community_chat_label = 'Open community'
        if settings_record is not None:
            community_chat_url = getattr(settings_record, 'community_chat_url', None) or ''
            community_chat_label = getattr(settings_record, 'community_chat_label', None) or 'Open community'

        return render_template(
            'admin/integrations.html',
            settings=settings_record,
            current_settings=current_settings,
            steamgriddb_status=steamgriddb_status,
            community_chat_url=community_chat_url,
            community_chat_label=community_chat_label,
        )
    except Exception as e:
        logging.exception('Error retrieving integrations: %s', e)
        abort(500)


@admin2_bp.route('/admin/integrations/igdb/save', methods=['POST'])
@login_required
@admin_required
def integrations_igdb_save():
    """Handle IGDB settings save from integrations page."""
    try:
        data = request.json
        settings = global_settings_row_or_create()

        # Validate input
        client_id = data.get('igdb_client_id', '').strip()
        # The page never shows the saved secret; blank keeps it.
        client_secret = data.get('igdb_client_secret', '').strip() or (settings.igdb_client_secret or '')

        if len(client_id) < 20 or len(client_secret) < 20:
            return api_error('Client ID and Secret must be at least 20 characters long', code='bad_request')

        settings.igdb_client_id = client_id
        settings.igdb_client_secret = client_secret

        db.session.commit()
        log_system_event("IGDB settings updated via integrations page")

        return api_ok({'message': 'IGDB settings saved successfully'})

    except Exception as e:
        db.session.rollback()
        logging.error("Error saving IGDB settings from integrations: %s", type(e).__name__)
        return api_error('Could not save the IGDB settings.', code='internal')


@admin2_bp.route('/admin/integrations/igdb/test', methods=['POST'])
@login_required
@admin_required
def integrations_igdb_test():
    """Handle IGDB settings test from integrations page."""
    try:
        logging.info("Testing IGDB connection from integrations page...")
        settings = global_settings_row()

        if not settings or not settings.igdb_client_id or not settings.igdb_client_secret:
            return api_error('IGDB settings not configured. Please save your settings first.', code='bad_request')

        # Test the IGDB API with a simple query
        response = make_igdb_api_request('https://api.igdb.com/v4/games', 'fields name; limit 1;')

        if isinstance(response, list):
            logging.info("IGDB API test successful from integrations page")
            settings.igdb_last_tested = datetime.now(timezone.utc)
            db.session.commit()
            log_system_event("IGDB API test successful via integrations page")
            return api_ok({'message': 'IGDB API test successful'})
        else:
            logging.warning("IGDB API test failed - invalid response")
            return api_error('Invalid API response', code='internal')

    except Exception as e:
        # Not str(e): the IGDB request carries the client secret in its URL.
        logging.error("Error testing IGDB from integrations: %s", type(e).__name__)
        return api_error('The IGDB connection test failed.', code='internal')


@admin2_bp.route('/admin/integrations/oidc/save', methods=['POST'])
@login_required
@admin_required
def integrations_oidc_save():
    """Persist OIDC / SSO settings from the integrations page."""
    try:
        data = request.get_json(silent=True) or {}
        settings = get_or_create_settings_record()
        issuer_url = (data.get('oidc_issuer_url') or '').strip()[:512] or None
        if issuer_url and not is_secure_oidc_issuer(issuer_url):
            return api_error('OIDC issuer URL must use HTTPS.', code='bad_request')

        settings.oidc_enabled = bool(data.get('oidc_enabled', False))
        settings.oidc_display_name = (data.get('oidc_display_name') or 'Sign in with SSO').strip()[:120]
        settings.oidc_issuer_url = issuer_url
        settings.oidc_client_id = (data.get('oidc_client_id') or '').strip()[:255] or None
        # The page never shows the saved secret; blank keeps it.
        new_secret = (data.get('oidc_client_secret') or '').strip()[:512]
        if new_secret:
            settings.oidc_client_secret = new_secret
        settings.oidc_redirect_uri = (data.get('oidc_redirect_uri') or '').strip()[:512] or None
        settings.oidc_scopes = (data.get('oidc_scopes') or 'openid email profile').strip()[:255]
        settings.oidc_role_claim = (data.get('oidc_role_claim') or 'groups').strip()[:64]

        role_map = data.get('oidc_role_map')
        if isinstance(role_map, str):
            try:
                role_map = json.loads(role_map)
            except json.JSONDecodeError:
                return api_error('Role map must be valid JSON.', code='bad_request')
        if role_map is not None and not isinstance(role_map, dict):
            return api_error('Role map must be a JSON object.', code='bad_request')
        settings.oidc_role_map = role_map

        if settings.oidc_enabled:
            missing = []
            if not settings.oidc_issuer_url:
                missing.append('issuer URL')
            if not settings.oidc_client_id:
                missing.append('client ID')
            if not settings.oidc_redirect_uri:
                missing.append('redirect URI')
            if missing:
                return api_error(f"When enabling SSO, provide: {', '.join(missing)}.", code='bad_request')

        settings.last_updated = datetime.now(timezone.utc)
        db.session.commit()
        cache.delete('global_settings')
        log_system_event('OIDC settings updated via integrations page', event_type='audit', event_level='information')
        return api_ok({'message': 'OIDC settings saved successfully.'})
    except Exception as e:
        db.session.rollback()
        logging.error("Error saving OIDC settings: %s", type(e).__name__)
        return api_error('Could not save the OIDC settings.', code='internal')


@admin2_bp.route('/admin/integrations/community', methods=['POST'])
@login_required
@admin_required
def community_chat_settings():
    """Persist BYO Stoat/Matrix community deep-link (no Discord)."""
    from oneirodex.utils.security import validate_community_chat_url

    settings = global_settings_row_or_create()

    raw_url = (request.form.get('community_chat_url') or '').strip()
    label = (request.form.get('community_chat_label') or 'Open community').strip()[:120]
    ok, normalized_or_err = validate_community_chat_url(raw_url)
    if not ok:
        flash(normalized_or_err, 'error')
        return redirect(url_for('admin2.integrations') + '#community')

    settings.community_chat_url = normalized_or_err or None
    settings.community_chat_label = label or 'Open community'
    try:
        db.session.commit()
        log_system_event('Community chat link updated via integrations')
        flash('Community chat link saved.', 'success')
    except Exception as e:
        db.session.rollback()
        logging.error('Error saving community chat settings: %s', e)
        flash('Failed to save community chat link.', 'error')
    return redirect(url_for('admin2.integrations') + '#community')


@admin2_bp.route('/admin/emulator_profiles', methods=['GET'])
@login_required
@admin_required
def emulator_profiles_page():
    """Admin UI for preferred WebRetro cores per platform."""
    return render_template('admin/emulator_profiles.html')


@admin2_bp.route('/admin/quality_profiles', methods=['GET'])
@login_required
@admin_required
def quality_profiles_page():
    """Admin UI for release quality / scene group preferences."""
    return render_template('admin/quality_profiles.html')


@admin2_bp.route('/admin/detail_layout', methods=['GET'])
@login_required
@admin_required
def detail_layout_page():
    return render_template('admin/detail_layout.html')


@admin2_bp.route('/admin/ai', methods=['GET'])
@login_required
@admin_required
def ai_assist_page():
    from oneirodex.utils.ai_assist import get_ai_config

    return render_template('admin/ai_assist.html', ai_config=get_ai_config())


@admin2_bp.route('/admin/storage', methods=['GET'])
@login_required
@admin_required
def storage_page():
    from oneirodex.utils.module_status import hardlink_apply_on, hardlink_helpers_on

    helpers_on = hardlink_helpers_on()
    allow_apply = hardlink_apply_on()
    return render_template(
        'admin/storage.html',
        helpers_enabled=helpers_on,
        allow_apply=allow_apply,
    )


@admin2_bp.route('/admin/scan_match', methods=['GET'])
@login_required
@admin_required
def scan_match_settings_page():
    """React ScanMatchSettingsPage shell (W20-4). Config via /api/admin/scan-match/config."""
    return render_template('admin/admin_scan_match_settings.html')
