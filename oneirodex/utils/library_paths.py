"""Where the app keeps the files it writes while running.

``oneirodex/static/library`` holds everything the server writes at runtime:
themes, icon packs, artwork, saves, fonts, feeds and caches. The Compose stack
mounts a volume there, and the native install writes into its own checkout.

A standalone install (ADR 0011) must not write inside its install folder, which
may be read-only (Program Files, a signed macOS bundle). ``ONEIRODEX_LIBRARY_DIR``
moves the whole area to the data folder. It is still served at ``/static/library/``.

A few files are written to shipped paths outside ``library/``: browser-play
cores fetched on boot and the Art Studio's fallback covers. When the library is
moved, those land in ``<library>/static-overrides/<same path>`` instead, and the
static handlers serve an override ahead of the shipped file.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from flask import current_app, has_app_context

LIBRARY_DIR_ENV = 'ONEIRODEX_LIBRARY_DIR'
STATIC_OVERRIDES = 'static-overrides'
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def relocated_library_dir() -> str | None:
    """The data-folder library when ``ONEIRODEX_LIBRARY_DIR`` is set, else None."""
    explicit = (os.environ.get(LIBRARY_DIR_ENV) or '').strip()
    return os.path.abspath(explicit) if explicit else None


def library_dir(package_root: str | Path | None = None) -> str:
    """The runtime library folder, served at ``/static/library/``.

    ``package_root`` names the ``oneirodex`` package folder to use when the
    library has not been moved (tests pass a temporary one). Without it the
    current app's ``root_path`` is used, then this package.
    """
    relocated = relocated_library_dir()
    if relocated:
        return relocated
    if package_root is None:
        package_root = current_app.root_path if has_app_context() else PACKAGE_ROOT
    return os.path.join(str(package_root), 'static', 'library')


def image_save_dir(upload_folder: str | Path) -> str:
    """Return the persistent image folder below the configured library root."""
    return os.path.join(str(upload_folder), 'images')


#: Folders the install ships inside ``static/library`` (git-tracked art). Only
#: these are copied into a moved library: a developer checkout keeps its own
#: runtime files in the same folder, and those must not be swept along.
SHIPPED_LIBRARY_FOLDERS = ('system-marks', 'stock')


def seed_shipped_library() -> int:
    """Copy shipped library files into a moved library, never overwriting.

    Without this a standalone install would 404 every system mark: URLs under
    ``/static/library/`` are served from the data folder only. Returns the
    number of files copied.
    """
    relocated = relocated_library_dir()
    shipped = PACKAGE_ROOT / 'static' / 'library'
    if not relocated or not shipped.is_dir() or Path(relocated).resolve() == shipped.resolve():
        return 0
    copied = 0
    for folder in SHIPPED_LIBRARY_FOLDERS:
        for src in sorted((shipped / folder).rglob('*')):
            if not src.is_file():
                continue
            dest = Path(relocated, src.relative_to(shipped))
            if dest.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
    return copied


def static_write_dir(*parts: str, package_root: str | Path | None = None) -> Path:
    """Where to write files served at ``/static/<parts>/`` outside ``library/``.

    The shipped static folder normally; ``<library>/static-overrides/<parts>``
    when the library has been moved out of the install folder.
    """
    relocated = relocated_library_dir()
    if relocated:
        return Path(relocated, STATIC_OVERRIDES, *parts)
    if package_root is None:
        package_root = current_app.root_path if has_app_context() else PACKAGE_ROOT
    return Path(str(package_root), 'static', *parts)
