#!/usr/bin/env python3
"""Import operator-supplied BIOS files from a local collection into the volume.

Oneirodex never downloads or bundles BIOS. This script does not fetch anything:
it looks through firmware *you already have* and copies the specific files the
libretro cores ask for into the BIOS volume, flattened, under the exact names
the cores look up. Admin → Emulators **Scan collection** / **Install matching
firmware** is the same walk with a version picker and a copyable missing report.

Preview by default, like the storage helpers and leaf-library proposer; nothing
is written until you pass --apply.

    python scripts/import_bios.py --source E:\\_bios
    python scripts/import_bios.py --source E:\\_bios --apply

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


def _copy(source: str, src: str, dest: str) -> None:
    with _security.open_plain_file_within(source, src) as fin:
        with open(dest, 'wb') as fout:
            shutil.copyfileobj(fin, fout, 1024 * 1024)
        info = os.fstat(fin.fileno())
    os.utime(dest, ns=(info.st_atime_ns, info.st_mtime_ns))


def cores_for(name: str) -> list[str]:
    return [core for core, names in BIOS_REQUIREMENTS.items() if name in names]


def _choose_source(sources: list[str], base: str) -> tuple[str, str]:
    """Pick which copy to import, and describe why.

    When several files share a firmware name and their contents differ, prefer
    the one the most packs agree on rather than whichever the walk reached
    first. Regional dumps and bad rips share filenames, and a consensus copy is
    a better default than an arbitrary one — `firmware.bin` for the DS was 4-to-1
    across three packs, where first-found could have gone either way depending
    on directory order.

    The disagreement is still reported. A silent pick is the thing to avoid.
    """
    if len(sources) == 1:
        return sources[0], ''

    by_digest: dict[str, list[str]] = {}
    for path in sources:
        try:
            by_digest.setdefault(_digest(path, base), []).append(path)
        except OSError:
            continue  # replaced by a link since the scan: not a candidate
    if not by_digest:
        return sources[0], '  [could not be read]'

    if len(by_digest) == 1:
        return sources[0], f'  [{len(sources)} identical copies]'

    # Most copies wins; ties fall back to the earliest path for stability.
    best = max(by_digest.values(), key=lambda paths: (len(paths), -sources.index(paths[0])))
    others = len(by_digest) - 1
    return best[0], (
        f'  [{len(sources)} candidates, {len(by_digest)} differ — '
        f'using the {len(best)}-copy majority, {others} other version(s) ignored]'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Folder to search (searched recursively)')
    parser.add_argument('--dest', default=os.environ.get('EMULATOR_BIOS_PATH') or DEFAULT_DEST)
    parser.add_argument('--apply', action='store_true', help='Actually copy (default is preview)')
    parser.add_argument('--overwrite', action='store_true', help='Replace files already present')
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
    for name in sorted(found):
        sources = found[name]
        already = name.lower() in present
        # Distinct contents under one name is worth saying out loud — regional
        # dumps and bad rips share filenames, and picking silently would make
        # the choice invisible.
        chosen, note = _choose_source(sources, args.source)

        if already and not args.overwrite:
            print(f'  = {name:<24} already present{note}')
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

    if not to_copy:
        print('\nNothing to copy.')
        return 0

    if not args.apply:
        print(f'\nPreview only — {len(to_copy)} file(s) would be copied to {args.dest}')
        print('Re-run with --apply to write them.')
        return 0

    os.makedirs(args.dest, exist_ok=True)
    for src, dest in to_copy:
        shutil.copy2(src, dest)
    print(f'\nCopied {len(to_copy)} file(s) to {args.dest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
