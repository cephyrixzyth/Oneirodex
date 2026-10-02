from flask import render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from oneirodex import db
from oneirodex.models import UserPreference
from oneirodex.utils.auth import admin_required
from oneirodex.forms import ThemeUploadForm
from oneirodex.utils.themes import ThemeManager
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.preset_themes import install_preset_themes
from oneirodex.routes_theme import clear_theme_asset_versions
from oneirodex.utils.icon_themes import get_icon_pack
import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional, Union
from . import admin2_bp
from oneirodex.utils.library_paths import library_dir

# Configuration constants
MAX_THEME_FILE_SIZE = 25 * 1024 * 1024  # 25MB in bytes
ZIP_MAGIC_BYTES = [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08']  # Standard ZIP file signatures
WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
}

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


def validate_theme_file(file) -> tuple[bool, Optional[str]]:
    """Validate uploaded theme file for security and format requirements.
    
    Args:
        file: Uploaded file object from form
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not file or not file.filename:
        return False, "No file provided"
    
    # Check file size
    file.seek(0, 2)  # Seek to end
    file_size = file.tell()
    file.seek(0)  # Reset to beginning
    
    if file_size > MAX_THEME_FILE_SIZE:
        return False, f"File size ({file_size / (1024*1024):.1f}MB) exceeds maximum allowed size (25MB)"
    
    if file_size == 0:
        return False, "File is empty"
    
    # Check magic bytes for ZIP file
    file_header = file.read(4)
    file.seek(0)  # Reset to beginning
    
    if not any(file_header.startswith(magic) for magic in ZIP_MAGIC_BYTES):
        return False, "File is not a valid ZIP archive"
    
    return True, None


def is_valid_theme_name(name: str) -> tuple[bool, Optional[str]]:
    """Check if theme name is valid and safe to use.
    
    Args:
        name: Theme name to validate
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Theme name cannot be empty"
    
    # Check for Windows reserved names
    name_upper = name.upper()
    if name_upper in WINDOWS_RESERVED_NAMES:
        return False, f"'{name}' is a reserved system name and cannot be used"
    
    # Check for reserved names with extensions
    if '.' in name_upper:
        base_name = name_upper.split('.')[0]
        if base_name in WINDOWS_RESERVED_NAMES:
            return False, f"'{name}' uses a reserved system name and cannot be used"
    
    # Check for dangerous characters
    dangerous_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/']
    if any(char in name for char in dangerous_chars):
        return False, f"Theme name contains invalid characters: {', '.join(char for char in dangerous_chars if char in name)}"
    
    # Check for path traversal attempts  
    if '..' in name or (name.startswith('.') and name != '.') or name.endswith('.'):
        return False, "Theme name contains invalid path elements"
    
    return True, None


@admin2_bp.route('/admin/themes', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_themes():
    """Manage themes - upload, list, and configure themes.
    
    Returns:
        Response: Rendered template or redirect
    """
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

    installed_themes = theme_manager.get_installed_themes()
    default_theme = theme_manager.get_default_theme()
    return render_template('admin/admin_manage_themes.html', form=form, themes=installed_themes, default_theme=default_theme)

@admin2_bp.route('/admin/themes/readme')
@login_required
@admin_required
def theme_readme():
    """Display theme documentation and readme information.
    
    Returns:
        Response: Rendered template with theme documentation
    """
    return render_template('admin/admin_manage_themes_readme.html')

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

@admin2_bp.route('/admin/themes/reset', methods=['POST'])
@login_required
@admin_required
def reset_default_themes():
    """Reset themes to default by copying from source directory.

    Returns:
        Response: Redirect to themes management page
    """
    try:
        # Resolve against the app package root — not process CWD (Docker/uvicorn).
        app_root = Path(current_app.root_path)
        default_theme_source = app_root / 'setup' / 'default_theme'
        if not default_theme_source.exists():
            error_msg = "Failed to reset default themes: source directory not found"
            flash('Error: default theme source not found in oneirodex/setup/default_theme', 'error')
            log_system_event(
                error_msg,
                event_type='themes',
                event_level='error'
            )
            return redirect(url_for('admin2.manage_themes'))

        default_theme_target = Path(library_dir(app_root)) / 'themes' / 'default'

        log_system_event(
            "Starting default themes reset...",
            event_type='themes',
            event_level='information'
        )

        # Remove existing default theme if it exists
        if default_theme_target.exists():
            try:
                shutil.rmtree(default_theme_target)
                log_system_event(
                    "Removed existing default theme directory",
                    event_type='themes',
                    event_level='information'
                )
            except Exception as e:
                error_message = f"Failed to remove existing default theme: {str(e)}"
                flash(error_message, 'error')
                log_system_event(error_message, event_type='themes', event_level='error')
                return redirect(url_for('admin2.manage_themes'))

        # Create themes directory if it doesn't exist
        default_theme_target.parent.mkdir(parents=True, exist_ok=True)

        # Copy default theme from source and (re)install color presets
        try:
            shutil.copytree(default_theme_source, default_theme_target)
            themes_root = default_theme_target.parent
            presets = install_preset_themes(
                str(themes_root),
                str(default_theme_source),
                force=True,
            )
            # The files on disk are new; the URLs pointing at them are not until
            # this runs. Without it the reset succeeds server-side and the
            # browser keeps serving the previous stylesheet for up to an hour,
            # which is precisely how a working reset came to look broken.
            clear_theme_asset_versions()
            log_system_event(
                f"Default theme reset; installed {presets} preset theme(s)",
                event_type='themes',
                event_level='information'
            )
            flash(
                f'Default theme reset and {presets} preset themes installed. '
                'Pick a theme under Preferences.',
                'success',
            )
        except Exception as e:
            error_message = f"Failed to copy default theme: {str(e)}"
            flash(error_message, 'error')
            log_system_event(error_message, event_type='themes', event_level='error')

    except Exception as e:
        error_message = f"Error resetting default themes: {str(e)}"
        flash(error_message, 'error')
        log_system_event(error_message, event_type='themes', event_level='error')

    return redirect(url_for('admin2.manage_themes'))



# POST /admin/themes/apply is retired (W28). It set the calling admin's own
# theme preference — the same write Preferences performs, from a second swatch
# grid on this page, so the two surfaces could disagree about what was selected.
# Preferences builds its choices from get_installed_themes(), so it already
# covers uploaded packs as well as presets and nothing was lost by removing this.
# The grid and its fetch() went with it; this page keeps upload, reset and delete.
