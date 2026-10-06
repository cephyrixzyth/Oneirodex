"""Zip and gzip handling for playable ROMs (stdlib only -- no external
extractor), plus the playable-zip bundler with cue-sheet path rewriting.

Split out of ``rom_archive`` in the v11 cycle (H-D.4) as a pure move. The
7z / rar paths, which shell out to an extractor, stay in ``rom_archive``.
"""
from __future__ import annotations

import gzip
import io
import os
import re
import shutil
import zipfile
from pathlib import Path
from oneirodex.utils.rom_archive_select import _is_rom_name
from oneirodex.utils.rom_archive_types import ArchiveRomError, RomExpansionBudget
from oneirodex.utils.rom_archive_select import _member_ext
from oneirodex.utils.rom_archive_types import CUE_COMPANION_EXTENSIONS
from oneirodex.utils.rom_archive_select import choose_rom_member
from oneirodex.utils.rom_archive_select import _platform_key, _safe_basename
from oneirodex.utils.rom_archive_types import PLATFORM_ROM_EXTENSIONS
from oneirodex.utils.rom_archive_types import MAX_NEST_DEPTH
from oneirodex.utils.security import is_plain_file_within, open_plain_file_within
from oneirodex.utils.zipstream import zip_date_time


def _list_roms_with_sizes_in_zip(zip_path: str) -> list[tuple[str, int]]:
    try:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            return [
                (info.filename, int(info.file_size or 0))
                for info in archive.infolist()
                if not info.is_dir() and _is_rom_name(info.filename)
            ]
    except zipfile.BadZipFile as exc:
        raise ArchiveRomError(
            'Invalid or corrupt zip archive',
            code='corrupt_archive',
            hint='Re-zip the ROM or use a raw ROM / .7z / .rar if the file is not a zip.',
        ) from exc


def _list_nested_zip_members(zip_path: str) -> list[tuple[str, int]]:
    with zipfile.ZipFile(zip_path, 'r') as archive:
        return [
            (info.filename, int(info.file_size or 0))
            for info in archive.infolist()
            if not info.is_dir() and info.filename.lower().endswith('.zip')
        ]


def _extract_zip_member(
    archive: zipfile.ZipFile, member: str, dest: str,
    budget: RomExpansionBudget | None = None,
) -> None:
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # open(dest, 'wb') writes *through* a link sitting at dest; replace it instead.
    if os.path.islink(dest):
        os.unlink(dest)
    budget = budget or RomExpansionBudget()
    try:
        info = archive.getinfo(member)
        if info.file_size > budget.remaining:
            budget.consume(info.file_size)
        with archive.open(member) as src, open(dest, 'wb') as out:
            budget.copy_stream(src, out)
    except Exception:
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass
        raise


def _extract_cue_companions(
    archive: zipfile.ZipFile,
    chosen: str,
    cache_dir: str,
    member_names: set[str],
    budget: RomExpansionBudget,
) -> None:
    """Extract disc companions (.bin/.img/…) next to a chosen .cue in the same zip folder."""
    if _member_ext(chosen) != '.cue':
        return
    folder = str(Path(chosen).parent).replace('\\', '/')
    if folder == '.':
        folder = ''
    prefix = f'{folder}/' if folder else ''
    for name in member_names:
        if name == chosen:
            continue
        norm = name.replace('\\', '/')
        if folder:
            if not norm.startswith(prefix):
                continue
            rest = norm[len(prefix):]
            if '/' in rest:
                continue
        elif '/' in norm or '\\' in name:
            continue
        if _member_ext(name) not in CUE_COMPANION_EXTENSIONS:
            continue
        companion_dest = os.path.join(cache_dir, Path(name).name)
        if os.path.isfile(companion_dest) and os.path.getsize(companion_dest) > 0:
            continue
        try:
            _extract_zip_member(archive, name, companion_dest, budget)
        except KeyError:
            continue


_ARCHIVE_EXTS = ('.zip', '.7z')


def _drop_archive_members(
    members: list[tuple[str, int]],
    platform: str | None,
    keep: str | None = None,
) -> list[tuple[str, int]]:
    """Inner archives are the ROM only where the platform's dumps are archives.

    Arcade and Neo Geo put ``.zip``/``.7z`` in ``PLATFORM_ROM_EXTENSIONS``,
    which unions them into ``ROM_EXTENSIONS`` for every platform. Left in, a
    GBA pack shaped ``outer.zip > inner.zip > Hero.gba`` handed the player
    ``inner.zip`` and the nested search below never ran.

    With no known platform the old behaviour stands, and an explicitly
    requested member (*keep*) is never dropped.
    """
    key = _platform_key(platform)
    if key not in PLATFORM_ROM_EXTENSIONS:
        return members
    if any(ext in PLATFORM_ROM_EXTENSIONS[key] for ext in _ARCHIVE_EXTS):
        return members
    return [
        (name, size) for name, size in members
        if name == keep or not name.lower().endswith(_ARCHIVE_EXTS)
    ]


def extract_rom_from_zip(
    zip_path: str,
    cache_dir: str,
    *,
    member: str | None = None,
    platform: str | None = None,
    nest_depth: int = 0,
    budget: RomExpansionBudget | None = None,
) -> str:
    """
    Extract one ROM member from a zip into cache_dir and return absolute path.

    Supports nested .zip members when no ROM is present at the current level.
    When a .cue is selected, sibling disc images in the same folder are extracted too.
    """
    os.makedirs(cache_dir, exist_ok=True)
    budget = budget or RomExpansionBudget()
    rom_members = _drop_archive_members(_list_roms_with_sizes_in_zip(zip_path), platform, keep=member)

    if rom_members:
        chosen = choose_rom_member(rom_members, platform=platform, preferred_member=member)
        safe_name = _safe_basename(chosen)
        dest = os.path.join(cache_dir, safe_name)
        with zipfile.ZipFile(zip_path, 'r') as archive:
            all_names = {info.filename for info in archive.infolist() if not info.is_dir()}
            preexisting_outputs = {
                os.path.join(cache_dir, Path(name).name)
                for name in all_names
                if os.path.isfile(os.path.join(cache_dir, Path(name).name))
            }
            if not (os.path.isfile(dest) and os.path.getsize(dest) > 0):
                try:
                    _extract_zip_member(archive, chosen, dest, budget)
                except KeyError as exc:
                    raise ArchiveRomError(
                        f'ROM member not found in zip: {safe_name}',
                        code='invalid_member',
                    ) from exc
            try:
                _extract_cue_companions(archive, chosen, cache_dir, all_names, budget)
            except ArchiveRomError:
                # A cue and its tracks form one playable result; never leave a
                # cue behind when the aggregate companion budget is exceeded.
                for output in {dest, *(os.path.join(cache_dir, Path(n).name) for n in all_names)} - preexisting_outputs:
                    try:
                        if os.path.isfile(output):
                            os.remove(output)
                    except OSError:
                        pass
                raise
        if not os.path.isfile(dest):
            raise ArchiveRomError(
                'Failed to extract ROM from zip archive',
                code='extract_failed',
            )
        return dest

    if nest_depth >= MAX_NEST_DEPTH:
        raise ArchiveRomError(
            'No playable ROM files found inside zip archive (nested search exhausted)',
            code='no_playable_member',
            hint='Put a ROM directly in the zip, or use a shallower nest of zip-in-zip.',
        )

    nested = _list_nested_zip_members(zip_path)
    if not nested:
        raise ArchiveRomError(
            'No playable ROM files found inside zip archive',
            code='no_playable_member',
            hint='Archive should contain a ROM with a known extension (e.g. .nes, .sfc, .gba).',
        )

    nested.sort(key=lambda item: (-item[1], item[0].lower()))
    last_error: ArchiveRomError | None = None
    for nested_name, _ in nested[:8]:
        nested_basename = _safe_basename(nested_name)
        nested_dest = os.path.join(cache_dir, f'_nested_{nest_depth}_{nested_basename}')
        try:
            with zipfile.ZipFile(zip_path, 'r') as archive:
                if not (os.path.isfile(nested_dest) and os.path.getsize(nested_dest) > 0):
                    _extract_zip_member(archive, nested_name, nested_dest, budget)
            return extract_rom_from_zip(
                nested_dest,
                cache_dir,
                member=member,
                platform=platform,
                nest_depth=nest_depth + 1,
                budget=budget,
            )
        except ArchiveRomError as exc:
            if exc.code == 'archive_too_large':
                try:
                    if os.path.isfile(nested_dest):
                        os.remove(nested_dest)
                except OSError:
                    pass
                raise
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise ArchiveRomError(
        'No playable ROM files found inside nested zip archive',
        code='no_playable_member',
    )


def extract_rom_from_gz(
    gz_path: str, cache_dir: str, *, budget: RomExpansionBudget | None = None,
) -> str:
    """Gunzip a single-file ROM wrapper (e.g. Adventure.nes.gz) into cache_dir."""
    inner_name = Path(gz_path).stem
    if inner_name.lower().endswith('.tar') or not _is_rom_name(inner_name):
        raise ArchiveRomError(
            '.gz must wrap a single ROM file (e.g. game.nes.gz); .tar.gz is not supported',
            status_code=415,
            code='unsupported_format',
            hint='Unzip/repack as .zip/.7z/.rar with a ROM inside, or store the raw ROM.',
        )

    os.makedirs(cache_dir, exist_ok=True)
    budget = budget or RomExpansionBudget()
    safe_name = _safe_basename(inner_name)
    dest = os.path.join(cache_dir, safe_name)
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest

    try:
        if os.path.islink(dest):
            os.unlink(dest)
        with gzip.open(gz_path, 'rb') as src, open(dest, 'wb') as out:
            budget.copy_stream(src, out)
    except ArchiveRomError:
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass
        raise ArchiveRomError(
            'Invalid or corrupt gzip ROM',
            code='corrupt_archive',
        ) from exc

    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        raise ArchiveRomError(
            'Failed to extract ROM from gzip',
            code='extract_failed',
        )
    return dest


# Matches a cue sheet FILE line, quoted or bare: FILE "disc.bin" BINARY / FILE disc.bin BINARY
_CUE_FILE_LINE_RE = re.compile(r'(?im)^(\s*FILE\s+)(?:"([^"]*)"|(\S+))(\s+\S+\s*)$')


def _rewrite_cue_file_paths(cue_text: str) -> str:
    """Rewrite FILE references in a .cue sheet to basenames (for a flattened zip)."""

    def _replace(match: re.Match[str]) -> str:
        prefix, quoted, bare, suffix = match.groups()
        original = quoted if quoted is not None else bare
        basename = Path(original.replace('\\', '/')).name
        if quoted is not None:
            return f'{prefix}"{basename}"{suffix}'
        return f'{prefix}{basename}{suffix}'

    return _CUE_FILE_LINE_RE.sub(_replace, cue_text)


def _write_vetted_member(archive: zipfile.ZipFile, real_root: str, companion: Path) -> None:
    """Add *companion* to *archive* from a vetted open handle, not from its path.

    ``archive.write(path)`` opens the path again, so a companion swapped for a
    link after it was listed would put the link's target into the bundle that
    goes to the member. Here the descriptor that passed
    ``open_plain_file_within`` is the one that is read, and its own ``fstat``
    gives the size and mtime.
    """
    with open_plain_file_within(real_root, companion, base_is_resolved=True) as source:
        info = os.fstat(source.fileno())
        member = zipfile.ZipInfo(companion.name, date_time=zip_date_time(info.st_mtime))
        member.compress_type = zipfile.ZIP_STORED
        member.external_attr = (info.st_mode & 0xFFFF) << 16
        member.file_size = info.st_size
        with archive.open(member, 'w') as target:
            shutil.copyfileobj(source, target, 1024 * 1024)


def bundle_playable_rom_zip(rom_path: str, cache_dir: str, *, root: str | None = None) -> tuple[str, str]:
    """
    Bundle a resolved `.cue` sheet with its sibling disc images (.bin/.img/.iso/
    .raw/.wav) into one stored (uncompressed) zip named `play.zip`, so a single
    HTTP download hands WebRetro every file a multi-track PSX/CD image needs
    (WebRetro's own client-side unzip already splits multi-file zips back out
    for disc cores — see `unzipFileMulti` in base.js).

    Returns (rom_path, filename) unchanged when `rom_path` is not a `.cue` or
    has no companions next to it, so single-file `.iso`/`.chd`/`.bin` play is
    untouched.

    The disc folder is a share someone else can write to, so nothing is read by
    path after it has been vetted: the cue sheet and every companion go through
    ``open_plain_file_within`` against *root* and are written from that handle.
    *root* is the folder's already-resolved path (the caller vetted it when the
    request began); without it the folder is resolved once, here, and every file
    is compared against that string, so a folder swapped for a link afterwards
    reads as "outside" instead of redefining "inside".
    """
    path = Path(rom_path)
    if path.suffix.lower() != '.cue':
        return rom_path, path.name

    source_dir = path.parent
    try:
        sibling_names = sorted(os.listdir(source_dir))
    except OSError as exc:
        raise ArchiveRomError(
            'Failed to read disc folder for ROM bundling',
            code='extract_failed',
        ) from exc

    real_root = root if root is not None else os.path.realpath(source_dir)
    resolved_cue = path.resolve()
    # Only real files that live in the disc folder: a ``disc.bin`` link pointing
    # at some other readable file would otherwise be zipped into the download.
    companions = [
        candidate
        for name in sibling_names
        if Path(name).suffix.lower() in CUE_COMPANION_EXTENSIONS
        for candidate in (source_dir / name,)
        if is_plain_file_within(real_root, candidate, base_is_resolved=True) and candidate.resolve() != resolved_cue
    ]

    if not companions:
        return rom_path, path.name

    os.makedirs(cache_dir, exist_ok=True)
    zip_path = os.path.join(cache_dir, 'play.zip')

    sources = [path, *companions]
    try:
        newest_source_mtime = max(p.stat().st_mtime for p in sources)
    except OSError as exc:
        raise ArchiveRomError(
            'Failed to stat disc files for ROM bundling',
            code='extract_failed',
        ) from exc

    if os.path.isfile(zip_path):
        try:
            fresh = (
                os.path.getsize(zip_path) > 0
                and os.path.getmtime(zip_path) >= newest_source_mtime
            )
        except OSError:
            fresh = False
        if fresh:
            return zip_path, 'play.zip'

    try:
        with io.TextIOWrapper(
            open_plain_file_within(real_root, path, base_is_resolved=True),
            encoding='utf-8',
            errors='replace',
        ) as cue_file:
            cue_text = cue_file.read()
    except OSError as exc:
        raise ArchiveRomError(
            'Failed to read .cue sheet for ROM bundling',
            code='extract_failed',
        ) from exc

    rewritten_cue = _rewrite_cue_file_paths(cue_text)

    tmp_path = f'{zip_path}.tmp-{os.getpid()}'
    try:
        with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(path.name, rewritten_cue)
            for companion in companions:
                _write_vetted_member(zf, real_root, companion)
        os.replace(tmp_path, zip_path)
    except OSError as exc:
        raise ArchiveRomError(
            'Failed to build ROM bundle zip',
            code='extract_failed',
        ) from exc
    finally:
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return zip_path, 'play.zip'
