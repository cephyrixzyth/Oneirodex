"""Pure filesystem version tokens for cacheable application assets."""

from __future__ import annotations

from pathlib import Path


_ASSET_VERSIONS: dict[str, str] = {}


def clear_asset_versions() -> None:
    """Drop memoised asset versions after theme or bundle files are rewritten."""
    _ASSET_VERSIONS.clear()


def asset_version(fs_path: Path) -> str:
    key = str(fs_path)
    cached = _ASSET_VERSIONS.get(key)
    if cached is not None:
        return cached
    try:
        stat = fs_path.stat()
        token = f'{int(stat.st_mtime)}-{stat.st_size}'
    except OSError:
        token = '0'
    _ASSET_VERSIONS[key] = token
    return token
