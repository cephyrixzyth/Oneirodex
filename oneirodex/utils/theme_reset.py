"""Shared filesystem operation for restoring the shipped default theme."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path


def reset_default_theme_assets(app_root, *, audit_user_id=None, logger=None) -> tuple[bool, str]:
    """Restore shipped default theme assets using explicit paths and audit identity."""
    from oneirodex.utils.asset_version import clear_asset_versions
    from oneirodex.utils.event_logging import log_system_event
    from oneirodex.utils.library_paths import library_dir
    from oneirodex.utils.preset_themes import install_preset_themes

    log = logger or logging.getLogger(__name__)
    app_root = Path(app_root)
    source = app_root / 'setup' / 'default_theme'
    if not source.exists():
        log_system_event(
            'Failed to reset default themes: source directory not found',
            event_type='themes', event_level='error', audit_user=audit_user_id,
        )
        return False, 'Error: default theme source not found in oneirodex/setup/default_theme'

    target = Path(library_dir(app_root)) / 'themes' / 'default'
    try:
        if target.exists():
            try:
                shutil.rmtree(target)
            except Exception as exc:
                message = f'Failed to remove existing default theme: {exc}'
                log_system_event(message, event_type='themes', event_level='error',
                                 audit_user=audit_user_id)
                return False, message
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(source, target)
        except Exception as exc:
            message = f'Failed to copy default theme: {exc}'
            log_system_event(message, event_type='themes', event_level='error',
                             audit_user=audit_user_id)
            return False, message
        presets = install_preset_themes(str(target.parent), str(source), force=True)
        clear_asset_versions()
        log_system_event(
            f'Default theme reset; installed {presets} preset theme(s)',
            event_type='themes', event_level='information', audit_user=audit_user_id,
        )
        return True, (
            f'Default theme reset and {presets} preset themes installed. '
            'Pick a theme under Preferences.'
        )
    except Exception as exc:
        message = f'Error resetting default themes: {exc}'
        log.exception('Default theme reset failed')
        log_system_event(message, event_type='themes', event_level='error',
                         audit_user=audit_user_id)
        return False, message
