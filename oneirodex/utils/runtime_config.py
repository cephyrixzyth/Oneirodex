"""Runtime configuration lookup with a framework-free native fast path."""
from __future__ import annotations

from oneirodex.runtime_native.runtime_context import get_runtime_config as _native_config


def get_runtime_config():
    """Return the active native config or the legacy Flask app config."""
    config = _native_config()
    if config is not None:
        return config
    try:
        from flask import current_app

        return current_app.config
    except (ImportError, RuntimeError):
        return None


__all__ = ['get_runtime_config']
