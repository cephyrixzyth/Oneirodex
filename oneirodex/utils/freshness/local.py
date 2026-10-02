"""Local version / DLC hints from name, NFO, and on-disk files."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from oneirodex.utils.security import open_plain_file_within

VERSION_PATTERNS = [
    re.compile(r'(?i)\bv(\d+(?:\.\d+){1,3})\b'),
    re.compile(r'(?i)(?:^|[_\s.-])(\d+\.\d+(?:\.\d+){0,2})(?:[_\s.-]|$)'),
    re.compile(r'(?i)build[:\s_-]*(\d+)'),
]
DLC_COUNT_RE = re.compile(r'(?i)\+(\d+)\s*DLCs?')
VERSION_FILE_NAMES = (
    'version.txt',
    'version',
    'VERSION',
    'build.txt',
    'Build.txt',
    'product_version.txt',
)
#: A version file is a line or two; never read more of a share-writable file.
_VERSION_FILE_MAX_BYTES = 4096


def _first_version(text: str | None) -> str | None:
    if not text:
        return None
    for pattern in VERSION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _folder_mtime(path: str | None) -> str | None:
    if not path or not os.path.isdir(path):
        return None
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _resolved_game_folder(folder: str) -> str | None:
    """The game folder resolved once, or None when it is outside every library.

    Resolving once and comparing against that fixed string means a folder
    swapped for a link mid-check reads as outside, not as the link's target.
    Without an app context (tools, tests) there are no library bases to check.
    """
    real = os.path.realpath(folder)
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            from oneirodex.utils.security import get_allowed_base_directories, is_safe_path

            bases = get_allowed_base_directories(current_app)
            if bases and not is_safe_path(real, bases)[0]:
                return None
    except Exception:  # noqa: BLE001 -- a freshness hint must never break a scan
        return None
    return real


def _read_version_file(folder: str) -> tuple[str | None, str | None]:
    folder = _resolved_game_folder(folder)
    if folder is None:
        return None, None
    for name in VERSION_FILE_NAMES:
        path = os.path.join(folder, name)
        try:
            # The text becomes Game.local_version and the freshness payload,
            # which every member can read, so ``version.txt -> /run/secrets/x``
            # in a game folder must not be followed. The check runs on the
            # opened descriptor (see open_plain_file_within); a link, a FIFO,
            # a missing file or anything outside the folder is "no version
            # file", not an error.
            with open_plain_file_within(folder, path, base_is_resolved=True) as handle:
                content = handle.read(_VERSION_FILE_MAX_BYTES).decode('utf-8', errors='ignore')
        except OSError:
            continue
        lines = content.strip().splitlines()
        version = _first_version(content) or (lines[0].strip()[:80] if lines else '')
        if version:
            return version, name
    return None, None


def _scan_update_dlc_hints(game) -> list[str]:
    hints = []
    for update in getattr(game, 'updates', None) or []:
        path = getattr(update, 'file_path', '') or ''
        base = os.path.basename(path.rstrip('\\/'))
        if base:
            hints.append(base)
        nfo = getattr(update, 'nfo_content', None)
        if nfo:
            hints.append(nfo[:200])
    for extra in getattr(game, 'extras', None) or []:
        path = getattr(extra, 'file_path', '') or ''
        base = os.path.basename(path.rstrip('\\/')).lower()
        if 'dlc' in base:
            hints.append(os.path.basename(path.rstrip('\\/')))
    return hints


def detect_local_facts(game) -> dict:
    """Collect local version / DLC facts without network I/O."""
    name = getattr(game, 'name', None) or ''
    path = getattr(game, 'full_disk_path', None) or ''
    folder_label = os.path.basename(path.rstrip('\\/')) if path else ''
    nfo = getattr(game, 'nfo_content', None) or ''

    sources_tried = []
    version = None
    source = None

    for label, text in (
        ('folder_name', folder_label),
        ('game_name', name),
        ('nfo', nfo),
    ):
        sources_tried.append(label)
        found = _first_version(text)
        if found:
            version = found
            source = label
            break

    version_file = None
    if path and os.path.isdir(path):
        file_ver, file_name = _read_version_file(path)
        sources_tried.append('version_file')
        if file_ver and not version:
            version = file_ver
            source = 'version_file'
            version_file = file_name
        elif file_ver:
            version_file = file_name

    dlc_count = None
    for text in (folder_label, name, nfo):
        match = DLC_COUNT_RE.search(text or '')
        if match:
            dlc_count = int(match.group(1))
            break

    update_hints = _scan_update_dlc_hints(game)

    return {
        'version': version,
        'source': source,
        'version_file': version_file,
        'dlc_count_hint': dlc_count,
        'update_hints': update_hints[:20],
        'folder_mtime': _folder_mtime(path),
        'path': path or None,
        'sources_tried': sources_tried,
    }
