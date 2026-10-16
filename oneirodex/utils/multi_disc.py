"""BE-DET-5 — multi-disc / cue+bin grouping helpers.

Clear sibling dumps (same cleaned title, differing disc index) attach to one
Game. Ambiguous collisions stay Duplicate / Unmatched (no wrong merges).
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, GameExtra
from oneirodex.utils.rom_name_peel import (
    capture_disc_index,
    parse_console_rom_label,
)

# Disc-image companions for a cue sheet (play bundling already uses this set).
CUE_COMPANION_EXTS = frozenset({'.bin', '.img', '.iso', '.raw', '.wav'})
DISC_EXTRA_KIND = 'disc'


def _basename(path_or_name: str | None) -> str:
    raw = (path_or_name or '').strip()
    if not raw:
        return ''
    return os.path.basename(raw.replace('\\', '/'))


def _stem(filename: str) -> str:
    base = _basename(filename)
    root, _ext = os.path.splitext(base)
    return root


def _ext(filename: str) -> str:
    return os.path.splitext(_basename(filename))[1].lower()


def parse_disc_fields(path_or_name: str | None) -> dict[str, Any]:
    """Extract disc_index (+ cleaned_name) from a dump path/basename."""
    label = _basename(path_or_name)
    if not label:
        return {'disc_index': None, 'cleaned_name': '', 'raw': ''}
    peel = parse_console_rom_label(label)
    return {
        'disc_index': peel.get('disc_index'),
        'cleaned_name': (peel.get('cleaned_name') or '').strip(),
        'raw': peel.get('raw') or label,
    }


def apply_disc_fields(
    game,
    path_or_name: str | None = None,
    *,
    peel: dict[str, Any] | None = None,
) -> None:
    """Persist disc_index on a Game from peel capture or path parse."""
    if isinstance(peel, dict) and 'disc_index' in peel:
        idx = peel.get('disc_index')
    else:
        source = path_or_name or getattr(game, 'full_disk_path', None) or ''
        idx = capture_disc_index(_basename(source))
    try:
        idx_int = int(idx) if idx is not None else None
    except (TypeError, ValueError):
        idx_int = None
    if idx_int is not None and idx_int <= 0:
        idx_int = None
    game.disc_index = idx_int
    if idx_int is not None:
        current = getattr(game, 'disc_count', None)
        try:
            current_int = int(current) if current is not None else 0
        except (TypeError, ValueError):
            current_int = 0
        game.disc_count = max(current_int, 1)


def is_cue_bin_companion(filename: str, sibling_names: set[str] | list[str]) -> bool:
    """True when ``filename`` is a cue companion (.bin/…) with a matching .cue stem."""
    ext = _ext(filename)
    if ext not in CUE_COMPANION_EXTS:
        return False
    stem = _stem(filename)
    if not stem:
        return False
    siblings = {n.casefold() for n in sibling_names}
    return f'{stem}.cue'.casefold() in siblings


def filter_cue_bin_companions(entries: list[dict]) -> list[dict]:
    """Drop cue companions so a cue+bin pair is one scan identity.

    ``entries`` items need ``full_path`` (and optional ``name``). Matching is
    by directory sibling list — only companions in the same folder are dropped.
    """
    if not entries:
        return []
    by_dir: dict[str, list[dict]] = {}
    for entry in entries:
        path = entry.get('full_path') or ''
        parent = os.path.dirname(path.replace('\\', '/')) or '.'
        by_dir.setdefault(parent, []).append(entry)

    kept: list[dict] = []
    for _parent, group in by_dir.items():
        names = [_basename(e.get('full_path') or e.get('name') or '') for e in group]
        name_set = [n for n in names if n]
        for entry, name in zip(group, names):
            if name and is_cue_bin_companion(name, name_set):
                continue
            kept.append(entry)
    return kept


def cleaned_titles_match(a: str | None, b: str | None) -> bool:
    left = (a or '').strip().casefold()
    right = (b or '').strip().casefold()
    return bool(left and right and left == right)


def is_clear_multi_disc_sibling(
    *,
    new_disc_index: int | None,
    new_cleaned_name: str | None,
    existing_disc_index: int | None,
    existing_cleaned_name: str | None,
    existing_path: str | None = None,
) -> bool:
    """True only when both sides have disc tokens, same cleaned title, different index.

    Ambiguous (one side missing disc token, same index, or title mismatch) → False.
    """
    if new_disc_index is None:
        return False
    existing_idx = existing_disc_index
    if existing_idx is None and existing_path:
        existing_idx = capture_disc_index(_basename(existing_path))
    if existing_idx is None:
        return False
    try:
        new_i = int(new_disc_index)
        existing_i = int(existing_idx)
    except (TypeError, ValueError):
        return False
    if new_i <= 0 or existing_i <= 0 or new_i == existing_i:
        return False
    existing_clean = existing_cleaned_name
    if not existing_clean and existing_path:
        existing_clean = parse_disc_fields(existing_path).get('cleaned_name')
    return cleaned_titles_match(new_cleaned_name, existing_clean)


def _known_disc_indices(game) -> set[int]:
    indices: set[int] = set()
    primary = getattr(game, 'disc_index', None)
    if primary is not None:
        try:
            indices.add(int(primary))
        except (TypeError, ValueError):
            pass
    path_idx = capture_disc_index(_basename(getattr(game, 'full_disk_path', None)))
    if path_idx is not None:
        indices.add(path_idx)
    game_uuid = getattr(game, 'uuid', None)
    extras: list = []
    if game_uuid:
        extras = list(
            db.session.execute(
                select(GameExtra).filter_by(
                    game_uuid=game_uuid, extra_kind=DISC_EXTRA_KIND
                )
            ).scalars().all()
        )
    else:
        raw = getattr(game, 'extras', None) or []
        try:
            extras = [e for e in raw if getattr(e, 'extra_kind', None) == DISC_EXTRA_KIND]
        except TypeError:
            extras = []
    for extra in extras:
        eidx = getattr(extra, 'disc_index', None)
        if eidx is not None:
            try:
                indices.add(int(eidx))
            except (TypeError, ValueError):
                pass
        pidx = capture_disc_index(_basename(getattr(extra, 'file_path', None)))
        if pidx is not None:
            indices.add(pidx)
    return indices


def refresh_disc_count(game) -> None:
    """Set disc_count from primary + disc extras (and path tokens)."""
    indices = _known_disc_indices(game)
    if not indices:
        if getattr(game, 'disc_index', None) is None:
            game.disc_count = None
        else:
            game.disc_count = 1
        return
    game.disc_count = max(len(indices), max(indices))


def attach_disc_sibling(
    existing_game,
    full_disk_path: str,
    *,
    disc_index: int | None,
    peel: dict[str, Any] | None = None,
) -> GameExtra | None:
    """Attach ``full_disk_path`` as a disc GameExtra on ``existing_game``.

    Idempotent on file_path. Prefer lower disc_index as Game.full_disk_path
    (primary play path); demote the previous primary into a disc extra when
    swapping.
    """
    if not existing_game or not full_disk_path:
        return None
    path = full_disk_path
    idx = disc_index
    if idx is None and peel is not None:
        idx = peel.get('disc_index')
    if idx is None:
        idx = capture_disc_index(_basename(path))
    try:
        idx_int = int(idx) if idx is not None else None
    except (TypeError, ValueError):
        idx_int = None

    # Already attached?
    existing_extra = db.session.execute(
        select(GameExtra).filter_by(game_uuid=existing_game.uuid, file_path=path)
    ).scalar_one_or_none()
    if existing_extra is not None:
        if idx_int is not None:
            existing_extra.extra_kind = DISC_EXTRA_KIND
            existing_extra.disc_index = idx_int
        refresh_disc_count(existing_game)
        db.session.flush()
        return existing_extra

    primary_path = getattr(existing_game, 'full_disk_path', None) or ''
    primary_idx = getattr(existing_game, 'disc_index', None)
    if primary_idx is None:
        primary_idx = capture_disc_index(_basename(primary_path))

    # Same path as primary — nothing to attach.
    if primary_path and os.path.normcase(primary_path) == os.path.normcase(path):
        apply_disc_fields(existing_game, path, peel=peel)
        refresh_disc_count(existing_game)
        db.session.flush()
        return None

    swap_primary = (
        idx_int is not None
        and primary_path
        and (primary_idx is None or idx_int < int(primary_idx))
    )

    if swap_primary:
        # Demote current primary to a disc extra, then point Game at the
        # lower-index disc (usual Disc 1 play path).
        demote = db.session.execute(
            select(GameExtra).filter_by(
                game_uuid=existing_game.uuid, file_path=primary_path
            )
        ).scalar_one_or_none()
        if demote is None:
            demote = GameExtra(
                game_uuid=existing_game.uuid,
                file_path=primary_path,
                extra_kind=DISC_EXTRA_KIND,
                disc_index=int(primary_idx) if primary_idx is not None else None,
            )
            db.session.add(demote)
        else:
            demote.extra_kind = DISC_EXTRA_KIND
            if primary_idx is not None:
                demote.disc_index = int(primary_idx)
        existing_game.full_disk_path = path
        existing_game.disc_index = idx_int
        refresh_disc_count(existing_game)
        db.session.flush()
        return demote

    extra = GameExtra(
        game_uuid=existing_game.uuid,
        file_path=path,
        extra_kind=DISC_EXTRA_KIND,
        disc_index=idx_int,
    )
    db.session.add(extra)
    if getattr(existing_game, 'disc_index', None) is None and primary_idx is not None:
        existing_game.disc_index = int(primary_idx)
    elif getattr(existing_game, 'disc_index', None) is None and idx_int is not None:
        # Primary had no token; keep primary path, record its unknown index as None.
        pass
    refresh_disc_count(existing_game)
    db.session.flush()
    return extra


def try_attach_multi_disc_sibling(
    *,
    existing_game,
    full_disk_path: str,
    game_name: str | None = None,
    peel: dict[str, Any] | None = None,
) -> bool:
    """Attach when grouping is clear; return True if attached (caller treats as matched)."""
    if existing_game is None or not full_disk_path:
        return False
    label = game_name or _basename(full_disk_path)
    new_fields = peel if isinstance(peel, dict) and 'disc_index' in peel else parse_disc_fields(
        label if '(' in (label or '') else full_disk_path
    )
    # Prefer full path when label lacks disc token (cleaned scan name).
    if new_fields.get('disc_index') is None:
        new_fields = parse_disc_fields(full_disk_path)

    existing_clean = parse_disc_fields(
        getattr(existing_game, 'full_disk_path', None)
    ).get('cleaned_name')
    if not is_clear_multi_disc_sibling(
        new_disc_index=new_fields.get('disc_index'),
        new_cleaned_name=new_fields.get('cleaned_name'),
        existing_disc_index=getattr(existing_game, 'disc_index', None),
        existing_cleaned_name=existing_clean,
        existing_path=getattr(existing_game, 'full_disk_path', None),
    ):
        return False

    attach_disc_sibling(
        existing_game,
        full_disk_path,
        disc_index=new_fields.get('disc_index'),
        peel=new_fields if isinstance(peel, dict) else None,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return False
    return True


def disc_browse_fields(game, extras=None) -> dict[str, Any]:
    """JSON field map for browse/details (disc chips on the details page)."""
    primary_idx = getattr(game, 'disc_index', None)
    disc_count = getattr(game, 'disc_count', None)
    discs: list[dict[str, Any]] = []
    if primary_idx is not None or disc_count:
        discs.append({
            'disc_index': primary_idx,
            'path': getattr(game, 'full_disk_path', None),
            'is_primary': True,
        })
    if extras is None:
        raw_extras = getattr(game, 'extras', None)
        try:
            extra_iter = list(raw_extras) if raw_extras is not None else []
        except TypeError:
            extra_iter = []
    else:
        extra_iter = list(extras)
    for extra in extra_iter:
        if getattr(extra, 'extra_kind', None) != DISC_EXTRA_KIND:
            continue
        discs.append({
            'disc_index': getattr(extra, 'disc_index', None),
            'path': getattr(extra, 'file_path', None),
            'uuid': getattr(extra, 'uuid', None),
            'is_primary': False,
        })
    discs.sort(
        key=lambda d: (
            d.get('disc_index') is None,
            d.get('disc_index') if d.get('disc_index') is not None else 999,
        )
    )
    return {
        'disc_index': primary_idx,
        'disc_count': disc_count,
        'discs': discs,
        'is_multi_disc': bool(disc_count and int(disc_count) > 1) or len(discs) > 1,
    }
