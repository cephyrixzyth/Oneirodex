"""Resolve a playable ROM file path, including zip/7z/rar/gz archives for WebRetro.

The v11 cycle (H-D.4) moved the extension tables to ``rom_archive_types``,
member selection to ``rom_archive_select`` and the zip / gzip / bundle paths
to ``rom_archive_zip`` as pure moves. The 7z / rar extractor shims and
``resolve_playable_rom_path`` stay here; every name callers import still
resolves here.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path

# H-D.4 split: these moved to sibling modules as pure moves. Public names are
# re-exported here because callers and tests import them from this module.
logger = logging.getLogger(__name__)

from oneirodex.utils.rom_archive_select import (  # noqa: F401
    choose_rom_member,
    path_supports_browser_extract,
    _cue_companion_targets,
    _is_rom_name,
    _safe_basename,
    _safe_member_name,
)
from oneirodex.utils.rom_archive_types import (  # noqa: F401
    ARCHIVE_EXTENSIONS,
    ArchiveRomError,
    CUE_COMPANION_EXTENSIONS,
    GZIP_EXTENSIONS,
    MAX_NEST_DEPTH,
    MIN_ROM_BYTES_PREFERRED,
    RomExpansionBudget,
    PLATFORM_DUMP_SUFFIXES,
    PLATFORM_ROM_EXTENSIONS,
    ROM_EXTENSIONS,
    UNSUPPORTED_ARCHIVE_EXTENSIONS,
    _EXTRACTOR_BINARIES,
    _MISSING_EXTRACTOR_HINT,
)
from oneirodex.utils.rom_archive_zip import (  # noqa: F401
    bundle_playable_rom_zip,
    extract_rom_from_gz,
    extract_rom_from_zip,
    _list_roms_with_sizes_in_zip,
)
from oneirodex.utils.security import is_path_within, is_plain_file_within


def find_archive_extractors() -> dict[str, str]:
    """Return ``{tool_key: absolute_path}`` for ``7z`` / ``7za`` / ``bsdtar`` / ``unrar`` on PATH."""
    found: dict[str, str] = {}
    for key, binary in _EXTRACTOR_BINARIES:
        path = shutil.which(binary)
        if path:
            found[key] = path
    return found


def _missing_extractor_error(*, archive_kind: str) -> ArchiveRomError:
    return ArchiveRomError(
        f'Failed to extract {archive_kind} archive — no extractor tool found',
        status_code=415,
        code='missing_extractor',
        hint=_MISSING_EXTRACTOR_HINT,
    )


def _configure_rarfile_tools(rarfile_mod) -> list[str]:
    """Point rarfile at available ``7z`` / ``bsdtar`` / ``unrar`` and force tool rediscovery."""
    found = find_archive_extractors()
    if '7z' in found:
        rarfile_mod.SEVENZIP_TOOL = found['7z']
    if '7za' in found:
        rarfile_mod.SEVENZIP2_TOOL = found['7za']
    if 'bsdtar' in found:
        rarfile_mod.BSDTAR_TOOL = found['bsdtar']
    if 'unrar' in found:
        rarfile_mod.UNRAR_TOOL = found['unrar']

    has_unrar = 'unrar' in found
    has_7z = '7z' in found
    has_7za = '7za' in found
    has_bsdtar = 'bsdtar' in found
    if not (has_unrar or has_7z or has_7za or has_bsdtar):
        return []

    # Prefer available tools; skip unrar when absent so 7z/bsdtar are tried first.
    rarfile_mod.tool_setup(
        unrar=has_unrar,
        unar=False,
        sevenzip=has_7z,
        sevenzip2=has_7za,
        bsdtar=has_bsdtar,
        force=True,
    )
    return list(found.keys())


def _run_extractor(cmdline: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmdline,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _list_roms_via_7z(archive_path: str, seven_z: str) -> list[tuple[str, int]]:
    """List ROM members via ``7z l -slt`` (works for .7z and many .rar)."""
    result = _run_extractor([seven_z, 'l', '-slt', '-ba', archive_path])
    if result.returncode != 0:
        raise ArchiveRomError(
            'Failed to list archive members with 7z',
            status_code=415,
            code='extract_failed',
            hint=_MISSING_EXTRACTOR_HINT if not find_archive_extractors() else (
                'Archive may be corrupt or password-protected; prefer a .zip ROM.'
            ),
        )
    members: list[tuple[str, int]] = []
    path: str | None = None
    size = 0
    is_dir = False
    is_link = False

    def _flush() -> None:
        # Member names are attacker-controlled: anything that could land outside
        # the extraction directory never reaches the chooser, and links are not
        # ROMs (7z prints the target on a ``Symbolic Link =`` line).
        if path and not is_dir and not is_link and _is_rom_name(path):
            safe = _safe_member_name(path)
            if safe is not None:
                members.append((safe, size))

    for line in (result.stdout or '').splitlines():
        if line.startswith('Path = '):
            _flush()
            path = line[7:].strip()
            size = 0
            is_dir = False
            is_link = False
        elif line.startswith('Size = '):
            try:
                size = int(line[7:].strip() or 0)
            except ValueError:
                size = 0
        elif line.startswith('Attributes = '):
            attrs = line[13:].strip().upper()
            is_dir = 'D' in attrs
        elif line.startswith('Symbolic Link = '):
            is_link = bool(line[16:].strip())
        elif line == '' and path:
            _flush()
            path = None
            size = 0
            is_dir = False
            is_link = False
    _flush()
    return members


def _list_roms_via_bsdtar(archive_path: str, bsdtar: str) -> list[tuple[str, int]]:
    result = _run_extractor([bsdtar, '-tf', archive_path])
    if result.returncode != 0:
        raise ArchiveRomError(
            'Failed to list archive members with bsdtar',
            status_code=415,
            code='extract_failed',
            hint='Archive may be corrupt or use an unsupported RAR variant; prefer .zip or install 7z.',
        )
    members: list[tuple[str, int]] = []
    for line in (result.stdout or '').splitlines():
        name = line.strip().replace('\\', '/')
        if not name or name.endswith('/'):
            continue
        if _is_rom_name(name):
            safe = _safe_member_name(name)
            if safe is not None:
                members.append((safe, 0))
    return members


def _lexical_extract_paths(cache_dir: str, targets: list[str]) -> list[str]:
    """Where a target can land -- flattened (7z -e) or nested (bsdtar) -- by name only.

    Member names are attacker-controlled. Anything ``_safe_member_name`` refuses
    (absolute, drive letter, ``..``) yields no candidate at all, and the nested
    form is only ever built from the normalised, already-safe relative name.
    This does not look at the disk; :func:`_extract_paths_for` adds the
    realpath containment check that catches links the archive planted.
    """
    out: list[str] = []
    for target in targets:
        safe = _safe_member_name(target)
        if safe is None:
            continue
        base = Path(safe).name
        if not base or base in ('.', '..'):
            continue
        out.append(os.path.join(cache_dir, base))
        out.append(os.path.join(cache_dir, safe.replace('/', os.sep)))
    return out


def _extract_paths_for(cache_dir: str, targets: list[str]) -> list[str]:
    """Candidate landing paths that really resolve inside ``cache_dir``."""
    return [
        path for path in _lexical_extract_paths(cache_dir, targets)
        if is_path_within(cache_dir, path)
    ]


def _parent_in_cache(cache_dir: str, path: str) -> bool:
    """True when the directory holding *path* is ``cache_dir`` or below it, links resolved."""
    real_cache = os.path.realpath(cache_dir)
    real_parent = os.path.realpath(os.path.dirname(path))
    return real_parent == real_cache or is_path_within(real_cache, real_parent)


def _unlink_in_cache(cache_dir: str, path: str, *, links_only: bool = False) -> None:
    """Remove one extracted file or link, but never anything reached *through* a link.

    Only the final path component is removed, and only when the directory that
    holds it resolves inside the cache -- so a planted ``dir -> /elsewhere``
    cannot turn a cleanup into a delete outside it.
    """
    try:
        if not _parent_in_cache(cache_dir, path):
            return
        if os.path.islink(path):
            os.remove(path)
        elif not links_only and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _replace_in_cache(cache_dir: str, src: str, dest: str) -> bool:
    """``os.replace`` that refuses unless both ends are plain paths inside ``cache_dir``."""
    try:
        if os.path.islink(src) or not os.path.isfile(src):
            return False
        if not (is_path_within(cache_dir, src) and is_path_within(cache_dir, dest)):
            return False
        os.replace(src, dest)
        return True
    except OSError:
        return False


def _prune_empty_dirs(cache_dir: str, start: str) -> None:
    """Remove now-empty nested directories up to (not including) ``cache_dir``."""
    parent = start
    while is_path_within(cache_dir, parent):
        try:
            os.rmdir(parent)
        except OSError:
            break
        parent = os.path.dirname(parent)


def _remove_extracted_links(cache_dir: str, targets: list[str]) -> None:
    """An archive can carry a symlink member named like a ROM; never keep one."""
    for path in _lexical_extract_paths(cache_dir, targets):
        _unlink_in_cache(cache_dir, path, links_only=True)


def _extracted_bytes(cache_dir: str, targets: list[str], chosen: str) -> bool:
    """True when the member we actually asked for arrived with bytes in it."""
    return _member_has_bytes(cache_dir, chosen)


def _clear_empty_extracts(cache_dir: str, targets: list[str]) -> None:
    """Remove the zero-byte husks a failed decode leaves, so the next tool
    starts clean and a later run does not serve an empty ROM from cache."""
    for path in _lexical_extract_paths(cache_dir, targets):
        try:
            if os.path.islink(path) or (os.path.isfile(path) and os.path.getsize(path) == 0):
                _unlink_in_cache(cache_dir, path)
        except OSError:
            pass


def _extract_members_via_7z(
    archive_path: str,
    cache_dir: str,
    members: list[str],
    seven_z: str,
    budget: RomExpansionBudget | None = None,
) -> None:
    budget = budget or RomExpansionBudget()
    for index, member in enumerate(members):
        safe = _safe_member_name(member)
        if safe is None:
            continue
        dest = os.path.join(cache_dir, Path(safe).name)
        try:
            _extract_cli_member([seven_z, 'x', '-so', archive_path, '--', member], dest, budget)
        except ArchiveRomError as exc:
            if index == 0 or exc.code == 'archive_too_large':
                raise
            logger.warning('rom_archive: skipped unextractable cue companion %s', Path(member).name)


def _extract_cli_member(
    command: list[str],
    destination: str,
    budget: RomExpansionBudget,
    *,
    timeout: int = 600,
) -> None:
    """Stream one extracted member through the shared budget instead of disk extraction."""
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if os.path.islink(destination):
        os.unlink(destination)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timer = threading.Timer(timeout, process.kill)
    timer.daemon = True
    timer.start()
    try:
        assert process.stdout is not None
        with open(destination, 'wb') as output:
            budget.copy_stream(process.stdout, output)
        code = process.wait()
        if code != 0:
            raise ArchiveRomError(
                'Failed to extract ROM with the configured archive tool',
                status_code=415,
                code='extract_failed',
                hint='Archive may be corrupt, password-protected or use an unsupported method.',
            )
    except BaseException:
        process.kill()
        process.wait()
        try:
            if os.path.isfile(destination):
                os.remove(destination)
        except OSError:
            pass
        raise
    finally:
        timer.cancel()
        if process.stdout:
            process.stdout.close()


def _check_declared_expansion(
    members: list[tuple[str, int]], targets: list[str], budget: RomExpansionBudget,
) -> None:
    wanted = set(targets)
    declared_total = sum(max(0, size) for name, size in members if name in wanted)
    if declared_total > budget.remaining:
        budget.consume(declared_total)


# bsdtar matches member arguments as shell-style patterns, and ROM names are
# full of metacharacters -- `[!]`, `[NGCD-058]`, `(Track 02 of 34)`. An exact
# name therefore asks bsdtar for a character class and it answers "Not found in
# archive". Backslash-escaping makes the match literal, which also keeps the
# work to the members we want instead of unpacking 700 MB to reach one cue.
_GLOB_METACHARS = frozenset('*?[]\\')

# How many damaged members we will step over before calling the archive bad.
_MAX_DAMAGED_MEMBERS = 6


def _bsdtar_literal(member: str) -> str:
    return ''.join('\\' + ch if ch in _GLOB_METACHARS else ch for ch in member)


def _member_has_bytes(cache_dir: str, member: str) -> bool:
    return any(
        is_plain_file_within(cache_dir, path) and os.path.getsize(path) > 0
        for path in _extract_paths_for(cache_dir, [member])
    )


def _drop_member_files(cache_dir: str, member: str) -> None:
    for path in _lexical_extract_paths(cache_dir, [member]):
        _unlink_in_cache(cache_dir, path)


def _bsdtar_damaged_member(stderr: str, wanted: list[str]) -> str | None:
    """Which member bsdtar died on, when it named one.

    A CD rip with one bad audio track stops the whole run, so a cue sitting at
    member 34 of 34 never lands even though every other track decoded. bsdtar
    prints the member it choked on; the caller drops that one and asks again.
    """
    text = stderr or ''
    hits = []
    for member in wanted:
        for needle in (member, Path(member).name):
            at = text.find(needle)
            if at >= 0:
                hits.append((at, member))
                break
    return min(hits)[1] if hits else None


def _extract_members_via_bsdtar(
    archive_path: str,
    cache_dir: str,
    members: list[str],
    bsdtar: str,
    budget: RomExpansionBudget | None = None,
) -> None:
    budget = budget or RomExpansionBudget()
    for index, member in enumerate(members):
        safe = _safe_member_name(member)
        if safe is None:
            continue
        dest = os.path.join(cache_dir, Path(safe).name)
        try:
            _extract_cli_member([bsdtar, '-xOf', archive_path, '--', _bsdtar_literal(member)], dest, budget)
        except ArchiveRomError as exc:
            if index == 0 or exc.code == 'archive_too_large':
                raise
            logger.warning('rom_archive: skipped unextractable cue companion %s', Path(member).name)


def _extract_archive_via_cli(
    archive_path: str,
    cache_dir: str,
    *,
    member: str | None = None,
    platform: str | None = None,
    archive_kind: str = 'archive',
    budget: RomExpansionBudget | None = None,
) -> str:
    """Extract one ROM (and cue companions) using host ``7z`` or ``bsdtar``."""
    budget = budget or RomExpansionBudget()
    found = find_archive_extractors()
    seven = found.get('7z') or found.get('7za')
    bsdtar = found.get('bsdtar')
    if not seven and not bsdtar:
        raise _missing_extractor_error(archive_kind=archive_kind)

    last_error: ArchiveRomError | None = None
    members: list[tuple[str, int]] = []
    tool_name = ''
    if seven:
        try:
            members = _list_roms_via_7z(archive_path, seven)
            tool_name = '7z'
        except ArchiveRomError as exc:
            last_error = exc
    if not members and bsdtar:
        try:
            members = _list_roms_via_bsdtar(archive_path, bsdtar)
            tool_name = 'bsdtar'
        except ArchiveRomError as exc:
            last_error = exc

    if not members:
        if last_error is not None:
            raise last_error
        raise ArchiveRomError(
            f'No playable ROM files found inside {archive_kind} archive',
            code='no_playable_member',
            hint='Archive should contain a ROM with a known extension (e.g. .nes, .sfc, .gba).',
        )

    chosen = choose_rom_member(members, platform=platform, preferred_member=member)
    safe_name = _safe_basename(chosen)
    dest = os.path.join(cache_dir, safe_name)
    _unlink_in_cache(cache_dir, dest, links_only=True)
    if is_plain_file_within(cache_dir, dest) and os.path.getsize(dest) > 0:
        return dest

    targets = _cue_companion_targets(members, chosen)
    _check_declared_expansion(members, targets, budget)
    os.makedirs(cache_dir, exist_ok=True)

    # The tool that could *list* the archive is not necessarily the tool that
    # can *decompress* it: a 7-Zip build without the RAR codec lists a RAR5
    # happily and then writes zero-byte files ("Unsupported Method"). So try
    # the listing tool, check it produced real bytes, and fall back to the
    # other one rather than handing the member a truncated ROM.
    attempts: list[tuple[str, object]] = []
    if tool_name == '7z' and seven:
        attempts.append(('7z', seven))
        if bsdtar:
            attempts.append(('bsdtar', bsdtar))
    elif bsdtar:
        attempts.append(('bsdtar', bsdtar))
        if seven:
            attempts.append(('7z', seven))
    if not attempts:
        raise _missing_extractor_error(archive_kind=archive_kind)

    extract_error: ArchiveRomError | None = None
    for name, tool in attempts:
        try:
            if name == '7z':
                _extract_members_via_7z(archive_path, cache_dir, targets, str(tool), budget)
            else:
                _extract_members_via_bsdtar(archive_path, cache_dir, targets, str(tool), budget)
        except ArchiveRomError as exc:
            extract_error = exc
            _clear_empty_extracts(cache_dir, targets)
            if exc.code == 'archive_too_large':
                raise
            # A tool can fail the *archive* and still have written the member we
            # asked for: one bad audio track in a 34-track CD rip makes bsdtar
            # exit non-zero long after the .cue and the data track landed. The
            # question is whether the ROM is here and whole, not whether every
            # companion survived -- so check before throwing the work away.
            if _extracted_bytes(cache_dir, targets, chosen):
                break
            continue
        if _extracted_bytes(cache_dir, targets, chosen):
            break
        # Zero bytes on disk is a failed decode wearing a success's clothes.
        extract_error = ArchiveRomError(
            f'{name} produced an empty file for this {archive_kind} archive',
            status_code=415,
            code='extract_failed',
            hint=f'{name} can list this archive but not decompress it (missing codec).',
        )
        _clear_empty_extracts(cache_dir, targets)
    else:
        if extract_error is not None:
            raise extract_error

    # A symlink member named like a ROM is not a ROM; never keep one around
    # where a later cache hit or bundle could follow it out of cache_dir.
    _remove_extracted_links(cache_dir, targets)

    # 7z -e already flattens; ensure companions land as basenames.
    for target in targets:
        safe = _safe_member_name(target)
        if safe is None:
            continue
        flat = os.path.join(cache_dir, Path(safe).name)
        nested = os.path.join(cache_dir, safe.replace('/', os.sep))
        if nested != flat:
            _replace_in_cache(cache_dir, nested, flat)

    if not is_plain_file_within(cache_dir, dest):
        raise ArchiveRomError(
            f'Failed to extract ROM from {archive_kind} archive',
            code='extract_failed',
            hint='Prefer re-packing as .zip with a single known ROM extension.',
        )
    return dest


def list_roms_in_zip(zip_path: str) -> list[str]:
    return [name for name, _ in _list_roms_with_sizes_in_zip(zip_path)]


def path_is_supported_archive(path: str | Path | None) -> bool:
    """True when path looks like a zip/7z/rar container (existence not required)."""
    if not path:
        return False
    return Path(path).suffix.lower() in ARCHIVE_EXTENSIONS


def list_roms_in_archive(archive_path: str) -> list[tuple[str, int]]:
    """
    List playable ROM members ``(name, size)`` inside zip/7z/rar.

    Raises ``ArchiveRomError`` on corrupt / unsupported archives. Returns [] when
    the archive opens but contains no ROM-like members.
    """
    path = os.path.abspath(archive_path)
    if not os.path.isfile(path):
        raise ArchiveRomError(
            'Archive path not found',
            status_code=404,
            code='path_not_found',
        )
    ext = Path(path).suffix.lower()
    if ext == '.zip':
        return _list_roms_with_sizes_in_zip(path)
    if ext == '.7z':
        return _list_roms_in_7z(path)
    if ext == '.rar':
        return _list_roms_in_rar(path)
    raise ArchiveRomError(
        f'{ext or "unknown"} archives are not supported — use .zip, .7z, or .rar',
        status_code=415,
        code='unsupported_format',
    )


def _list_roms_in_rar(archive_path: str) -> list[tuple[str, int]]:
    tools = find_archive_extractors()
    has_cli = bool(tools.get('7z') or tools.get('7za') or tools.get('bsdtar') or tools.get('unrar'))
    try:
        import rarfile
    except ImportError:
        seven = tools.get('7z') or tools.get('7za')
        if seven:
            return _list_roms_via_7z(archive_path, seven)
        if tools.get('bsdtar'):
            return _list_roms_via_bsdtar(archive_path, tools['bsdtar'])
        raise ArchiveRomError(
            '.rar support requires rarfile plus an extractor tool (7z/bsdtar/unrar)',
            status_code=415,
            code='missing_extractor',
            hint=_MISSING_EXTRACTOR_HINT,
        )

    configured = _configure_rarfile_tools(rarfile)
    if not configured and not has_cli:
        raise _missing_extractor_error(archive_kind='rar')

    try:
        with rarfile.RarFile(archive_path) as archive:
            return [
                (info.filename, int(getattr(info, 'file_size', 0) or 0))
                for info in archive.infolist()
                if not info.is_dir()
                and _is_rom_name(info.filename)
                and _safe_member_name(info.filename) is not None
            ]
    except ArchiveRomError:
        raise
    except Exception:
        seven = tools.get('7z') or tools.get('7za')
        if seven:
            return _list_roms_via_7z(archive_path, seven)
        if tools.get('bsdtar'):
            return _list_roms_via_bsdtar(archive_path, tools['bsdtar'])
        raise ArchiveRomError(
            'Failed to list rar archive members',
            status_code=415,
            code='extract_failed',
            hint='Prefer re-packing as .zip, or verify the RAR is not password-protected.',
        )


def _list_roms_in_7z(archive_path: str) -> list[tuple[str, int]]:
    try:
        import py7zr
        from py7zr.exceptions import Bad7zFile
    except ImportError:
        found = find_archive_extractors()
        seven = found.get('7z') or found.get('7za')
        if seven:
            return _list_roms_via_7z(archive_path, seven)
        raise ArchiveRomError(
            '.7z support requires py7zr or a host 7z binary',
            status_code=415,
            code='missing_extractor',
            hint=_MISSING_EXTRACTOR_HINT,
        )
    try:
        with py7zr.SevenZipFile(archive_path, mode='r') as archive:
            names = [
                name for name in archive.getnames()
                if _is_rom_name(name) and _safe_member_name(name) is not None
            ]
            # py7zr does not always expose reliable per-file sizes before extract; use 0.
            return [(name, 0) for name in names]
    except Bad7zFile as exc:
        raise ArchiveRomError(
            'Invalid or corrupt 7z archive',
            status_code=400,
            code='corrupt_archive',
        ) from exc


def extract_rom_from_7z(
    archive_path: str,
    cache_dir: str,
    *,
    member: str | None = None,
    platform: str | None = None,
    budget: RomExpansionBudget | None = None,
) -> str:
    budget = budget or RomExpansionBudget()
    try:
        import py7zr
        from py7zr.exceptions import Bad7zFile
    except ImportError:
        return _extract_archive_via_cli(
            archive_path,
            cache_dir,
            member=member,
            platform=platform,
            archive_kind='7z',
            budget=budget,
        )

    os.makedirs(cache_dir, exist_ok=True)
    try:
        members = _list_roms_in_7z(archive_path)
    except ArchiveRomError:
        # py7zr present but list failed oddly — try host 7z before giving up.
        found = find_archive_extractors()
        if found.get('7z') or found.get('7za'):
            return _extract_archive_via_cli(
                archive_path,
                cache_dir,
                member=member,
                platform=platform,
                archive_kind='7z',
                budget=budget,
            )
        raise
    if not members:
        raise ArchiveRomError(
            'No playable ROM files found inside 7z archive',
            code='no_playable_member',
            hint='Archive should contain a ROM with a known extension (e.g. .nes, .sfc, .gba).',
        )
    chosen = choose_rom_member(members, platform=platform, preferred_member=member)
    safe_name = _safe_basename(chosen)
    dest = os.path.join(cache_dir, safe_name)
    _unlink_in_cache(cache_dir, dest, links_only=True)
    if is_plain_file_within(cache_dir, dest) and os.path.getsize(dest) > 0:
        return dest

    targets = _cue_companion_targets(members, chosen)
    _check_declared_expansion(members, targets, budget)

    try:
        with py7zr.SevenZipFile(
            archive_path, mode='r', max_extract_size=budget.remaining,
        ) as archive:
            archive.extract(targets=targets, path=cache_dir)
    except Exception as exc:
        for target_name in targets:
            _drop_member_files(cache_dir, target_name)
        if 'exceeds limit of' in str(exc):
            raise ArchiveRomError(
                'Expanded archive output exceeds the 64 GiB limit',
                status_code=413,
                code='archive_too_large',
            ) from exc
        if isinstance(exc, Bad7zFile):
            raise ArchiveRomError(
                'Invalid or corrupt 7z archive',
                status_code=400,
                code='corrupt_archive',
            ) from exc
        raise

    extracted_bytes = sum(
        os.path.getsize(path)
        for target_name in targets
        for path in _extract_paths_for(cache_dir, [target_name])
        if is_plain_file_within(cache_dir, path)
    )
    try:
        budget.consume(extracted_bytes)
    except ArchiveRomError:
        for target_name in targets:
            _drop_member_files(cache_dir, target_name)
        raise

    # Nothing below may move a file that is not inside cache_dir, whatever the
    # archive called its members (see _replace_in_cache).
    _remove_extracted_links(cache_dir, targets)
    extracted = os.path.join(cache_dir, chosen)
    if extracted != dest and _replace_in_cache(cache_dir, extracted, dest):
        _prune_empty_dirs(cache_dir, os.path.dirname(extracted))
    for companion_name in targets[1:]:
        companion_src = os.path.join(cache_dir, companion_name)
        companion_dest = os.path.join(cache_dir, Path(companion_name).name)
        if companion_src != companion_dest:
            _replace_in_cache(cache_dir, companion_src, companion_dest)
    if not is_plain_file_within(cache_dir, dest):
        # Fall back to host 7z when py7zr wrote nothing useful.
        found = find_archive_extractors()
        if found.get('7z') or found.get('7za'):
            return _extract_archive_via_cli(
                archive_path,
                cache_dir,
                member=member,
                platform=platform,
                archive_kind='7z',
                budget=budget,
            )
        raise ArchiveRomError(
            'Failed to extract ROM from 7z archive',
            code='extract_failed',
        )
    return dest


def extract_rom_from_rar(
    archive_path: str,
    cache_dir: str,
    *,
    member: str | None = None,
    platform: str | None = None,
    budget: RomExpansionBudget | None = None,
) -> str:
    budget = budget or RomExpansionBudget()
    """
    Extract one ROM from a .rar archive.

    Prefers host ``7z`` / ``bsdtar`` (Docker ships both) via rarfile or a direct
    CLI path. Returns ``missing_extractor`` JSON when no tool is available.
    """
    os.makedirs(cache_dir, exist_ok=True)
    tools = find_archive_extractors()
    has_cli = bool(tools.get('7z') or tools.get('7za') or tools.get('bsdtar') or tools.get('unrar'))

    try:
        import rarfile
    except ImportError as exc:
        if has_cli:
            return _extract_archive_via_cli(
                archive_path,
            cache_dir,
            member=member,
            platform=platform,
            archive_kind='rar',
            budget=budget,
            )
        raise ArchiveRomError(
            '.rar support requires rarfile plus an extractor tool (7z/bsdtar/unrar)',
            status_code=415,
            code='missing_extractor',
            hint=_MISSING_EXTRACTOR_HINT,
        ) from exc

    configured = _configure_rarfile_tools(rarfile)
    if not configured and not has_cli:
        raise _missing_extractor_error(archive_kind='rar')

    try:
        with rarfile.RarFile(archive_path) as archive:
            members = [
                (info.filename, int(getattr(info, 'file_size', 0) or 0))
                for info in archive.infolist()
                if not info.is_dir()
                and _is_rom_name(info.filename)
                and _safe_member_name(info.filename) is not None
            ]
            if not members:
                raise ArchiveRomError(
                    'No playable ROM files found inside rar archive',
                    code='no_playable_member',
                    hint='Archive should contain a ROM with a known extension (e.g. .nes, .sfc, .gba).',
                )
            chosen = choose_rom_member(members, platform=platform, preferred_member=member)
            targets = _cue_companion_targets(members, chosen)
            _check_declared_expansion(members, targets, budget)
            safe_name = _safe_basename(chosen)
            dest = os.path.join(cache_dir, safe_name)
            # open(dest, 'wb') would write through a link sitting at dest.
            _unlink_in_cache(cache_dir, dest, links_only=True)
            if is_plain_file_within(cache_dir, dest) and os.path.getsize(dest) > 0:
                return dest
            expected = next((size for name, size in members if name == chosen), 0)
            with archive.open(chosen) as src, open(dest, 'wb') as out:
                budget.copy_stream(src, out)
            # A backend that cannot decode this RAR returns a short stream
            # rather than raising; a half ROM is worse than an honest failure.
            if expected and os.path.getsize(dest) < expected:
                os.remove(dest)
                raise ArchiveRomError(
                    'rar member came back short',
                    status_code=415,
                    code='extract_failed',
                    hint='The configured rar backend cannot decode this archive.',
                )
            for companion_name in _cue_companion_targets(members, chosen)[1:]:
                companion_dest = os.path.join(cache_dir, Path(companion_name).name)
                _unlink_in_cache(cache_dir, companion_dest, links_only=True)
                if is_plain_file_within(cache_dir, companion_dest) and os.path.getsize(companion_dest) > 0:
                    continue
                with archive.open(companion_name) as src, open(companion_dest, 'wb') as out:
                    budget.copy_stream(src, out)
            return dest
    except ArchiveRomError:
        for target_name in locals().get('targets', []):
            _drop_member_files(cache_dir, target_name)
        raise
    except Exception as exc:
        # rarfile.Error / RarCannotExec / OSError — prefer CLI before failing.
        if tools.get('7z') or tools.get('7za') or tools.get('bsdtar'):
            # The CLI path knows *why* it failed (missing codec, damaged member,
            # password). Reporting a generic "failed to read" over the top of it
            # is what made this look like a missing unrar tool for months.
            return _extract_archive_via_cli(
                archive_path,
                cache_dir,
                member=member,
                platform=platform,
                archive_kind='rar',
                budget=budget,
            )
        if not find_archive_extractors():
            raise _missing_extractor_error(archive_kind='rar') from exc
        raise ArchiveRomError(
            'Failed to read rar archive',
            status_code=415,
            code='extract_failed',
            hint=(
                'A 7z/bsdtar/unrar tool was found but could not open this archive. '
                'Prefer re-packing as .zip, or verify the RAR is not password-protected.'
            ),
        ) from exc


def resolve_playable_rom_path(
    source_path: str,
    *,
    cache_dir: str,
    platform: str | None = None,
    budget: RomExpansionBudget | None = None,
) -> tuple[str, str]:
    """
    Return (absolute_file_path, filename) suitable for WebRetro streaming.

    Supports plain ROM files, .zip (including nested zip), optional .7z (py7zr),
    optional .rar (rarfile), and single-file .gz ROM wrappers.
    """
    budget = budget or RomExpansionBudget()
    if not source_path or not os.path.exists(source_path):
        raise ArchiveRomError(
            'ROM path not found',
            status_code=404,
            code='path_not_found',
        )

    path = os.path.abspath(source_path)
    if os.path.isfile(path):
        ext = Path(path).suffix.lower()
        if ext in UNSUPPORTED_ARCHIVE_EXTENSIONS:
            raise ArchiveRomError(
                f'{ext} archives are not supported — use .zip, .7z, .rar, .gz (ROM.gz), or a raw ROM',
                status_code=415,
                code='unsupported_format',
            )
        if ext == '.zip':
            extracted = extract_rom_from_zip(path, cache_dir, platform=platform, budget=budget)
            return extracted, os.path.basename(extracted)
        if ext == '.7z':
            extracted = extract_rom_from_7z(path, cache_dir, platform=platform, budget=budget)
            return extracted, os.path.basename(extracted)
        if ext == '.rar':
            extracted = extract_rom_from_rar(path, cache_dir, platform=platform, budget=budget)
            return extracted, os.path.basename(extracted)
        if ext in GZIP_EXTENSIONS:
            extracted = extract_rom_from_gz(path, cache_dir, budget=budget)
            return extracted, os.path.basename(extracted)
        return path, os.path.basename(path)

    if os.path.isdir(path):
        # A game folder is scanned content, not operator-authored: a
        # ``game.bin -> /etc/whatever`` link in it must not be served as the ROM
        # (nor a ``game.zip`` link be unpacked), so links and anything whose
        # realpath leaves the folder are not candidates.
        archives = [
            os.path.join(path, name)
            for name in os.listdir(path)
            if Path(name).suffix.lower() in (ARCHIVE_EXTENSIONS | GZIP_EXTENSIONS)
            and is_plain_file_within(path, os.path.join(path, name))
        ]
        roms = [
            os.path.join(path, name)
            for name in os.listdir(path)
            if _is_rom_name(name) and is_plain_file_within(path, os.path.join(path, name))
        ]
        if len(roms) == 1:
            return roms[0], os.path.basename(roms[0])
        if len(archives) == 1:
            return resolve_playable_rom_path(archives[0], cache_dir=cache_dir, platform=platform, budget=budget)
        if roms:
            sized = [(p, os.path.getsize(p)) for p in roms]
            chosen_path = choose_rom_member(
                [(os.path.basename(p), size) for p, size in sized],
                platform=platform,
            )
            for full, _ in sized:
                if os.path.basename(full) == chosen_path:
                    return full, os.path.basename(full)
            chosen = sorted(roms)[0]
            return chosen, os.path.basename(chosen)
        if archives:
            raise ArchiveRomError(
                'Folder has multiple archives — ambiguous for WebRetro play',
                status_code=400,
                code='ambiguous_folder',
                hint='Keep one archive or one ROM in the game folder for browser play.',
            )
        raise ArchiveRomError(
            'Folder has no single archive/ROM suitable for WebRetro play',
            status_code=400,
            code='ambiguous_folder',
            hint='Place one .zip/.7z/.rar/.gz or a raw ROM in the game folder.',
        )

    raise ArchiveRomError(
        'Unsupported ROM path type',
        status_code=400,
        code='unsupported_format',
    )


