"""Wanted update/DLC packs — notify when local scan finds a match."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any
from oneirodex.utils.library_paths import library_dir

_LOCK = threading.Lock()


def _library_root() -> str:
    try:
        from flask import current_app

        upload = current_app.config.get('UPLOAD_FOLDER')
        if upload:
            return upload
    except RuntimeError:
        pass
    return library_dir(os.path.dirname(os.path.dirname(__file__)))


def _store_path(user_id: int) -> str:
    folder = os.path.join(_library_root(), 'wanted_updates')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f'user_{int(user_id)}.json')


def _read(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    rows = data.get('items') if isinstance(data, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _write(path: str, items: list[dict[str, Any]]) -> None:
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'items': items}, fh, indent=2)


def list_wanted(user_id: int) -> list[dict[str, Any]]:
    return _read(_store_path(user_id))


def add_wanted(
    user_id: int,
    *,
    game_uuid: str,
    kind: str = 'update',
    label: str | None = None,
    store: str | None = None,
    store_id: str | None = None,
) -> dict[str, Any]:
    cleaned_uuid = str(game_uuid or '').strip()
    cleaned_kind = str(kind or 'update').strip().lower()
    if not cleaned_uuid:
        raise ValueError('game_uuid required')
    if cleaned_kind not in {'update', 'extra', 'dlc'}:
        raise ValueError('kind must be update, extra, or dlc')
    item = {
        'id': str(uuid.uuid4()),
        'game_uuid': cleaned_uuid,
        'kind': cleaned_kind,
        'label': (label or cleaned_kind).strip()[:200],
        'store': (store or '').strip() or None,
        'store_id': (store_id or '').strip() or None,
        'status': 'wanted',
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    path = _store_path(user_id)
    with _LOCK:
        items = _read(path)
        items = [
            row
            for row in items
            if not (
                row.get('game_uuid') == cleaned_uuid
                and row.get('kind') == cleaned_kind
                and row.get('status') == 'wanted'
            )
        ]
        items.append(item)
        _write(path, items[-100:])
    return item


def mark_fulfilled(user_id: int, game_uuid: str, *, kind: str | None = None) -> int:
    path = _store_path(user_id)
    updated = 0
    with _LOCK:
        items = _read(path)
        for row in items:
            if row.get('game_uuid') != game_uuid or row.get('status') != 'wanted':
                continue
            if kind and row.get('kind') != kind:
                continue
            row['status'] = 'available'
            row['fulfilled_at'] = datetime.now(timezone.utc).isoformat()
            updated += 1
        if updated:
            _write(path, items)
    return updated
