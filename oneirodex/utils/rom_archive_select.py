"""Choosing the ROM member inside an archive: name / extension / platform
heuristics, cue-sheet companions and the browser-extract eligibility check.

Split out of ``rom_archive`` in the v11 cycle (H-D.4) as a pure move.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from oneirodex.utils.rom_archive_types import CUE_COMPANION_EXTENSIONS
from oneirodex.utils.rom_archive_types import ROM_EXTENSIONS
from oneirodex.utils.rom_archive_types import ArchiveRomError
from oneirodex.utils.rom_archive_types import PLATFORM_ROM_EXTENSIONS
from oneirodex.utils.rom_archive_types import MIN_ROM_BYTES_PREFERRED
from oneirodex.utils.rom_archive_types import UNSUPPORTED_ARCHIVE_EXTENSIONS
from oneirodex.utils.rom_archive_types import ARCHIVE_EXTENSIONS
from oneirodex.utils.rom_archive_types import GZIP_EXTENSIONS


def _cue_companion_targets(
    members: list[tuple[str, int]],
    chosen: str,
) -> list[str]:
    targets = [chosen]
    if _member_ext(chosen) != '.cue':
        return targets
    folder = str(Path(chosen).parent).replace('\\', '/')
    if folder == '.':
        folder = ''
    prefix = f'{folder}/' if folder else ''
    for name, _ in members:
        if name == chosen or _member_ext(name) not in CUE_COMPANION_EXTENSIONS:
            continue
        norm = name.replace('\\', '/')
        if folder and not norm.startswith(prefix):
            continue
        if folder:
            rest = norm[len(prefix):]
            if '/' in rest:
                continue
        targets.append(name)
    return targets


def _is_rom_name(name: str) -> bool:
    lower = Path(name).name.lower()
    return any(lower.endswith(ext) for ext in ROM_EXTENSIONS)


def _member_ext(name: str) -> str:
    return Path(name).suffix.lower()


def _safe_basename(member: str) -> str:
    safe_name = Path(member).name
    if not safe_name or safe_name in ('.', '..'):
        raise ArchiveRomError(
            'Invalid ROM member name in archive',
            code='invalid_member',
        )
    return safe_name


_DRIVE_PREFIX_RE = re.compile(r'^[A-Za-z]:')


def _safe_member_name(name: str | None) -> str | None:
    """Return *name* with ``/`` separators, or None if it could leave the extract dir.

    Archive member names are attacker-controlled. The 7z / bsdtar listing paths
    used to hand them on verbatim, and the extract code then joined them onto the
    ROM cache directory, so ``../../lib/victim.nes`` named a file *outside* the
    cache that the flatten step would move into place (and a later serve or
    cleanup would touch). A member is refused here, at list time, when its
    normalised path is absolute, names a drive, is a UNC path, or has a ``..``
    segment -- including the padded forms (``.. ``, ``...``) Windows folds back
    into ``..``.
    """
    if not name or '\x00' in name:
        return None
    norm = name.replace('\\', '/')
    if norm.startswith('/') or _DRIVE_PREFIX_RE.match(norm):
        return None
    for segment in norm.split('/'):
        if segment in ('', '.'):
            continue
        if not segment.rstrip(' .'):
            return None
    return norm


def _platform_key(platform: str | None) -> str | None:
    if not platform:
        return None
    text = str(platform).strip()
    if not text:
        return None
    # Accept enum .name or raw key.
    return text.upper().replace(' ', '_') if text.islower() else text


def choose_rom_member(
    members: list[tuple[str, int]],
    *,
    platform: str | None = None,
    preferred_member: str | None = None,
) -> str:
    """
    Pick the best ROM member from (name, size) pairs.

    Prefer: explicit member → platform-matching extension → .cue over lone .bin →
    larger size → shallower path. Tiny junk files are demoted when larger ROMs exist.
    """
    if not members:
        raise ArchiveRomError(
            'No playable ROM files found inside archive',
            code='no_playable_member',
            hint='Archive should contain a ROM with a known extension (e.g. .nes, .sfc, .gba).',
        )

    names = {name for name, _ in members}
    if preferred_member and preferred_member in names:
        return preferred_member

    preferred_exts = PLATFORM_ROM_EXTENSIONS.get(_platform_key(platform) or '', frozenset())
    has_cue = any(_member_ext(name) == '.cue' for name, _ in members)

    scored: list[tuple[float, str]] = []
    for name, size in members:
        ext = _member_ext(name)
        score = float(max(size, 0))
        if preferred_exts and ext in preferred_exts:
            score += 1e12
        if ext == '.cue':
            score += 1e9
        if has_cue and ext == '.bin':
            # WebRetro / disc cores usually want the cue sheet, not a raw track dump.
            score -= 1e8
        if size < MIN_ROM_BYTES_PREFERRED and any(s >= MIN_ROM_BYTES_PREFERRED for _, s in members):
            score -= 1e6
        depth = name.count('/') + name.count('\\')
        score -= depth * 1000
        # Stable tie-break: lexicographic name (negative so reverse sort still prefers A before Z).
        scored.append((score, name))

    scored.sort(key=lambda item: (-item[0], item[1].lower()))
    return scored[0][1]


def path_supports_browser_extract(source_path: str | None) -> bool:
    """
    Whether browse play_url may advertise browser play for this on-disk path.

    Returns True when unknown/empty (keep existing browse behavior) or when the
    resolver can attempt extract/stream. Returns False for formats we will never
    extract for WebRetro (e.g. bare .tar / non-ROM .gz). Existence is not required.
    """
    if not source_path:
        return True
    path = os.path.abspath(source_path)
    if os.path.isdir(path):
        return True

    ext = Path(path).suffix.lower()
    if ext in UNSUPPORTED_ARCHIVE_EXTENSIONS:
        return False
    if ext in ARCHIVE_EXTENSIONS:
        return True
    if ext in GZIP_EXTENSIONS:
        return _is_rom_name(Path(path).stem)
    if _is_rom_name(Path(path).name):
        return True
    # Unknown extension — leave browse decision to platform/cores.
    return True
