# /oneirodex/routes_admin_ext/attract_mode.py
from oneirodex.utils.api_response import api_error, api_ok
from flask import render_template, request, jsonify
from flask_login import login_required, current_user
from oneirodex.models import GlobalSettings, UserAttractModeSettings, Library, Genre, Theme, Game
from oneirodex.models import LibraryPlatform
from oneirodex import db, cache
from sqlalchemy import select, func
from datetime import datetime, timezone
from . import admin2_bp
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)
from oneirodex.utils.auth import admin_required
import json
import logging

# Configuration constants
MIN_IDLE_TIMEOUT = 10  # seconds
MAX_IDLE_TIMEOUT = 300  # seconds (5 minutes)
DEFAULT_IDLE_TIMEOUT = 60  # seconds

# Default attract mode settings
DEFAULT_ATTRACT_MODE_SETTINGS = {
    'filters': {
        'library_uuid': None,
        'genres': [],
        'themes': [],
        'date_from': None,
        'date_to': None
    },
    'autoplay': {
        'enabled': True,
        'skipFirst': 0,
        'skipAfter': 0
    }
}


@admin2_bp.route('/admin/attract_mode_settings', methods=['GET'])
@login_required
@admin_required
def attract_mode_settings_page():
    """Admin page for configuring attract mode settings"""
    try:
        # Get current global settings
        global_settings = global_settings_row()

        # Prepare settings data
        settings_data = {
            'enabled': global_settings.attract_mode_enabled if global_settings else False,
            'idle_timeout': global_settings.attract_mode_idle_timeout if global_settings else DEFAULT_IDLE_TIMEOUT,
            'settings': global_settings.attract_mode_settings if global_settings and global_settings.attract_mode_settings else DEFAULT_ATTRACT_MODE_SETTINGS
        }

        # Get filter options for the form
        # Get all libraries
        libraries = db.session.execute(
            select(Library).order_by(Library.display_order, Library.name)
        ).scalars().all()

        # Get all genres
        genres = db.session.execute(
            select(Genre).order_by(Genre.name)
        ).scalars().all()

        # Get all themes
        themes = db.session.execute(
            select(Theme).order_by(Theme.name)
        ).scalars().all()

        # Get date range from games with videos
        date_range = db.session.execute(
            select(
                func.min(Game.first_release_date),
                func.max(Game.first_release_date)
            ).filter(
                Game.video_urls.isnot(None),
                Game.video_urls != '',
                Game.first_release_date.isnot(None)
            )
        ).first()

        min_year = date_range[0].year if date_range and date_range[0] else None
        max_year = date_range[1].year if date_range and date_range[1] else None

        filter_options = {
            'libraries': [{'uuid': str(lib.uuid), 'name': lib.name} for lib in libraries],
            'genres': [{'id': g.id, 'name': g.name} for g in genres],
            'themes': [{'id': t.id, 'name': t.name} for t in themes],
            'date_range': {
                'min_year': min_year,
                'max_year': max_year
            }
        }

        return render_template(
            'admin/attract_mode_settings.html',
            settings=settings_data,
            filter_options=filter_options,
            min_timeout=MIN_IDLE_TIMEOUT,
            max_timeout=MAX_IDLE_TIMEOUT
        )

    except Exception as e:
        logging.error(f"Error loading attract mode settings page: {e}")
        return render_template('admin/attract_mode_settings.html',
                             settings={'enabled': False, 'idle_timeout': DEFAULT_IDLE_TIMEOUT, 'settings': DEFAULT_ATTRACT_MODE_SETTINGS},
                             filter_options={'libraries': [], 'genres': [], 'themes': [], 'date_range': {}},
                             min_timeout=MIN_IDLE_TIMEOUT,
                             max_timeout=MAX_IDLE_TIMEOUT,
                             error="Failed to load settings")


@admin2_bp.route('/admin/attract_mode_settings', methods=['POST'])
@login_required
@admin_required
def save_attract_mode_settings():
    """Save attract mode settings"""
    try:
        data = request.get_json()

        if not data:
            return api_error('No data provided', code='bad_request')

        # Validate data
        errors = validate_attract_mode_settings(data)
        if errors:
            return api_error('Validation failed', code='bad_request', errors=errors)

        # Get or create global settings
        global_settings = global_settings_row_or_create()

        # Update settings
        global_settings.attract_mode_enabled = data.get('enabled', False)
        global_settings.attract_mode_idle_timeout = int(data.get('idle_timeout', DEFAULT_IDLE_TIMEOUT))

        # Store filter and autoplay settings as JSON
        settings_json = {
            'filters': data.get('filters', DEFAULT_ATTRACT_MODE_SETTINGS['filters']),
            'autoplay': data.get('autoplay', DEFAULT_ATTRACT_MODE_SETTINGS['autoplay'])
        }
        global_settings.attract_mode_settings = settings_json
        global_settings.last_updated = datetime.now(timezone.utc)

        db.session.commit()

        # Clear cache
        cache.clear()

        # Log the change
        log_system_event(
            f'Attract mode settings updated by {current_user.name}',
            event_type='configuration',
            event_level='information',
            audit_user=current_user.id,
        )

        return api_ok({'message': 'Attract mode settings saved successfully'})

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error saving attract mode settings: {e}")
        return api_error('Could not save the attract mode settings', code='internal')


@admin2_bp.route('/api/attract-mode/settings', methods=['GET'])
def get_attract_mode_settings():
    """
    Public API endpoint to get attract mode settings for current user.
    Merges admin defaults with user overrides if they exist.
    No authentication required - works for anonymous users too.
    """
    try:
        # Get global settings
        global_settings = global_settings_row()

        if not global_settings or not global_settings.attract_mode_enabled:
            return jsonify({
                'enabled': False,
                'idle_timeout': 0,
                'settings': None
            })

        # Start with admin defaults
        result = {
            'enabled': True,
            'idle_timeout': global_settings.attract_mode_idle_timeout,
            'settings': global_settings.attract_mode_settings or DEFAULT_ATTRACT_MODE_SETTINGS
        }

        # If user is authenticated, check for user overrides
        if current_user.is_authenticated:
            user_settings = db.session.execute(
                select(UserAttractModeSettings).filter_by(user_id=current_user.user_id)
            ).scalar_one_or_none()

            if user_settings and user_settings.has_customized:
                # Merge user overrides with admin defaults
                if user_settings.filter_settings:
                    result['settings']['filters'] = user_settings.filter_settings
                if user_settings.autoplay_settings:
                    result['settings']['autoplay'] = user_settings.autoplay_settings

        return jsonify(result)

    except Exception as e:
        logging.error(f"Error fetching attract mode settings: {e}")
        return jsonify({
            'enabled': False,
            'idle_timeout': 0,
            'settings': None
        })


@admin2_bp.route('/api/attract-mode/user-override', methods=['POST'])
@login_required
def save_user_attract_mode_override():
    """
    Save user-specific attract mode settings override.
    User overrides persist forever once set.
    """
    try:
        data = request.get_json()
        logging.info(f"Received user override data: {data}")

        if not data:
            logging.warning('No data provided in request')
            return api_error('No data provided', code='bad_request')

        # Get or create user settings
        user_settings = db.session.execute(
            select(UserAttractModeSettings).filter_by(user_id=current_user.user_id)
        ).scalar_one_or_none()

        if not user_settings:
            user_settings = UserAttractModeSettings(user_id=current_user.user_id)
            db.session.add(user_settings)

        # Update user settings
        user_settings.has_customized = True
        if 'filters' in data:
            user_settings.filter_settings = data['filters']
        if 'autoplay' in data:
            user_settings.autoplay_settings = data['autoplay']
        user_settings.updated_at = datetime.now(timezone.utc)

        db.session.commit()

        # Log the change
        log_system_event(
            f'User {current_user.name} customized attract mode settings',
            event_type='user_preference',
            event_level='information',
            audit_user=current_user.id,
        )

        return api_ok({'message': 'Your attract mode preferences have been saved'})

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error saving user attract mode override: {e}", exc_info=True)
        return api_error('Could not save your attract mode preferences', code='internal')


def validate_attract_mode_settings(data):
    """Validate attract mode settings data"""
    errors = []

    # Validate idle timeout
    idle_timeout = data.get('idle_timeout')
    if idle_timeout is not None:
        try:
            idle_timeout = int(idle_timeout)
            if idle_timeout < MIN_IDLE_TIMEOUT or idle_timeout > MAX_IDLE_TIMEOUT:
                errors.append(f'Idle timeout must be between {MIN_IDLE_TIMEOUT} and {MAX_IDLE_TIMEOUT} seconds')
        except (ValueError, TypeError):
            errors.append('Idle timeout must be a valid number')

    # Validate autoplay settings if provided
    autoplay = data.get('autoplay', {})
    if autoplay:
        skip_first = autoplay.get('skipFirst')
        if skip_first is not None:
            try:
                skip_first = int(skip_first)
                if skip_first < 0 or skip_first > 300:
                    errors.append('Skip first must be between 0 and 300 seconds')
            except (ValueError, TypeError):
                errors.append('Skip first must be a valid number')

        skip_after = autoplay.get('skipAfter')
        if skip_after is not None:
            try:
                skip_after = int(skip_after)
                if skip_after < 0 or skip_after > 600:
                    errors.append('Skip after must be between 0 and 600 seconds')
            except (ValueError, TypeError):
                errors.append('Skip after must be a valid number')

    return errors
