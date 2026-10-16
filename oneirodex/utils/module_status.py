"""Settings-hub module On/Off status for optional admin features.

Arr and AI honor env OR GlobalSettings DB toggles. Hardlink helpers are
env-only safety gates — the hub still surfaces their status so admins can
see why Apply is disabled without opening the page.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from oneirodex.models import GlobalSettings
from oneirodex.runtime_native.db_session import native_db


def env_flag(name: str, default: str = '', *, config=None) -> bool:
    if config is None:
        try:
            from flask import current_app

            app_config = current_app.config
        except (ImportError, RuntimeError):
            from oneirodex.runtime_native.app_config import build_runtime_config

            app_config = build_runtime_config()
    else:
        app_config = config
    return str(app_config.get(name, default)).lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


def _global_settings() -> GlobalSettings | None:
    return native_db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def ensure_global_settings() -> GlobalSettings:
    row = _global_settings()
    if row is None:
        row = GlobalSettings()
        native_db.session.add(row)
        native_db.session.flush()
    return row


def arr_db_enabled() -> bool:
    settings = _global_settings()
    return bool(getattr(settings, 'enable_arr_module', False)) if settings else False


def arr_module_on(*, config=None) -> bool:
    return env_flag('ENABLE_ARR_MODULE', config=config) or arr_db_enabled()


def ai_db_enabled() -> bool:
    settings = _global_settings()
    return bool(getattr(settings, 'enable_ai_assist', False)) if settings else False


def ai_module_on(*, config=None) -> bool:
    from oneirodex.utils.ai_assist import ai_enabled

    return ai_enabled(config=config)


def hardlink_helpers_on(*, config=None) -> bool:
    return env_flag('ENABLE_HARDLINK_HELPERS', config=config)


def hardlink_apply_on(*, config=None) -> bool:
    return hardlink_helpers_on(config=config) and env_flag(
        'ALLOW_HARDLINK_APPLY', config=config,
    )


def settings_hub_module_status(*, config=None) -> dict[str, dict[str, Any]]:
    """Badge payload for settings-shell cards keyed by section id."""
    arr_on = arr_module_on(config=config)
    ai_on = ai_module_on(config=config)
    helpers_on = hardlink_helpers_on(config=config)
    apply_on = hardlink_apply_on(config=config)

    storage: dict[str, Any] = {
        'on': helpers_on,
        'label': 'On' if helpers_on else 'Off',
    }
    if helpers_on and not apply_on:
        storage['detail'] = 'Apply off'

    return {
        'arr': {'on': arr_on, 'label': 'On' if arr_on else 'Off'},
        'ai': {'on': ai_on, 'label': 'On' if ai_on else 'Off'},
        'storage': storage,
    }
