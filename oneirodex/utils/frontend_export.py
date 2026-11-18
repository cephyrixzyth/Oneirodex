"""ES-DE gamelist.xml + Pegasus metadata.pegasus.txt export builders."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable
from xml.etree.ElementTree import Element, SubElement, tostring


def _safe_text(value: Any) -> str:
    return str(value or '').strip()


def _pegasus_escape(value: str) -> str:
    return value.replace('\n', ' ').replace('\r', '')


def _looks_absolute(path: str) -> bool:
    if not path:
        return False
    if path.startswith(('/', '\\')):
        return True
    # Windows drive letter (C:\… or C:/…)
    if len(path) >= 3 and path[1] == ':' and path[0].isalpha() and path[2] in '\\/':
        return True
    # UNC \\server\share
    if path.startswith('\\\\'):
        return True
    return False


def portable_export_path(
    path: str,
    *,
    library_roots: Iterable[str] | None = None,
) -> str:
    """Strip server library roots for portable ES-DE / Pegasus exports.

    Prefers ``<library>/relative/path`` when the file sits under a configured
    root; otherwise falls back to the basename so exports never leak home /
    NAS mount prefixes.
    """
    raw = _safe_text(path)
    if not raw:
        return ''
    normalized = raw.replace('\\', '/')
    if normalized.startswith('./') or not _looks_absolute(raw):
        return normalized

    roots = [r for r in (library_roots or []) if r]
    for root in sorted(roots, key=lambda r: len(str(r)), reverse=True):
        root_s = str(root).strip().rstrip('/\\')
        if not root_s:
            continue
        # Fast string prefix match (handles mixed separators without requiring
        # the path to exist on the build host).
        root_norm = root_s.replace('\\', '/').rstrip('/')
        if normalized.lower().startswith(root_norm.lower() + '/') or normalized.lower() == root_norm.lower():
            rel = normalized[len(root_norm):].lstrip('/')
            return f'<library>/{rel}' if rel else '<library>'
        try:
            # Path.resolve only when both sides look real-ish (optional).
            if os.name == 'nt':
                candidate = PureWindowsPath(raw)
                base = PureWindowsPath(root_s)
            else:
                candidate = PurePosixPath(normalized)
                base = PurePosixPath(root_norm)
            rel = candidate.relative_to(base)
            return f'<library>/{PurePosixPath(rel).as_posix()}'
        except (ValueError, OSError, RuntimeError):
            continue

    # Unknown absolute path — basename only (ES-DE resolves against local ROMs).
    name = Path(normalized).name or Path(raw).name
    return name


def _export_path_from_row(row: dict[str, Any], *, library_roots: Iterable[str] | None = None) -> str:
    raw = _safe_text(row.get('path') or row.get('rom_path') or row.get('full_disk_path'))
    return portable_export_path(raw, library_roots=library_roots)


def build_es_de_gamelist(
    games: Iterable[dict[str, Any]],
    *,
    system: str = '',
    library_roots: Iterable[str] | None = None,
) -> bytes:
    """Build EmulationStation / ES-DE gamelist.xml bytes."""
    root = Element('gameList')
    if system:
        SubElement(root, 'provider').text = f'Oneirodex/{system}'
    for row in games:
        game_el = SubElement(root, 'game')
        name = _safe_text(row.get('name') or row.get('title') or 'Unknown')
        path = _export_path_from_row(row, library_roots=library_roots)
        SubElement(game_el, 'path').text = path or f'./{name}'
        SubElement(game_el, 'name').text = name
        if row.get('summary') or row.get('desc'):
            SubElement(game_el, 'desc').text = _safe_text(row.get('summary') or row.get('desc'))
        if row.get('cover_url') or row.get('image'):
            SubElement(game_el, 'image').text = _safe_text(row.get('cover_url') or row.get('image'))
        if row.get('releasedate') or row.get('first_release_date'):
            SubElement(game_el, 'releasedate').text = _safe_text(
                row.get('releasedate') or row.get('first_release_date'),
            )
        if row.get('developer'):
            SubElement(game_el, 'developer').text = _safe_text(row.get('developer'))
        if row.get('publisher'):
            SubElement(game_el, 'publisher').text = _safe_text(row.get('publisher'))
        if row.get('genre'):
            SubElement(game_el, 'genre').text = _safe_text(row.get('genre'))
        if row.get('uuid'):
            SubElement(game_el, 'id').text = _safe_text(row.get('uuid'))
    xml = tostring(root, encoding='utf-8', xml_declaration=True)
    # ES-DE prefers readable entities for & already handled by ElementTree
    return xml


def build_pegasus_metadata(
    games: Iterable[dict[str, Any]],
    *,
    collection: str,
    shortname: str | None = None,
    library_roots: Iterable[str] | None = None,
) -> str:
    """Build Pegasus Frontend metadata.pegasus.txt contents."""
    short = shortname or re.sub(r'[^a-z0-9]+', '', collection.lower()) or 'game'
    lines = [
        f'collection: {_pegasus_escape(collection)}',
        f'shortname: {short}',
        'extension: zip,7z,iso,chd,cue,bin,nes,sfc,smc,n64,z64,gba,gb,gbc,nds,pce,md,sms,gg',
        '',
    ]
    for row in games:
        name = _safe_text(row.get('name') or row.get('title') or 'Unknown')
        path = _export_path_from_row(row, library_roots=library_roots) or name
        lines.append(f'game: {_pegasus_escape(name)}')
        lines.append(f'file: {_pegasus_escape(path)}')
        if row.get('summary') or row.get('desc'):
            lines.append(f'description: {_pegasus_escape(_safe_text(row.get("summary") or row.get("desc")))}')
        if row.get('developer'):
            lines.append(f'developer: {_pegasus_escape(_safe_text(row.get("developer")))}')
        if row.get('publisher'):
            lines.append(f'publisher: {_pegasus_escape(_safe_text(row.get("publisher")))}')
        if row.get('genre'):
            lines.append(f'genre: {_pegasus_escape(_safe_text(row.get("genre")))}')
        if row.get('cover_url') or row.get('assets.boxFront'):
            art = _safe_text(row.get('cover_url') or row.get('assets.boxFront'))
            lines.append(f'assets.boxFront: {_pegasus_escape(art)}')
        lines.append('')
    return '\n'.join(lines)


