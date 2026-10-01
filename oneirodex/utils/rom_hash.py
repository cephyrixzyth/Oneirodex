"""Hash ROM files for DAT set-completion matching (CRC32 / MD5 / SHA1)."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zlib
from pathlib import Path
from typing import BinaryIO

from oneirodex.utils.rom_archive import ARCHIVE_EXTENSIONS, PLATFORM_DUMP_SUFFIXES
from oneirodex.utils.security import is_plain_file_within

# Prefer single-file ROM dumps when a library path is a folder.
_ROM_SUFFIXES = frozenset({
    '.nes', '.sfc', '.smc', '.n64', '.z64', '.v64', '.gb', '.gbc', '.gba', '.nds',
    '.3ds', '.cia', '.md', '.smd', '.gen', '.sms', '.gg', '.32x', '.pce', '.ngp',
    '.ws', '.wsc', '.a26', '.a52', '.a78', '.lnx', '.col', '.int',
    '.iso', '.gcm', '.rvz', '.wbfs', '.wad', '.cue', '.chd', '.bin', '.img',
    '.pbp', '.cso', '.gdi', '.cdi', '.rom', '.nsp', '.xci', '.nsz', '.xcz',
    '.min', '.wud', '.wux', '.wua', '.tzx', '.z80', '.mx1', '.mx2', '.cas', '.sna',
    '.dsk', '.st', '.stx', '.tap',
    '.atr', '.xfd', '.atx', '.xex', '.dim', '.xdf', '.hdm',
    '.fdi', '.hdi', '.nhd', '.d88',
    '.sg', '.sgx', '.sv', '.cpr', '.int', '.chf', '.adf', '.ipf',
    '.d64', '.prg', '.crt',
    '.zip', '.7z', '.rar',
}) | PLATFORM_DUMP_SUFFIXES | ARCHIVE_EXTENSIONS

# Cap inner-archive hashing so multicart / MAME set zips stay cheap and honest.
MAX_INNER_HASH_MEMBERS = 8


def resolve_hashable_file(path: str | Path) -> Path | None:
    """Return a single file to hash, or None for multi-file / missing paths."""
    root = Path(path) if path else None
    if root is None:
        return None
    try:
        if root.is_file():
            return root
        if not root.is_dir():
            return None
    except OSError:
        return None

    candidates: list[Path] = []
    try:
        for child in root.iterdir():
            # A link inside the folder is not the game: hashing it would read
            # (and store a digest of) whatever it points at, wherever that is.
            if is_plain_file_within(root, child) and child.suffix.lower() in _ROM_SUFFIXES:
                candidates.append(child)
    except OSError:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return None


def hash_fileobj(handle: BinaryIO, *, chunk_size: int = 1024 * 1024) -> dict[str, str]:
    """Return lowercase hex crc/md5/sha1 for an open binary stream."""
    crc = 0
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    while True:
        chunk = handle.read(chunk_size)
        if not chunk:
            break
        crc = zlib.crc32(chunk, crc)
        md5.update(chunk)
        sha1.update(chunk)
    return {
        'crc': f'{crc & 0xffffffff:08x}',
        'md5': md5.hexdigest(),
        'sha1': sha1.hexdigest(),
    }


def hash_rom_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> dict[str, str] | None:
    """Return lowercase hex crc/md5/sha1 for a ROM file path, or None if unhashable."""
    target = resolve_hashable_file(path)
    if target is None:
        return None
    try:
        with target.open('rb') as handle:
            return hash_fileobj(handle, chunk_size=chunk_size)
    except OSError:
        return None


def apply_file_hashes_to_game(game, path: str | None = None) -> bool:
    """Hash ``path`` (or ``game.full_disk_path``) onto the game model. Returns True if set."""
    disk = path if path is not None else getattr(game, 'full_disk_path', None)
    hashes = hash_rom_file(disk) if disk else None
    if not hashes:
        return False
    game.file_crc = hashes['crc']
    game.file_md5 = hashes['md5']
    game.file_sha1 = hashes['sha1']
    return True


def _dat_hash_inner_archive_enabled() -> bool:
    """Default ON — set ``DAT_HASH_INNER_ARCHIVE=0`` to skip open-on-miss."""
    raw = os.getenv('DAT_HASH_INNER_ARCHIVE')
    if raw is None or raw == '':
        try:
            from flask import current_app, has_app_context

            if has_app_context():
                return bool(current_app.config.get('DAT_HASH_INNER_ARCHIVE', True))
        except Exception:
            pass
        return True
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _select_inner_hash_members(
    members: list[tuple[str, int]],
    *,
    platform: str | None,
) -> list[str] | None:
    """
    Choose inner ROM member names to hash for DAT identify.

    Returns None when the archive is too crowded to hash safely (skip).
    """
    if not members:
        return []

    from oneirodex.utils.rom_archive import PLATFORM_ROM_EXTENSIONS, choose_rom_member

    preferred_exts = PLATFORM_ROM_EXTENSIONS.get((platform or '').strip().upper(), frozenset())
    filtered = members
    if preferred_exts:
        platform_members = [
            (name, size)
            for name, size in members
            if Path(name).suffix.lower() in preferred_exts
        ]
        if platform_members:
            filtered = platform_members

    if len(filtered) > MAX_INNER_HASH_MEMBERS:
        return None

    if len(filtered) == 1:
        return [filtered[0][0]]

    # Multiple candidates — hash each so distinct DAT titles can abort (no invent).
    # Still prefer choose_rom_member order so primary is first when only one hits.
    primary = choose_rom_member(filtered, platform=platform)
    ordered = [primary]
    for name, _ in sorted(filtered, key=lambda item: (-item[1], item[0].lower())):
        if name not in ordered:
            ordered.append(name)
    return ordered


def _hash_zip_member(archive_path: str, member: str) -> dict[str, str] | None:
    import zipfile

    try:
        with zipfile.ZipFile(archive_path, 'r') as archive:
            with archive.open(member) as handle:
                return hash_fileobj(handle)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def _hash_extracted_member(
    archive_path: str,
    member: str,
    *,
    platform: str | None,
) -> dict[str, str] | None:
    """Extract one member via play helpers into a temp dir, hash, cleanup."""
    from oneirodex.utils.rom_archive import (
        ArchiveRomError,
        extract_rom_from_7z,
        extract_rom_from_rar,
        extract_rom_from_zip,
    )

    ext = Path(archive_path).suffix.lower()
    try:
        with tempfile.TemporaryDirectory(prefix='od-dat-inner-') as tmp:
            if ext == '.zip':
                dest = extract_rom_from_zip(
                    archive_path, tmp, member=member, platform=platform,
                )
            elif ext == '.7z':
                dest = extract_rom_from_7z(
                    archive_path, tmp, member=member, platform=platform,
                )
            elif ext == '.rar':
                dest = extract_rom_from_rar(
                    archive_path, tmp, member=member, platform=platform,
                )
            else:
                return None
            # Whatever the extractor reports, only hash a real file that sits
            # inside the scratch directory we gave it.
            if not is_plain_file_within(tmp, dest):
                return None
            try:
                with open(dest, 'rb') as handle:
                    return hash_fileobj(handle)
            except OSError:
                return None
    except ArchiveRomError:
        return None


def hash_archive_inner_primary_dumps(
    path: str | Path,
    *,
    platform: str | None = None,
) -> list[dict[str, str]]:
    """
    Hash primary ROM dump candidate(s) inside a zip/7z/rar for DAT unique-hash.

    Returns digests for each candidate (may be empty). Non-archives, unreadable
    archives, empty ROM lists, and overcrowded archives (>``MAX_INNER_HASH_MEMBERS``)
    return []. Does not invent matches — caller decides unique vs ambiguous.
    """
    if not _dat_hash_inner_archive_enabled():
        return []

    from oneirodex.utils.rom_archive import (
        ArchiveRomError,
        list_roms_in_archive,
        path_is_supported_archive,
    )

    root = Path(path) if path else None
    if root is None or not path_is_supported_archive(root):
        return []
    try:
        if not root.is_file():
            return []
    except OSError:
        return []

    try:
        members = list_roms_in_archive(str(root))
    except ArchiveRomError:
        return []

    selected = _select_inner_hash_members(members, platform=platform)
    if not selected:
        return []

    digests: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    ext = root.suffix.lower()
    for member in selected:
        if ext == '.zip':
            digest = _hash_zip_member(str(root), member)
        else:
            digest = _hash_extracted_member(str(root), member, platform=platform)
        if not digest:
            continue
        key = (digest['crc'], digest['md5'], digest['sha1'])
        if key in seen:
            continue
        seen.add(key)
        digests.append(digest)
    return digests
