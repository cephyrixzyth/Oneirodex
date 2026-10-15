"""List downloadable versions for a game (base + updates + extras)."""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, GameExtra, GameUpdate


def _basename_label(path: str, fallback: str) -> str:
    name = os.path.basename(path.rstrip('\\/')) if path else ''
    return name or fallback


def _path_status(path: str | None) -> tuple[bool, bool, int | None]:
    """Return ``(path_missing, downloadable, size)`` for a version path.

    Empty/blank paths and missing files/dirs are marked missing and not
    downloadable. When a regular file exists, ``size`` is filled via
    ``os.path.getsize``. Directories that exist are downloadable with
    ``size=None`` (caller may supply a stored size, e.g. base game).
    """
    if path is None or not str(path).strip():
        return True, False, None
    try:
        if os.path.isfile(path):
            return False, True, os.path.getsize(path)
        if os.path.isdir(path):
            return False, True, None
    except OSError:
        return True, False, None
    return True, False, None


def _version_row(
    *,
    kind: str,
    uuid: str,
    label: str,
    is_default: bool,
    file_path: str | None,
    stored_size: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    path_missing, downloadable, measured_size = _path_status(file_path)
    size = measured_size if measured_size is not None else (None if path_missing else stored_size)
    row: dict[str, Any] = {
        'kind': kind,
        'id': uuid,
        'uuid': uuid,
        'label': label,
        'is_default': is_default,
        'file_path': file_path,
        'size': size,
        'path_missing': path_missing,
        'downloadable': downloadable,
    }
    row.update(extra)
    return row


def list_game_versions(game: Game) -> list[dict[str, Any]]:
    """Return selectable download versions for the game.

    Base is always ``is_default=True``. There is no persisted default-version
    column on ``GameUpdate`` / ``GameExtra``; do not invent schema here —
    UI should treat list ``is_default`` as base-only until a later wave.
    """
    versions: list[dict[str, Any]] = [
        _version_row(
            kind='base',
            uuid=game.uuid,
            label='Base game',
            is_default=True,
            file_path=game.full_disk_path,
            stored_size=game.size,
        )
    ]

    updates = db.session.execute(
        select(GameUpdate).filter_by(game_uuid=game.uuid).order_by(GameUpdate.created_at.desc())
    ).scalars().all()
    for update in updates:
        versions.append(
            _version_row(
                kind='update',
                uuid=update.uuid,
                label=f'Update: {_basename_label(update.file_path, update.uuid[:8])}',
                is_default=False,
                file_path=update.file_path,
            )
        )

    extras = db.session.execute(
        select(GameExtra).filter_by(game_uuid=game.uuid).order_by(GameExtra.created_at.desc())
    ).scalars().all()
    for extra in extras:
        is_patch = getattr(extra, 'extra_kind', None) == 'translation_patch'
        label_prefix = 'Translation patch' if is_patch else 'Extra'
        versions.append(
            _version_row(
                kind='extra',
                uuid=extra.uuid,
                label=f'{label_prefix}: {_basename_label(extra.file_path, extra.uuid[:8])}',
                is_default=False,
                file_path=extra.file_path,
                extra_kind=getattr(extra, 'extra_kind', None),
                patch_format=getattr(extra, 'patch_format', None),
                target_language=getattr(extra, 'target_language', None),
                source_url=getattr(extra, 'source_url', None),
                can_apply_patch=is_patch,
            )
        )

    return versions


def cleanup_orphan_versions(game: Game) -> dict[str, Any]:
    """Detach/delete update and extra rows whose files are gone for this game.

    Scope is limited to the given game's ``GameUpdate`` / ``GameExtra`` rows.
    Does not touch the base game row. Returns ``{ok, removed, kept}`` where
    ``removed`` / ``kept`` are lists of ``{kind, uuid}``.
    """
    removed: list[dict[str, str]] = []
    kept: list[dict[str, str]] = []

    updates = db.session.execute(
        select(GameUpdate).filter_by(game_uuid=game.uuid)
    ).scalars().all()
    for update in updates:
        path_missing, _, _ = _path_status(update.file_path)
        entry = {'kind': 'update', 'uuid': update.uuid}
        if path_missing:
            db.session.delete(update)
            removed.append(entry)
        else:
            kept.append(entry)

    extras = db.session.execute(
        select(GameExtra).filter_by(game_uuid=game.uuid)
    ).scalars().all()
    for extra in extras:
        path_missing, _, _ = _path_status(extra.file_path)
        entry = {'kind': 'extra', 'uuid': extra.uuid}
        if path_missing:
            db.session.delete(extra)
            removed.append(entry)
        else:
            kept.append(entry)

    db.session.commit()
    return {'ok': True, 'removed': removed, 'kept': kept}


def resolve_version_file(
    game: Game,
    *,
    kind: str | None = None,
    version_uuid: str | None = None,
) -> tuple[str, str, str | None]:
    """
    Resolve (file_location, zip_file_path_hint, version_uuid) for a download.

    kind: base | update | extra (default base)
    """
    kind = (kind or 'base').strip().lower()
    if kind in ('', 'base', 'game'):
        return game.full_disk_path, game.full_disk_path, None

    if not version_uuid:
        raise ValueError('version_uuid required for update/extra downloads')

    if kind == 'update':
        row = db.session.execute(
            select(GameUpdate).filter_by(game_uuid=game.uuid, uuid=version_uuid)
        ).scalars().first()
        if not row:
            raise LookupError('Update version not found')
        return row.file_path, row.file_path, row.uuid

    if kind == 'extra':
        row = db.session.execute(
            select(GameExtra).filter_by(game_uuid=game.uuid, uuid=version_uuid)
        ).scalars().first()
        if not row:
            raise LookupError('Extra version not found')
        return row.file_path, row.file_path, row.uuid

    raise ValueError('kind must be base, update, or extra')
