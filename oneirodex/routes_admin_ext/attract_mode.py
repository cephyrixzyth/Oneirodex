# /oneirodex/routes_admin_ext/attract_mode.py
from oneirodex.utils.api_response import api_error, api_ok
from flask import request, jsonify, current_app
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
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.utils.attract_mode_defaults import DEFAULT_ATTRACT_MODE_SETTINGS
import json
import logging
from copy import deepcopy
from pydantic import ValidationError
from oneirodex.schemas.attract_mode import AttractModeBody

# Configuration constants
MIN_IDLE_TIMEOUT = 10  # seconds
MAX_IDLE_TIMEOUT = 300  # seconds (5 minutes)
DEFAULT_IDLE_TIMEOUT = 60  # seconds

def admin_attract_state(settings):
    config = deepcopy(DEFAULT_ATTRACT_MODE_SETTINGS)
    saved = settings.attract_mode_settings if settings else None
    if isinstance(saved, dict):
        for key in ('filters', 'autoplay'):
            if isinstance(saved.get(key), dict):
                config[key].update(saved[key])
    return {
        'enabled': bool(settings and settings.attract_mode_enabled),
        'idle_timeout': settings.attract_mode_idle_timeout or DEFAULT_IDLE_TIMEOUT if settings else DEFAULT_IDLE_TIMEOUT,
        'filters': config['filters'], 'autoplay': config['autoplay'],
    }


def attract_filter_options():
    libraries = db.session.execute(select(Library).order_by(Library.display_order, Library.name)).scalars().all()
    genres = db.session.execute(select(Genre).order_by(Genre.name)).scalars().all()
    themes = db.session.execute(select(Theme).order_by(Theme.name)).scalars().all()
    dates = db.session.execute(select(func.min(Game.first_release_date), func.max(Game.first_release_date)).filter(
        Game.video_urls.isnot(None), Game.video_urls != '', Game.first_release_date.isnot(None))).first()
    return {
        'libraries': [{'uuid': str(row.uuid), 'name': row.name} for row in libraries],
        'genres': [{'id': row.id, 'name': row.name} for row in genres],
        'themes': [{'id': row.id, 'name': row.name} for row in themes],
        'date_range': {'min_year': dates[0].year if dates and dates[0] else None,
                       'max_year': dates[1].year if dates and dates[1] else None},
    }


def persist_admin_attract(data):
    settings = global_settings_row_or_create()
    settings.attract_mode_enabled = data.get('enabled', False)
    settings.attract_mode_idle_timeout = int(data.get('idle_timeout', DEFAULT_IDLE_TIMEOUT))
    settings.attract_mode_settings = {
        'filters': data.get('filters', DEFAULT_ATTRACT_MODE_SETTINGS['filters']),
        'autoplay': data.get('autoplay', DEFAULT_ATTRACT_MODE_SETTINGS['autoplay']),
    }
    settings.last_updated = datetime.now(timezone.utc)
    db.session.commit()
    cache.clear()
    log_system_event(f'Attract mode settings updated by {current_user.name}',
                     event_type='configuration', event_level='information', audit_user=current_user.id)
    return settings


@admin2_bp.route('/api/admin/attract-mode/settings', methods=['GET', 'PUT'])
@login_required
@admin_required
def admin_attract_settings_api():
    if request.method == 'GET':
        try:
            response = current_app.make_response(api_ok({
                'settings': admin_attract_state(global_settings_row()),
                'filter_options': attract_filter_options(),
                'bounds': {'idle_timeout': {'min': MIN_IDLE_TIMEOUT, 'max': MAX_IDLE_TIMEOUT},
                           'skipFirst': {'min': 0, 'max': 300}, 'skipAfter': {'min': 0, 'max': 600},
                           'year': {'min': 1, 'max': 9999}},
            }))
            response.headers['Cache-Control'] = 'no-store'
            return response
        except Exception:
            current_app.logger.warning('Could not load admin attract mode settings')
            return api_error('Could not load attract mode settings', code='internal')
    try:
        data = AttractModeBody.model_validate(request.get_json(silent=True)).model_dump()
    except ValidationError as exc:
        fields = [{'field': '.'.join(str(part) for part in error['loc']), 'message': error['msg']}
                  for error in exc.errors(include_input=False, include_context=False, include_url=False)]
        return api_error('Check attract mode settings and try again', code='bad_request', detail=fields)
    try:
        settings = persist_admin_attract(data)
    except Exception:
        db.session.rollback()
        current_app.logger.warning('Could not save admin attract mode settings')
        return api_error('Could not save attract mode settings', code='internal')
    response = current_app.make_response(api_ok({'settings': admin_attract_state(settings), 'message': 'Attract mode settings saved.'}))
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin2_bp.route('/admin/attract_mode_settings', methods=['GET'])
@login_required
@admin_required
def attract_mode_settings_page():
    """Admin page for configuring attract mode settings"""
    return render_admin_spa(title='Attract mode · Oneirodex Admin')


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

        persist_admin_attract(data)

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
