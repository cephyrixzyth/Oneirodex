"""Framework-independent application configuration shared by ASGI and WSGI.

The FastAPI runtime and the remaining Flask compatibility app must agree on
environment parsing and persistent library paths. This module copies the
project's config class using Flask's uppercase-attribute convention without
importing Flask or constructing an application.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from oneirodex.utils.library_paths import image_save_dir, library_dir, PACKAGE_ROOT


def _default_config_object():
    if 'pytest' in sys.modules or 'PYTEST_CURRENT_TEST' in os.environ:
        from config import TestConfig

        return TestConfig
    from config import Config

    return Config


def build_runtime_config(
    config_object: Any = None,
    *,
    package_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return effective app settings without importing a web framework."""
    source = config_object if config_object is not None else _default_config_object()
    if isinstance(source, Mapping):
        config = {key: value for key, value in source.items() if str(key).isupper()}
    else:
        config = {
            key: getattr(source, key)
            for key in dir(source)
            if key.isupper()
        }

    root = Path(package_root) if package_root is not None else PACKAGE_ROOT
    upload_folder = library_dir(root)
    config['UPLOAD_FOLDER'] = upload_folder
    config['IMAGE_SAVE_PATH'] = image_save_dir(upload_folder)
    return config


__all__ = ['build_runtime_config']
