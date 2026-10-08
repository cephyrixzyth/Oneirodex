#!/usr/bin/env python3
"""Import operator-supplied BIOS files from a local collection into the volume.

Oneirodex never downloads or bundles BIOS. This script does not fetch anything:
it looks through firmware *you already have* and copies the specific files the
libretro cores ask for into the BIOS volume, flattened, under the exact names
the cores look up. Admin > Emulators **Scan collection** / **Install matching
firmware** is the same walk with a version picker and a copyable missing report.

Preview by default, like the storage helpers and leaf-library proposer; nothing
is written until you pass --apply.

    python scripts/import_bios.py --source E:\\_bios
    python scripts/import_bios.py --source E:\\_bios --apply
    python scripts/import_bios.py --source E:\\_bios --require-all

The destination is `oneirodex/static/library/bios` (gitignored), or `bios` in
the data folder when ONEIRODEX_LIBRARY_DIR moves the library, unless
EMULATOR_BIOS_PATH is set or --dest is given. Firmware stays out of git.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import shutil

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_util(filename: str, alias: str):
    """Load oneirodex/utils/<filename> by path, without importing the app package.

    `import oneirodex.utils.emulator_bios` runs `oneirodex/__init__`, which
    imports config and refuses to load without SECRET_KEY — a real requirement
    for the server and a pointless one for a script that only needs a table of
    filenames. The module itself depends on nothing but flask/werkzeug names it
    does not call at import time, so loading it by path is safe and keeps
    BIOS_REQUIREMENTS a single source of truth.
    """
    path = os.path.join(REPO_ROOT, 'oneirodex', 'utils', filename)
    spec = importlib.util.spec_from_file_location(alias, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_bios = _load_util('emulator_bios.py', '_gt_emulator_bios')
# The same link-refusing file checks the server's firmware import uses, so the
# script cannot copy ``scph5501.bin -> /app/.env`` into the firmware volume.
_security = _load_util('security.py', '_gt_security')
BIOS_REQUIREMENTS = _bios.BIOS_REQUIREMENTS
BIOS_HARD_REQUIRED_CORES = _bios.BIOS_HARD_REQUIRED_CORES

# The server's own rule (utils/library_paths): a library moved to a data folder
# with ONEIRODEX_LIBRARY_DIR keeps its firmware there too.
_paths = _load_util('library_paths.py', '_gt_library_paths')
DEFAULT_DEST = os.path.join(
    _paths.relocated_library_dir() or os.path.join(REPO_ROOT, 'oneirodex', 'static', 'library'), 'bios'
)


def wanted_names() -> dict[str, str]:
    """Lowercased filename -> canonical name the cores look up."""
    out: dict[str, str] = {}
    for names in BIOS_REQUIREMENTS.values():
        for name in names:
            out.setdefault(name.lower(), name)
    return out


def _digest(path: str, base: str) -> str:
    h = hashlib.sha1()
    with _security.open_plain_file_within(base, path) as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def scan(source: str, wanted: dict[str, str]) -> dict[str, list[str]]:
    """Every path under *source* whose filename is one a core asks for."""
    found: dict[str, list[str]] = {}
    for dirpath, _dirnames, filenames in os.walk(source):
        for filename in filenames:
            canonical = wanted.get(filename.lower())
            if not canonical:
                continue
            path = os.path.join(dirpath, filename)
            if _security.is_plain_file_within(source, path):  # links are skipped, not followed
                found.setdefault(canonical, []).append(path)
    return found


def _same_file(src: str, dest: str) -> bool:
    try:
        return os.path.samefile(src, dest)
    except OSError:
        return False


def _copy(source: str, src: str, dest: str) -> None:
    with _security.open_plain_file_within(source, src) as fin:
        if os.path.exists(dest) and os.path.samestat(os.fstat(fin.fileno()), os.stat(dest)):
            return  # already in place: opening dest for writing would truncate the source
        with open(dest, 'wb') as fout:
            shutil.copyfileobj(fin, fout, 1024 * 1024)
        info = os.fstat(fin.fileno())
    os.utime(dest, ns=(info.st_atime_ns, info.st_mtime_ns))


def cores_for(name: str) -> list[str]:
    return [core for core, names in BIOS_REQUIREMENTS.items() if name in names]


def _choose_source(sources: list[str], base: str) -> tuple[str | None, str]:
    """Pick which copy to import, and describe why.

    When several files share a firmware name and their contents differ, prefer
    the one the most packs agree on rather than whichever the walk reached
    first. Regional dumps and bad rips share filenames, and a consensus copy is
    a better default than an arbitrary one — `firmware.bin` for the DS was 4-to-1
    across three packs, where first-found could have gone either way depending
    on directory order.

    The disagreement is still reported. A silent pick is the thing to avoid.

    A copy that was replaced by a link (or became unreadable) since the scan is
    not a candidate. When none is left the answer is ``None``: the caller reports
    the firmware as not installed rather than handing back a path to follow.
    """
    if len(sources) == 1:
        return sources[0], ''

    by_digest: dict[str, list[str]] = {}
    for path in sources:
        try:
            by_digest.setdefault(_digest(path, base), []).append(path)
        except OSError:
            continue
    if not by_digest:
        return None, ''

    if len(by_digest) == 1:
        paths = next(iter(by_digest.values()))
        if len(paths) == len(sources):
            return paths[0], f'  [{len(sources)} identical copies]'
        return paths[0], f'  [{len(paths)} of {len(sources)} copies readable]'

    # Most copies wins; ties fall back to the earliest path for stability.
    best = max(by_digest.values(), key=lambda paths: (len(paths), -sources.index(paths[0])))
    others = len(by_digest) - 1
    return best[0], (
        f'  [{len(sources)} candidates, {len(by_digest)} differ — '
        f'using the {len(best)}-copy majority, {others} other version(s) ignored]'
    )


def _not_installed(name: str, why: str) -> None:
    print(f'  ! {name:<24} not installed: {why}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Folder to search (searched recursively)')
    parser.add_argument('--dest', default=os.environ.get('EMULATOR_BIOS_PATH') or DEFAULT_DEST)
    parser.add_argument('--apply', action='store_true', help='Actually copy (default is preview)')
    parser.add_argument('--overwrite', action='store_true', help='Replace files already present')
    parser.add_argument(
        '--require-all',
        action='store_true',
        help='Fail without writing unless every supported firmware file is selectable from source or already installed',
    )
    args = parser.parse_args()

    if not os.path.isdir(args.source):
        print(f'Source not found: {args.source}')
        return 1

    wanted = wanted_names()
    print(f'Searching {args.source} for {len(wanted)} known firmware filenames...')
    found = scan(args.source, wanted)

    present = set()
    if os.path.isdir(args.dest):
        present = {n.lower() for n in os.listdir(args.dest)
                   if os.path.isfile(os.path.join(args.dest, n))}

    to_copy: list[tuple[str, str]] = []
    refused: list[str] = []  # firmware that could not be installed: not a clean run
    for name in sorted(found):
        sources = found[name]
        already = name.lower() in present
        # Distinct contents under one name is worth saying out loud — regional
        # dumps and bad rips share filenames, and picking silently would make
        # the choice invisible.
        chosen, note = _choose_source(sources, args.source)
        # A --dest inside --source (or a hard link) finds the installed file
        # itself; --overwrite would then truncate it onto itself.
        in_place = chosen is not None and _same_file(chosen, os.path.join(args.dest, name))

        if (already and not args.overwrite) or in_place:
            print(f'  = {name:<24} already present{note}')
            continue
        if chosen is None:
            _not_installed(name, 'no copy of it in the source can be read any more')
            refused.append(name)
            continue
        print(f'  + {name:<24} {chosen}{note}')
        to_copy.append((chosen, os.path.join(args.dest, name)))

    missing = [n for n in sorted(wanted.values()) if n not in found and n.lower() not in present]
    if missing:
        print(f'\nNot found in the source ({len(missing)}):')
        for name in missing:
            cores = cores_for(name)
            hard = any(c in BIOS_HARD_REQUIRED_CORES for c in cores)
            flag = 'blocks play' if hard else 'optional'
            print(f'  - {name:<24} {", ".join(cores)} ({flag})')

    if args.require_all and (missing or refused):
        unavailable = len(missing) + len(refused)
        print(f'\nIncomplete firmware set — {unavailable} supported file(s) are unavailable; nothing was copied.')
        return 2

    status = 1 if refused else 0
    if not to_copy:
        print('\nNothing to copy.')
        return status

    if not args.apply:
        print(f'\nPreview only — {len(to_copy)} file(s) would be copied to {args.dest}\n'
              'Re-run with --apply to write them.')
        return status

    os.makedirs(args.dest, exist_ok=True)
    copied = 0
    for src, dest in to_copy:
        try:
            # What the scan vetted can be replaced before it is copied (a link
            # to /app/.env, say): _copy opens it through open_plain_file_within
            # and refuses anything that is no longer a plain file under the
            # source. shutil.copy2 would follow the link into the firmware
            # volume, which every member can download.
            _copy(args.source, src, dest)
        except OSError as exc:
            name = os.path.basename(dest)
            _not_installed(name, f'{src} was not copied ({exc.strerror or type(exc).__name__})')
            refused.append(name)
            status = 1
            continue
        copied += 1
    summary = f'\nCopied {copied} file(s) to {args.dest}'
    if refused:
        summary += f'\n{len(refused)} file(s) not installed: {", ".join(refused)}'
    print(summary)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
