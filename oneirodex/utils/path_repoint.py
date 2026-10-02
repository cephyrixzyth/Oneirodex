"""Keep library records pointing at a folder after it is renamed on disk."""

from __future__ import annotations

import os

from sqlalchemy import or_, select

from oneirodex import db
from oneirodex.models import Game, GameExtra, GameUpdate, UnmatchedFolder


def _moved(path: str | None, old: str, new: str) -> str | None:
    """*path* rewritten from under *old* to under *new*, or None when unaffected."""
    if not path:
        return None
    if path == old:
        return new
    for sep in {os.sep, '/'}:
        prefix = old.rstrip(sep) + sep
        if path.startswith(prefix):
            return new.rstrip(sep) + sep + path[len(prefix):]
    return None


def repoint_paths(old: str, new: str) -> int:
    """Rewrite every stored path at or under *old* to the same place under *new*.

    Covers games, their updates and extras, and unmatched folders. The caller
    commits. Returns how many rows changed.
    """
    changed = 0
    like = old.rstrip('/\\') + '%'
    targets = (
        (Game, Game.full_disk_path),
        (GameUpdate, GameUpdate.file_path),
        (GameExtra, GameExtra.file_path),
        (UnmatchedFolder, UnmatchedFolder.folder_path),
    )
    for model, column in targets:
        rows = db.session.execute(
            select(model).where(or_(column == old, column.like(like)))
        ).scalars().all()
        for row in rows:
            moved = _moved(getattr(row, column.key), old, new)
            if moved is not None:
                setattr(row, column.key, moved)
                changed += 1
    return changed
