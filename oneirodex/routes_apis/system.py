# /oneirodex/routes_apis/system.py
import os
import re
from pathlib import Path
from oneirodex.utils.api_response import api_error, api_ok
from flask import jsonify, request, current_app, abort
from flask_login import login_required
from oneirodex import db
from oneirodex.models import AllowedFileType, IgnoredFileType
from oneirodex.platform import Emulator, LibraryPlatform, platform_emulator_mapping
from oneirodex.utils.auth import admin_required
from oneirodex.utils.browser_player import (
    get_browser_player_settings,
    set_browser_player_settings,
)
from oneirodex.utils.security import is_safe_path, get_allowed_base_directories
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import apis_bp


def validate_file_type_value(value):
    """Validate and sanitize file type values to prevent injection attacks."""
    if not value or not isinstance(value, str):
        return None
    
    # Remove any potentially dangerous characters and normalize
    value = str(value).strip().lower()
    
    # File extensions should only contain alphanumeric characters, dots, and hyphens
    if not re.match(r'^[a-z0-9.-]+$', value):
        return None
    
    # Ensure it does NOT start with a dot for consistency
    if value.startswith('.'):
        value = value[1:]
    if not value:
        return None
    
    # Prevent excessively long values
    if len(value) > 10:
        return None
    
    return value




def validate_json_input(required_fields=None):
    """Validate JSON input and check for required fields."""
    if not request.is_json:
        return None, "Request must be JSON"
    
    try:
        data = request.get_json()
        if data is None:
            return None, "Invalid JSON format"
        
        if required_fields:
            for field in required_fields:
                if field not in data:
                    return None, f"Missing required field: {field}"
        
        return data, None
    
    except Exception as e:
        current_app.logger.warning(f"JSON validation error: {e}")
        return None, "Invalid JSON format"


@apis_bp.route('/file_types/<string:type_category>', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
@admin_required
def manage_file_types(type_category):
    # Validate type category
    if type_category not in ['allowed', 'ignored']:
        return api_error('Invalid type category', code='bad_request')

    ModelClass = AllowedFileType if type_category == 'allowed' else IgnoredFileType

    try:
        if request.method == 'GET':
            types = db.session.execute(select(ModelClass).order_by(ModelClass.value.asc())).scalars().all()
            return jsonify([{'id': t.id, 'value': t.value} for t in types])

        elif request.method == 'POST':
            data, error = validate_json_input(['value'])
            if error:
                return api_error(error, code='bad_request')
            
            # Validate and sanitize the file type value
            sanitized_value = validate_file_type_value(data['value'])
            if not sanitized_value:
                return api_error('Invalid file type format', code='bad_request')
            
            new_type = ModelClass(value=sanitized_value)
            try:
                db.session.add(new_type)
                db.session.commit()
                return jsonify({'id': new_type.id, 'value': new_type.value}), 201
            except IntegrityError:
                db.session.rollback()
                return api_error('File type already exists', code='conflict')

        elif request.method == 'PUT':
            data, error = validate_json_input(['id', 'value'])
            if error:
                return api_error(error, code='bad_request')
            
            # Validate ID is numeric
            try:
                file_type_id = int(data['id'])
            except (ValueError, TypeError):
                return api_error('Invalid ID format', code='bad_request')
            
            # Validate and sanitize the file type value
            sanitized_value = validate_file_type_value(data['value'])
            if not sanitized_value:
                return api_error('Invalid file type format', code='bad_request')
            
            file_type = db.session.get(ModelClass, file_type_id)
            if not file_type:
                return api_error('File type not found', code='not_found')
                
            file_type.value = sanitized_value
            try:
                db.session.commit()
                return jsonify({'id': file_type.id, 'value': file_type.value})
            except IntegrityError:
                db.session.rollback()
                return api_error('File type already exists', code='conflict')

        elif request.method == 'DELETE':
            data, error = validate_json_input(['id'])
            if error:
                return api_error(error, code='bad_request')
            
            # Validate ID is numeric
            try:
                file_type_id = int(data['id'])
            except (ValueError, TypeError):
                return api_error('Invalid ID format', code='bad_request')
            
            file_type = db.session.get(ModelClass, file_type_id)
            if not file_type:
                return api_error('File type not found', code='not_found')
                
            db.session.delete(file_type)
            db.session.commit()
            return api_ok()
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error managing file types: {e}")
        return api_error('An error occurred while processing your request', code='internal')
    
@apis_bp.route('/check_path_availability', methods=['GET'])
@login_required
def check_path_availability():
    """Check if a file path exists, with security validation to prevent path traversal."""
    full_disk_path = request.args.get('full_disk_path', '').strip()
    
    if not full_disk_path:
        return api_error('Path parameter required', code='bad_request', available=False)
    
    # Get allowed base directories from config
    allowed_bases = get_allowed_base_directories(current_app)
    if not allowed_bases:
        current_app.logger.error("No allowed base directories configured")
        return api_error('Service configuration error', code='internal', available=False)
    
    # Use secure path validation
    is_safe, error_message = is_safe_path(full_disk_path, allowed_bases)
    if not is_safe:
        return api_error(error_message, code='forbidden', available=False)
    
    try:
        # Only check existence if path is validated as safe
        path_obj = Path(full_disk_path).resolve()
        is_available = path_obj.exists()
        
        # Don't reveal detailed filesystem information - just return boolean
        return jsonify({'available': is_available})
        
    except (OSError, ValueError) as e:
        current_app.logger.warning(f"Path existence check failed for validated path: {e}")
        return api_error('Unable to check path', code='internal', available=False)

@apis_bp.route('/emulators', methods=['GET'])
@apis_bp.route('/emulators/<platform>', methods=['GET'])
@login_required
def get_emulators(platform=None):
    """Return emulators for a specific platform or all emulators if no platform specified."""
    try:
        from oneirodex.utils.emulator_profiles import (
            get_emulator_profiles,
            resolve_emulators_for_platform,
        )

        if platform:
            # Validate platform parameter to prevent enumeration attacks
            if not isinstance(platform, str) or len(platform) > 50:
                return api_error('Invalid platform parameter', code='bad_request')
            
            try:
                return jsonify(resolve_emulators_for_platform(platform))
            except KeyError:
                # Don't reveal valid platform names in error message
                return api_error('Platform not supported', code='not_found')
        else:
            emulators = [e.value for e in Emulator]
            return jsonify({
                'emulators': emulators,
                'profiles': get_emulator_profiles(),
            })
        
    except Exception as e:
        current_app.logger.error(f"Error retrieving emulators: {e}")
        return api_error('Unable to retrieve emulators', code='internal')


@apis_bp.route('/emulator-profiles', methods=['GET'])
@login_required
@admin_required
def emulator_profiles_get():
    """Admin: list preferred WebRetro cores per platform."""
    from oneirodex.utils.emulator_profiles import get_emulator_profiles

    profiles = get_emulator_profiles()
    catalog = {
        p.name: [e.value for e in platform_emulator_mapping.get(p, [])]
        for p in LibraryPlatform
        if platform_emulator_mapping.get(p)
    }
    return jsonify({'profiles': profiles, 'catalog': catalog})


@apis_bp.route('/emulator-profiles', methods=['PUT', 'POST'])
@login_required
@admin_required
def emulator_profiles_save():
    """Admin: set preferred WebRetro cores. Body: {\"profiles\": {\"NES\": \"nestopia\"}}."""
    from oneirodex.utils.emulator_profiles import set_emulator_profiles

    data = request.get_json(silent=True) or {}
    profiles = data.get('profiles')
    if profiles is None and isinstance(data, dict):
        # Allow flat map body
        profiles = {k: v for k, v in data.items() if k != 'profiles'}
    if not isinstance(profiles, dict):
        return api_error('profiles object required', code='bad_request')
    try:
        saved = set_emulator_profiles(profiles)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    catalog = {
        p.name: [e.value for e in platform_emulator_mapping.get(p, [])]
        for p in LibraryPlatform
        if platform_emulator_mapping.get(p)
    }
    return jsonify({'profiles': saved, 'catalog': catalog})


@apis_bp.route('/browser-player-settings', methods=['GET'])
@login_required
@admin_required
def browser_player_settings_get():
    """Admin: browser play engine defaults (BP-0 / BP-1). Only shipped engines are selectable."""
    return api_ok(get_browser_player_settings())


@apis_bp.route('/browser-player-settings', methods=['PUT', 'POST'])
@login_required
@admin_required
def browser_player_settings_save():
    """Admin: persist browser play engine keys. Unwired engines are rejected."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return api_error('JSON object required', code='bad_request')
    try:
        saved = set_browser_player_settings(data)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok(saved)
