from flask import request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from oneirodex import db
from oneirodex.models import UserPreference
from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.forms import ThemeUploadForm
from oneirodex.utils.themes import ThemeManager
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.icon_themes import get_icon_pack
import json
import os
from pathlib import Path
from typing import Any, Optional, Union
from . import admin2_bp
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.theme_validation import (
    MAX_THEME_FILE_SIZE, WINDOWS_RESERVED_NAMES, ZIP_MAGIC_BYTES,
    is_valid_theme_name, validate_theme_file,
)

# Configuration constants
def _read_theme_default_icon_pack(themes_root: Path, theme: str) -> Optional[str]:
    """Return ``default_icon_pack`` from an installed theme's ``theme.json``, if any."""
    theme_json = themes_root / theme / 'theme.json'
    if not theme_json.is_file():
        return None
    try:
        data = json.loads(theme_json.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    pack = data.get('default_icon_pack')
    if isinstance(pack, str) and pack.strip():
        return pack.strip()
    return None


def resolve_apply_icon_pack(
    payload: dict[str, Any],
    form,
    themes_root: Path,
    theme: str,
) -> Optional[str]:
    """Resolve icon pack for theme apply.

    Preference order matches Preferences pairing:
    1. Explicit non-empty ``icon_pack`` in JSON/form body
    2. Applied theme's ``theme.json`` ``default_icon_pack`` when present
    3. ``None`` — leave the existing ``UserPreference.icon_pack`` unchanged

    Returns a normalised pack id (unknown ids → ``outline`` via ``get_icon_pack``).
    """
    if isinstance(payload, dict) and 'icon_pack' in payload:
        raw = payload.get('icon_pack')
    else:
        raw = form.get('icon_pack') if form is not None else None
    if isinstance(raw, str) and raw.strip():
        return get_icon_pack(raw.strip())['id']
    from_theme = _read_theme_default_icon_pack(themes_root, theme)
    if from_theme:
        return get_icon_pack(from_theme)['id']
    return None


@admin2_bp.route('/admin/themes', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_themes():
    """Manage themes - upload, list, and configure themes.
    
    Returns:
        Response: Rendered template or redirect
    """
    if request.method == 'GET':
        return render_admin_spa(title='Themes · Oneirodex Admin')

    form = ThemeUploadForm()
    theme_manager = ThemeManager(current_app)
    upload_folder = Path(current_app.config['UPLOAD_FOLDER']) / 'themes'
    
    if not upload_folder.exists():
        try:
            upload_folder.mkdir(parents=True, exist_ok=True)
            log_system_event(
                f"Created themes upload directory: {upload_folder}",
                event_type='themes',
                event_level='information'
            )
        except Exception as e:
            log_system_event(
                f"Error creating upload directory: {e}",
                event_type='themes',
                event_level='error'
            )
            flash("Error processing request. Please try again.", 'error')
            return redirect(url_for('admin2.manage_themes'))

    # JSON requests are the native admin SPA upload path. Keep the existing
    # multipart Flask-WTF form below as the compatibility route.
    if request.method == 'POST' and request.is_json:
        return api_error('Upload a ZIP file using multipart form data', code='bad_request')

    if form.validate_on_submit():
        theme_zip = form.theme_zip.data
        
        # Validate the uploaded file
        is_valid_file, file_error = validate_theme_file(theme_zip)
        if not is_valid_file:
            log_system_event(
                f"Theme upload failed - file validation: {file_error}",
                event_type='themes',
                event_level='warning'
            )
            flash(f"Upload failed: {file_error}", 'error')
            return redirect(url_for('admin2.manage_themes'))
        
        try:
            theme_data = theme_manager.upload_theme(theme_zip)
            if theme_data:
                # Validate theme name
                is_valid_name, name_error = is_valid_theme_name(theme_data.get('name', ''))
                if not is_valid_name:
                    log_system_event(
                        f"Theme upload failed - invalid name '{theme_data.get('name', '')}': {name_error}",
                        event_type='themes',
                        event_level='warning'
                    )
                    flash(f"Upload failed: {name_error}", 'error')
                    return redirect(url_for('admin2.manage_themes'))
                
                log_system_event(
                    f"Theme '{theme_data['name']}' uploaded successfully by admin",
                    event_type='themes',
                    event_level='information'
                )
                flash(f"Theme '{theme_data['name']}' uploaded successfully!", 'success')
            else:
                log_system_event(
                    "Theme upload failed - no theme data returned",
                    event_type='themes',
                    event_level='error'
                )
                flash("Theme upload failed. Please check the error messages.", 'error')
        except ValueError as e:
            log_system_event(
                f"Theme upload failed with ValueError: {e}",
                event_type='themes',
                event_level='warning'
            )
            flash(str(e), 'error')
        except Exception as e:
            log_system_event(
                f"Theme upload failed with unexpected error: {e}",
                event_type='themes',
                event_level='error'
            )
            flash(f"An unexpected error occurred: {str(e)}", 'error')
        return redirect(url_for('admin2.manage_themes'))

    if form.errors:
        flash('Please choose a valid theme archive and try again.', 'error')
    return redirect(url_for('admin2.manage_themes'))

@admin2_bp.route('/admin/themes/readme')
@login_required
@admin_required
def theme_readme():
    """Display theme documentation and readme information.
    
    Returns:
        Response: Rendered template with theme documentation
    """
    return render_admin_spa(title='Theme authoring guide · Oneirodex Admin')

@admin2_bp.route('/admin/themes/delete/<theme_name>', methods=['POST'])
@login_required
@admin_required
def delete_theme(theme_name: str):
    """Delete a theme from the system.
    
    Args:
        theme_name: Name of the theme to delete
        
    Returns:
        Response: Redirect to themes management page
    """
    theme_manager = ThemeManager(current_app)
    
    # Validate theme name before deletion
    is_valid_name, name_error = is_valid_theme_name(theme_name)
    if not is_valid_name:
        log_system_event(
            f"Theme deletion failed - invalid name '{theme_name}': {name_error}",
            event_type='themes',
            event_level='warning'
        )
        flash(f"Deletion failed: {name_error}", 'error')
        return redirect(url_for('admin2.manage_themes'))
    
    try:
        theme_manager.delete_themefile(theme_name)
        log_system_event(
            f"Theme '{theme_name}' deleted successfully by admin",
            event_type='themes',
            event_level='information'
        )
        flash(f"Theme '{theme_name}' deleted successfully!", 'success')
    except ValueError as e:
        log_system_event(
            f"Theme deletion failed with ValueError: {e}",
            event_type='themes',
            event_level='warning'
        )
        flash(str(e), 'error')
    except Exception as e:
        log_system_event(
            f"Theme deletion failed with unexpected error: {e}",
            event_type='themes',
            event_level='error'
        )
        flash(f"An unexpected error occurred: {str(e)}", 'error')
    return redirect(url_for('admin2.manage_themes'))

def perform_default_theme_reset() -> tuple[bool, str]:
    """Reset default assets and presets; shared by classic and native routes."""
    from oneirodex.utils.theme_reset import reset_default_theme_assets

    return reset_default_theme_assets(
        current_app.root_path,
        audit_user_id=getattr(current_user, 'id', None),
        logger=current_app.logger,
    )


@admin2_bp.route('/admin/themes/reset', methods=['POST'])
@login_required
@admin_required
def reset_default_themes():
    """Reset bundled theme assets while retaining custom installed themes."""
    ok, message = perform_default_theme_reset()
    flash(message, 'success' if ok else 'error')
    if request.is_json:
        if ok:
            return api_ok({'status': 'reset', 'message': message})
        return api_error('Default theme reset failed. Please try again.', code='internal')
    return redirect(url_for('admin2.manage_themes'))


# POST /admin/themes/apply is retired (W28). It set the calling admin's own
# theme preference — the same write Preferences performs, from a second swatch
# grid on this page, so the two surfaces could disagree about what was selected.
# Preferences builds its choices from get_installed_themes(), so it already
# covers uploaded packs as well as presets and nothing was lost by removing this.
# The grid and its fetch() went with it; this page keeps upload, reset and delete.
