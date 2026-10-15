"""Public, lazily loaded application exports.

Importing pure helpers from ``oneirodex.*`` must not initialize Flask. The
legacy runtime remains available behind these exports while its routes and
persistence are migrated to FastAPI.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    'app_start_time',
    'app_version',
    'cache',
    'create_app',
    'csrf',
    'db',
    'login_manager',
]


def __getattr__(name: str) -> Any:
    """Load the compatibility runtime only for Flask-owned exports."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name in {'app_start_time', 'app_version'}:
        from oneirodex import runtime_info

        value = getattr(runtime_info, name)
        globals()[name] = value
        return value
    if name == 'cache':
        from oneirodex.utils.cache import cache

        globals()[name] = cache
        return cache
    legacy_app = import_module('.legacy_app', __name__)
    value = getattr(legacy_app, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
