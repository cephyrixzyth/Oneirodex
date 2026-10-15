"""Admin theme inventory and native upload/delete actions."""

from __future__ import annotations

from flask import current_app, request
from flask_login import login_required, current_user

from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.loading_icons import get_loading_icon_settings
from oneirodex.utils.themes import ThemeManager
from oneirodex.routes_admin_ext.themes import is_valid_theme_name, validate_theme_file
from . import apis_bp


def _theme_payload():
    manager = ThemeManager(current_app)
    preference = getattr(current_user, 'preferences', None)
    active = getattr(preference, 'theme', None) or 'default'
    themes = manager.get_installed_themes()
    return {
        'themes': themes,
        'default_theme': manager.get_default_theme(),
        'active_theme': active,
    }


@apis_bp.route('/admin/themes', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_themes():
    if request.method == 'GET':
        return api_ok(_theme_payload())

    upload = request.files.get('theme_zip')
    valid, reason = validate_theme_file(upload)
    if not valid:
        return api_error(reason or 'Invalid theme ZIP', code='bad_request')
    manager = ThemeManager(current_app)
    try:
        data = manager.upload_theme(upload)
        if not data:
            return api_error('Theme upload failed. Check the ZIP contents and try again.', code='bad_request')
        valid_name, reason = is_valid_theme_name(data.get('name', ''))
        if not valid_name:
            # upload_theme reserves/cleans its temporary directory, but the
            # installed folder exists now. Remove it before rejecting a name.
            from werkzeug.utils import secure_filename
            folder = secure_filename(str(data.get('name', '')))
            try:
                manager.delete_themefile(folder)
            except Exception:
                current_app.logger.exception('Could not clean up rejected theme upload')
            return api_error(reason or 'Invalid theme name', code='bad_request')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except Exception:
        current_app.logger.exception('Theme upload failed')
        return api_error('Theme upload failed. Please try again.', code='internal')
    return api_ok({'status': 'uploaded', 'theme': data, **_theme_payload()})


@apis_bp.route('/admin/themes/<theme_name>', methods=['DELETE'])
@login_required
@admin_required
def delete_admin_theme(theme_name: str):
    valid, reason = is_valid_theme_name(theme_name)
    if not valid:
        return api_error(reason or 'Invalid theme name', code='bad_request')
    try:
        ThemeManager(current_app).delete_themefile(theme_name)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except Exception:
        current_app.logger.exception('Theme deletion failed')
        return api_error('Theme deletion failed. Please try again.', code='internal')
    return api_ok({'status': 'deleted', 'theme_name': theme_name, **_theme_payload()})


@apis_bp.route('/admin/themes/loading-icons', methods=['GET'])
@login_required
@admin_required
def admin_theme_loading_icons():
    return api_ok(get_loading_icon_settings(admin=True))

