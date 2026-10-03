"""Keep library records pointing at a folder after it is renamed on disk."""

from __future__ import annotations

import os

from sqlalchemy import or_, select

from oneirodex import db
from oneirodex.models import Game, GameExtra, GameUpdate, UnmatchedFolder


def _clean(path: str | None) -> str:
    """Collapsed separators ('/'), no trailing slash; case preserved."""
    if not path:
        return ''
    return os.path.normpath(path).replace('\\', '/').rstrip('/')


def _key(path: str | None) -> str:
    """Comparison key: :func:`_clean` plus the platform's case rules.

    Stored paths and the renamed folder's path are written by different code
    (scan, admin edits, the rename plan), so they can differ by a trailing
    slash, doubled or mixed separators, or case on a case-insensitive disk,
    while naming the same folder. Exact string equality missed those rows.
    """
    return os.path.normcase(_clean(path)).replace('\\', '/')


def _moved(path: str | None, old: str, new: str) -> str | None:
    """*path* rewritten from under *old* to under *new*, or None when unaffected."""
    if not path or not old:
        return None
    clean, old_clean = _clean(path), _clean(old)
    key, old_key = _key(path), _key(old)
    if not old_key:
        return None
    new_clean = new.rstrip('/\\')
    if key == old_key:
        return new_clean
    if key.startswith(old_key + '/'):
        # normcase never changes length, so the slice lines up; the tail keeps
        # the stored spelling.
        tail = clean[len(old_clean) + 1:]
        sep = '\\' if '\\' in new_clean and '/' not in new_clean else '/'
        return new_clean + sep + tail.replace('/', sep)
    return None


def _like_escape(text: str) -> str:
    return text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def repoint_paths(old: str, new: str) -> int:
    """Rewrite every stored path at or under *old* to the same place under *new*.

    Covers games, their updates and extras, and unmatched folders. Candidate rows
    are fetched with a case-insensitive, wildcard-escaped prefix match and then
    confirmed with :func:`_moved`. The caller commits. Returns how many rows
    changed.
    """
    changed = 0
    prefix = _like_escape(old.rstrip('/\\'))
    targets = (
        (Game, Game.full_disk_path),
        (GameUpdate, GameUpdate.file_path),
        (GameExtra, GameExtra.file_path),
        (UnmatchedFolder, UnmatchedFolder.folder_path),
    )
    for model, column in targets:
        rows = db.session.execute(
            select(model).where(or_(column.ilike(prefix, escape='\\'), column.ilike(prefix + '%', escape='\\')))
        ).scalars().all()
        for row in rows:
            moved = _moved(getattr(row, column.key), old, new)
            if moved is not None:
                setattr(row, column.key, moved)
                changed += 1
    return changed
