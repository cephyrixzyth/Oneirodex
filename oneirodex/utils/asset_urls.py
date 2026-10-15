"""Framework-independent URL helpers for versioned application/theme assets."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote

from oneirodex.utils.library_paths import PACKAGE_ROOT, library_dir
from oneirodex.utils.asset_version import asset_version, clear_asset_versions


def verify_file(full_path: str | os.PathLike[str]) -> bool:
    return os.path.exists(full_path) or os.access(full_path, os.R_OK)


def _static_url(filename: str, *, static_url_path: str | None, **query) -> str:
    if static_url_path is not None:
        url = f"{static_url_path.rstrip('/')}/{quote(filename.lstrip('/'), safe='/')}"
        if query:
            from urllib.parse import urlencode

            url += '?' + urlencode(query)
        return url
    if 'flask' in sys.modules:
        from flask import has_app_context, url_for

        if has_app_context():
            return url_for('static', filename=filename, **query)
    url = f"/static/{quote(filename.lstrip('/'), safe='/')}"
    if query:
        from urllib.parse import urlencode

        url += '?' + urlencode(query)
    return url


def _package_root() -> Path:
    if 'flask' in sys.modules:
        from flask import current_app, has_app_context

        if has_app_context():
            return Path(current_app.root_path)
    return PACKAGE_ROOT


def dist_asset_url(
    path: str, *, static_url_path: str | None = None,
    package_root: str | os.PathLike[str] | None = None,
) -> str:
    """Build a versioned static bundle URL, preserving JS module identity."""
    target = Path(package_root) if package_root is not None else _package_root()
    target = target / 'static' / 'dist' / path
    if target.suffix.lower() in ('.js', '.mjs'):
        return _static_url(f'dist/{path}', static_url_path=static_url_path)
    return _static_url(
        f'dist/{path}', static_url_path=static_url_path,
        v=asset_version(target),
    )


def theme_asset_url(
    path: str, *, theme: str | None = None,
    static_url_path: str | None = None,
    package_root: str | os.PathLike[str] | None = None,
) -> str:
    """Resolve an asset in the selected theme, falling back to the default."""
    if theme is None:
        if 'flask' in sys.modules:
            from flask import has_request_context
            from flask_login import current_user

            if has_request_context() and current_user.is_authenticated and hasattr(current_user, 'preferences') and current_user.preferences:
                from oneirodex.utils.preset_themes import canonical_theme_slug

                theme = canonical_theme_slug(current_user.preferences.theme)
        if theme is None:
            theme = 'default'

    root = Path(library_dir(package_root)) / 'themes'
    themed = root / theme / path
    if themed.is_file():
        return _static_url(
            f'library/themes/{theme}/{path}', static_url_path=static_url_path,
            v=asset_version(themed),
        )

    fallback = root / 'default' / path
    return _static_url(
        f'library/themes/default/{path}', static_url_path=static_url_path,
        v=asset_version(fallback),
    )
