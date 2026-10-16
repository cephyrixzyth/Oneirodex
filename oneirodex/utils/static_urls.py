"""Build static asset paths in native ASGI and legacy Flask request scopes."""
from __future__ import annotations

from urllib.parse import quote

from oneirodex.runtime_native.runtime_context import get_runtime_config as _native_config


def static_asset_url(filename: str) -> str:
    """Return the configured static URL, preserving Flask's mounted-root path."""
    config = _native_config()
    if config is None:
        try:
            from flask import has_app_context, url_for

            if has_app_context():
                return url_for('static', filename=filename)
        except ImportError:
            pass
        try:
            from oneirodex.utils.runtime_config import get_runtime_config

            config = get_runtime_config()
        except ImportError:
            config = None
    config = config or {}
    root = str(config.get('APPLICATION_ROOT') or '').rstrip('/')
    static_path = str(config.get('STATIC_URL_PATH') or '/static').rstrip('/')
    encoded = quote(str(filename).lstrip('/'), safe='/')
    return f'{root}{static_path}/{encoded}' or '/'


__all__ = ['static_asset_url']
