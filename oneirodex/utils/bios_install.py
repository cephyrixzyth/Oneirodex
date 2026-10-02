"""Import emulator firmware from an operator-supplied folder.

``scripts/import_bios.py`` has always known how to find firmware in a local
collection and copy the files the cores ask for. Boot still tops up from
``BIOS_IMPORT_SOURCE`` without replacing files already on the volume.

The admin Emulators page uses the same scan as the script: recursive walk,
majority default when several dumps share a name, and an explicit picker so a
disagreement is never silent. Oneirodex never downloads BIOS.
"""

from __future__ import annotations

import hashlib
import os
import shutil

from flask import g, has_request_context

from oneirodex.utils.emulator_bios import (
    BIOS_HARD_REQUIRED_CORES,
    BIOS_REQUIREMENTS,
    bios_root,
    bios_status_for_platforms,
)
from oneirodex.utils.security import (
    get_allowed_base_directories,
    is_plain_file_within,
    open_plain_file_within,
)


def wanted_firmware_names() -> dict[str, str]:
    """Lowercased filename -> canonical name a core looks up."""
    out: dict[str, str] = {}
    for names in BIOS_REQUIREMENTS.values():
        for name in names:
            out.setdefault(name.lower(), name)
    return out


def firmware_import_allowed_bases(app) -> list:
    """Library roots plus the configured BIOS collection, if any.

    A dump pack often lives next to the games share *or* on a dedicated folder
    named by ``BIOS_IMPORT_SOURCE``. Either is a legitimate scan root; anything
    else stays outside the path allowlist.
    """
    bases = list(get_allowed_base_directories(app))
    configured = app.config.get('BIOS_IMPORT_SOURCE')
    if configured:
        bases.append(configured)
    return bases


def scan_for_firmware(source: str, wanted: dict[str, str] | None = None) -> dict[str, list[str]]:
    """Every path under *source* whose filename is one a core asks for.

    Walks subdirectories: collections arrive organised per system, and the flat
    listing that missed them is the same bug the BIOS *discovery* fix addressed
    on the serving side.
    """
    names = wanted if wanted is not None else wanted_firmware_names()
    found: dict[str, list[str]] = {}
    for dirpath, _dirnames, filenames in os.walk(source):
        for filename in filenames:
            canonical = names.get(filename.lower())
            if not canonical:
                continue
            path = os.path.join(dirpath, filename)
            # A collection folder is somebody's share: ``scph5501.bin -> /app/.env``
            # would be copied into the firmware volume, which every signed-in
            # member can read. Links (and anything that resolves outside the
            # collection) are not firmware; they are skipped, not followed.
            if not is_plain_file_within(source, path):
                continue
            found.setdefault(canonical, []).append(path)
    return found


def firmware_digest(path: str, base: str | None = None) -> str:
    """SHA-1 of a firmware file. With *base*, the file must still be a plain
    file under it when it is opened (see ``open_plain_file_within``)."""
    h = hashlib.sha1()
    handle = open_plain_file_within(base, path) if base is not None else open(path, 'rb')
    with handle as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _copy_firmware(source_root: str, src: str, dest_path: str) -> None:
    """Copy one scanned firmware file into the volume.

    Opens the source through ``open_plain_file_within`` and copies from that
    descriptor, so a file swapped for a link after the scan is refused instead
    of followed. Raises ``OSError`` in that case; both callers already treat
    that as "could not copy this one".
    """
    with open_plain_file_within(source_root, src) as fin:
        with open(dest_path, 'wb') as fout:
            shutil.copyfileobj(fin, fout, 1024 * 1024)
        info = os.fstat(fin.fileno())
    os.utime(dest_path, ns=(info.st_atime_ns, info.st_mtime_ns))


def _relpath(path: str, source_root: str) -> str:
    try:
        rel = os.path.relpath(path, source_root)
    except ValueError:
        return os.path.basename(path)
    return rel.replace('\\', '/')


def _loadable_names(dest: str) -> set[str]:
    if not os.path.isdir(dest):
        return set()
    return {
        name.lower()
        for name in os.listdir(dest)
        if os.path.isfile(os.path.join(dest, name))
    }


def _systems_index() -> dict[str, list[dict]]:
    """Canonical firmware name -> platforms that ask for it."""
    index: dict[str, list[dict]] = {}
    for row in bios_status_for_platforms():
        hard = any(core in BIOS_HARD_REQUIRED_CORES for core in row['cores'])
        info = {
            'platform': row['platform'],
            'label': row['label'],
            'hard': hard,
        }
        for name in row['required']:
            bucket = index.setdefault(name, [])
            if not any(item['platform'] == info['platform'] for item in bucket):
                bucket.append(info)
    return index


def _systems_for(name: str, index: dict[str, list[dict]]) -> list[dict]:
    rows = list(index.get(name) or [])
    if rows:
        return rows
    cores = [core for core, names in BIOS_REQUIREMENTS.items() if name in names]
    return [
        {
            'platform': core,
            'label': core,
            'hard': core in BIOS_HARD_REQUIRED_CORES,
        }
        for core in cores
    ]


def versions_for(sources: list[str], source_root: str) -> tuple[list[dict], str, str]:
    """Group copies of one firmware name by content.

    One copy: no hash (the walk already named it). Several identical hashes:
    first path, with a note. Differing hashes: majority count wins as the
    default, and every version is returned so the operator can pick.
    """
    if not sources:
        return [], '', ''
    if len(sources) == 1:
        path = sources[0]
        rel = _relpath(path, source_root)
        return (
            [{
                'digest': '',
                'count': 1,
                'size': os.path.getsize(path),
                'paths': [rel],
            }],
            rel,
            '',
        )

    by_digest: dict[str, list[str]] = {}
    for path in sources:
        try:
            digest = firmware_digest(path, source_root)
        except OSError:
            continue  # swapped for a link (or removed) since the scan: not a candidate
        by_digest.setdefault(digest, []).append(path)
    if not by_digest:
        return [], '', ''

    versions: list[dict] = []
    for digest, paths in by_digest.items():
        versions.append({
            'digest': digest,
            'count': len(paths),
            'size': os.path.getsize(paths[0]),
            'paths': [_relpath(p, source_root) for p in paths[:8]],
        })
    versions.sort(key=lambda row: (-row['count'], row['digest']))
    default = versions[0]['digest']
    if len(versions) == 1:
        note = f'{len(sources)} identical copies'
    else:
        note = (
            f'{len(sources)} candidates, {len(versions)} differ — '
            f'default is the {versions[0]["count"]}-copy majority'
        )
    return versions, default, note


def _digest_or_none(path: str, source_root: str) -> str | None:
    try:
        return firmware_digest(path, source_root)
    except OSError:
        return None


def _resolve_choice(sources: list[str], source_root: str, choice: str | None) -> str | None:
    if not sources:
        return None
    if not choice:
        if len(sources) == 1:
            return sources[0]
        versions, default, _note = versions_for(sources, source_root)
        if default and len(default) == 40:
            for path in sources:
                if _digest_or_none(path, source_root) == default:
                    return path
        if versions and versions[0].get('paths'):
            return _resolve_choice(sources, source_root, versions[0]['paths'][0])
        return sources[0]

    token = choice.strip().replace('\\', '/')
    digest_like = len(token) == 40 and all(c in '0123456789abcdef' for c in token.lower())
    if digest_like:
        want = token.lower()
        for path in sources:
            if _digest_or_none(path, source_root) == want:
                return path
        return None
    for path in sources:
        if _relpath(path, source_root) == token:
            return path
    return None


def _clear_bios_file_cache() -> None:
    if has_request_context() and hasattr(g, '_bios_files_cache'):
        del g._bios_files_cache


def volume_missing_markdown() -> str:
    """What the firmware volume still lacks, with no collection overlay."""
    return build_missing_markdown(
        source='',
        found_names=set(),
        loadable=_loadable_names(bios_root()),
        conflicts=[],
    )


def build_missing_markdown(
    *,
    source: str,
    found_names: set[str],
    loadable: set[str],
    conflicts: list[dict],
) -> str:
    """Copyable markdown for the missing-firmware dialog.

    A platform that already has *any* of its files (on the volume or in the
    collection) is not listed as blocking — region variants are interchangeable.
    Leftover names go under optional.
    """
    found_lower = {name.lower() for name in found_names}
    blocking: list[str] = []
    optional: list[str] = []
    for row in bios_status_for_platforms():
        needed = list(row['required'])
        have = [
            name for name in needed
            if name.lower() in loadable or name.lower() in found_lower
        ]
        lack = [
            name for name in needed
            if name.lower() not in loadable and name.lower() not in found_lower
        ]
        if not lack:
            continue
        hard = any(core in BIOS_HARD_REQUIRED_CORES for core in row['cores'])
        line = f"- **{row['label']}** — {', '.join(f'`{name}`' for name in lack)}"
        if not have and hard:
            blocking.append(line)
        else:
            optional.append(line)

    lines = [
        '# Firmware still needed',
        '',
        'Oneirodex never downloads BIOS. Supply dumps you are entitled to use.',
        '',
    ]
    if source:
        lines.append(f'Scanned `{source}`.')
        lines.append('')
    if not blocking and not optional:
        lines.append(
            'Every named file the service asks for is either in this collection '
            'or already on the firmware volume.'
        )
        lines.append('')
    else:
        if blocking:
            lines.extend([
                '## Blocking',
                '',
                'These systems cannot boot until you add at least one of the listed files.',
                '',
                *blocking,
                '',
            ])
        if optional:
            lines.extend([
                '## Optional',
                '',
                'Improves accuracy, or extra region dumps; the system can still play.',
                '',
                *optional,
                '',
            ])
    if conflicts:
        lines.extend([
            '## Version conflicts',
            '',
            'Same filename, different contents. Choose which dump to install — '
            'cores read one file per name from the firmware root, so a shared '
            'filename is one dump for every system that uses it.',
            '',
        ])
        for conflict in conflicts:
            labels = ', '.join(
                item['label'] for item in (conflict.get('systems') or [])
            )
            extra = f' ({labels})' if labels else ''
            n_versions = len(conflict.get('versions') or [])
            lines.append(f"- `{conflict['name']}` — {n_versions} versions{extra}")
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def plan_firmware_import(source: str, dest: str | None = None) -> dict:
    """Preview a collection scan. Nothing is written."""
    if dest is None:
        dest = bios_root()

    wanted = wanted_firmware_names()
    found = scan_for_firmware(source, wanted)
    loadable = _loadable_names(dest)
    index = _systems_index()

    matches: list[dict] = []
    conflicts: list[dict] = []
    for canonical, paths in sorted(found.items()):
        versions, chosen, note = versions_for(paths, source)
        systems = _systems_for(canonical, index)
        already = canonical.lower() in loadable
        distinct = [row for row in versions if row.get('digest')]
        conflict = len({row['digest'] for row in distinct}) > 1
        row = {
            'name': canonical,
            'already': already,
            'versions': versions,
            'chosen': chosen,
            'note': note,
            'systems': systems,
            'blocking': any(item.get('hard') for item in systems),
        }
        matches.append(row)
        if conflict:
            conflicts.append({
                'name': canonical,
                'versions': versions,
                'systems': systems,
                'chosen': chosen,
            })

    missing: list[dict] = []
    seen: set[str] = set()
    for canonical in wanted.values():
        if canonical in seen:
            continue
        seen.add(canonical)
        if canonical in found or canonical.lower() in loadable:
            continue
        systems = _systems_for(canonical, index)
        missing.append({
            'name': canonical,
            'systems': systems,
            'blocking': any(item.get('hard') for item in systems),
        })

    markdown = build_missing_markdown(
        source=source,
        found_names=set(found),
        loadable=loadable,
        conflicts=conflicts,
    )
    return {
        'source': source,
        'wanted_count': len(wanted),
        'matches': matches,
        'missing': missing,
        'conflicts': conflicts,
        'copy_count': sum(1 for row in matches if not row['already']),
        'already_count': sum(1 for row in matches if row['already']),
        'conflict_count': len(conflicts),
        'missing_markdown': markdown,
    }


def apply_firmware_import(
    source: str,
    dest: str | None = None,
    *,
    selections: dict[str, str] | None = None,
    skipped: list[str] | None = None,
    overwrite: bool = False,
) -> dict:
    """Copy selected firmware into the BIOS root, flattened to canonical names."""
    if dest is None:
        dest = bios_root()
    os.makedirs(dest, exist_ok=True)

    skipped_set = {name.lower() for name in (skipped or [])}
    picks = selections or {}
    wanted = wanted_firmware_names()
    found = scan_for_firmware(source, wanted)
    present = _loadable_names(dest)

    copied: list[str] = []
    skipped_rows: list[str] = []
    unresolved: list[str] = []

    for canonical, paths in sorted(found.items()):
        if canonical.lower() in skipped_set:
            skipped_rows.append(canonical)
            continue
        if canonical.lower() in present and not overwrite:
            skipped_rows.append(canonical)
            continue
        choice = picks.get(canonical) or picks.get(canonical.lower())
        chosen_path = _resolve_choice(paths, source, choice)
        if chosen_path is None:
            unresolved.append(canonical)
            continue
        try:
            _copy_firmware(source, chosen_path, os.path.join(dest, canonical))
            copied.append(canonical)
        except OSError:
            unresolved.append(canonical)

    _clear_bios_file_cache()
    plan = plan_firmware_import(source, dest)
    return {
        'copied': copied,
        'skipped': skipped_rows,
        'unresolved': unresolved,
        'copied_count': len(copied),
        'missing_markdown': plan['missing_markdown'],
        'matches': plan['matches'],
        'missing': plan['missing'],
        'conflicts': plan['conflicts'],
        'conflict_count': plan['conflict_count'],
    }


def import_bios_from(source: str, dest: str | None = None) -> int:
    """Copy missing firmware from *source* into the BIOS root. Returns count.

    When several files under *source* share a firmware name, the first the walk
    reaches wins. The interactive plan does better — it prefers the copy the
    most packs agree on and *reports* the disagreement — but that is a
    judgement worth showing an operator rather than making silently at boot. A
    boot import fills obvious gaps; resolving a conflict stays interactive.
    """
    if dest is None:
        dest = bios_root()

    os.makedirs(dest, exist_ok=True)
    present = _loadable_names(dest)

    copied = 0
    for canonical, sources in sorted(scan_for_firmware(source).items()):
        if canonical.lower() in present:
            continue
        try:
            _copy_firmware(source, sources[0], os.path.join(dest, canonical))
            copied += 1
        except OSError:
            # One unreadable file should not abandon the rest of the import.
            continue

    return copied
