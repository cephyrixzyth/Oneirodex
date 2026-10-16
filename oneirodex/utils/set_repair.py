"""DAT repair preview -- report only (INSP-24, v11 cycle H1f).

Set completion (``set_completion.py``) answers *what is missing*. This module
answers the librarian's next question: *of the files I do own, which ones
does the DAT think are wrong?* It compares one platform's owned games with
the reference set(s) for that platform and sorts every owned file into one
bucket:

* ``rename_candidates`` -- the hash matches an entry, the filename does not.
  The dump is right; the name is not the set's name. The suggested name is
  the entry's, and nothing here renames anything.
* ``hash_mismatches`` -- the name matches an entry, the hash does not. A bad
  dump, a different revision, a header the set strips, or an overdump.
* ``clone_named`` -- the file is a *clone* entry (parent/clone data from
  INSP-5): a second dump of a game whose parent is owned or not.
* ``unknown`` -- neither hash nor name is in the set. A homebrew, a hack, a
  file the set never listed, or a DAT for a different region.
* ``verified`` is a count: hash and name both agree with the set. A MAME
  set names games by *description* while the files are named by machine
  short name, which the entry does not keep -- so on a ``mame`` set a hash
  hit is verified as it stands and never a rename candidate.

**Dry run, always.** The route is ``POST`` because the report is computed on
demand over the whole platform, but it writes nothing: no rename, no move, no
mark. A librarian reads the list and decides; the companion's own rename
tooling is a different slice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Library, ReferenceSet, ReferenceSetEntry
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.library_acl import apply_game_access_filters
from oneirodex.utils.set_completion import (
    normalize_region,
    normalize_set_title,
    validate_library_platform,
)

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


def _entry_index(entries: list[ReferenceSetEntry]) -> dict[str, dict[str, ReferenceSetEntry]]:
    by_hash: dict[str, ReferenceSetEntry] = {}
    by_name: dict[str, ReferenceSetEntry] = {}
    for entry in entries:
        for digest in (entry.crc, entry.md5, entry.sha1):
            if digest:
                by_hash.setdefault(digest.lower(), entry)
        if entry.normalized_name:
            by_name.setdefault(entry.normalized_name, entry)
    return {'hash': by_hash, 'name': by_name}


def _owned_rows(platform: str, user) -> list[Any]:
    query = (
        select(
            Game.uuid,
            Game.name,
            Game.full_disk_path,
            Game.file_crc,
            Game.file_md5,
            Game.file_sha1,
        )
        .join(Library, Game.library_uuid == Library.uuid)
        .filter(Library.platform == LibraryPlatform[platform])
        .order_by(Game.name)
    )
    return list(db.session.execute(apply_game_access_filters(query, user)).all())


def _basename_title(path: str | None) -> str:
    if not path:
        return ''
    return normalize_set_title(Path(path).stem)


def _hash_hit(row, by_hash: dict[str, ReferenceSetEntry]) -> tuple[ReferenceSetEntry | None, str | None]:
    for kind, digest in (('crc', row.file_crc), ('md5', row.file_md5), ('sha1', row.file_sha1)):
        if digest and digest.lower() in by_hash:
            return by_hash[digest.lower()], kind
    return None, None


def _item(row, **extra) -> dict[str, Any]:
    return {
        'game_uuid': row.uuid,
        'name': row.name,
        'path': row.full_disk_path,
        'file_name': Path(row.full_disk_path).name if row.full_disk_path else None,
        **extra,
    }


def repair_preview(
    *,
    library_platform: str,
    region: str | None,
    user,
    limit: int | None = None,
) -> dict[str, Any] | None:
    """The report described in the module docstring, or ``None`` when the
    platform has no reference set (for that region, when one is given)."""
    platform = validate_library_platform(library_platform)
    cap = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    query = select(ReferenceSet).filter_by(library_platform=platform)
    region_n = normalize_region(region) if region else None
    if region_n:
        query = query.filter_by(region=region_n)
    sets = list(db.session.execute(query).scalars().all())
    if not sets:
        return None

    entries = list(
        db.session.execute(
            select(ReferenceSetEntry).filter(ReferenceSetEntry.set_id.in_([s.id for s in sets]))
        ).scalars().all()
    )
    index = _entry_index(entries)
    source_by_set = {s.id: (s.source or '') for s in sets}
    owned = _owned_rows(platform, user)
    owned_titles = {normalize_set_title(r.name) for r in owned} | {_basename_title(r.full_disk_path) for r in owned}
    owned_titles.discard('')
    owned_hashes = {
        d.lower() for r in owned for d in (r.file_crc, r.file_md5, r.file_sha1) if d
    }

    def parent_owned(parent: str) -> bool:
        norm = normalize_set_title(parent)
        if norm in owned_titles:
            return True
        parent_entry = index['name'].get(norm)
        if parent_entry is None:
            return False
        return any(d and d.lower() in owned_hashes for d in (parent_entry.crc, parent_entry.md5, parent_entry.sha1))

    buckets: dict[str, list[dict[str, Any]]] = {
        'rename_candidates': [],
        'hash_mismatches': [],
        'clone_named': [],
        'unknown': [],
    }
    verified = 0
    unhashed = 0
    for row in owned:
        has_hash = bool(row.file_crc or row.file_md5 or row.file_sha1)
        file_title = _basename_title(row.full_disk_path) or normalize_set_title(row.name)
        entry, kind = _hash_hit(row, index['hash']) if has_hash else (None, None)
        name_entry = index['name'].get(file_title) or index['name'].get(normalize_set_title(row.name))
        target = entry or name_entry
        parent = getattr(target, 'parent_name', None) if target else None
        if parent:
            buckets['clone_named'].append(_item(
                row,
                entry_name=target.name,
                clone_of=parent,
                parent_owned=parent_owned(parent),
                matched_by=kind or 'name',
            ))
            continue
        if entry is not None:
            names_by_description = source_by_set.get(entry.set_id) == 'mame'
            if entry.normalized_name and entry.normalized_name != file_title and not names_by_description:
                buckets['rename_candidates'].append(_item(
                    row, matched_by=kind, suggested_name=entry.name, entry_crc=entry.crc,
                ))
            else:
                verified += 1
            continue
        if name_entry is not None:
            if not has_hash:
                unhashed += 1
                continue
            buckets['hash_mismatches'].append(_item(
                row,
                entry_name=name_entry.name,
                entry_crc=name_entry.crc,
                file_crc=row.file_crc,
                note='name matches the set, hash does not -- bad dump, other revision, header or overdump',
            ))
            continue
        buckets['unknown'].append(_item(row, hashed=has_hash))

    counts = {key: len(rows) for key, rows in buckets.items()}
    truncated = any(len(rows) > cap for rows in buckets.values())
    return {
        'library_platform': platform,
        'region': region_n,
        'sets': [
            {'id': s.id, 'name': s.name, 'region': s.region, 'source': s.source, 'entry_count': s.entry_count}
            for s in sets
        ],
        'owned_total': len(owned),
        'verified': verified,
        'unhashed_name_matches': unhashed,
        'counts': counts,
        'truncated': truncated,
        'dry_run': True,
        **{key: rows[:cap] for key, rows in buckets.items()},
    }
