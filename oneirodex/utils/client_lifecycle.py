"""Companion client lifecycle registry synced to the server for web UI."""

from __future__ import annotations

import json
import os
import threading
from typing import Any
from oneirodex.utils.library_paths import library_dir

_LOCK = threading.Lock()
_VALID_STATES = frozenset({'not_downloaded', 'downloaded', 'installed', 'update_available'})


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
    folder = os.path.join(_library_root(), 'client_lifecycle')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f'user_{int(user_id)}.json')


def _read_lifecycle_map(path: str) -> dict[str, str]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    records = data.get('records') if isinstance(data, dict) else None
    if not isinstance(records, list):
        return {}
    out: dict[str, str] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        uuid = str(row.get('game_uuid') or '').strip()
        state = str(row.get('state') or '').strip()
        if uuid and state in _VALID_STATES:
            out[uuid] = state
    return out


def load_lifecycle_map(user_id: int | None) -> dict[str, str]:
    """Return {game_uuid: state} for the user, or empty."""
    if user_id is None:
        return {}
    return _read_lifecycle_map(_store_path(user_id))


def save_lifecycle_records(
    user_id: int,
    records: list[dict[str, Any]],
    *,
    replace: bool = False,
) -> dict[str, str]:
    """Upsert companion lifecycle rows (default) or replace the whole map.

    Partial companion snapshots must not wipe other games' states; pass
    ``replace=True`` only for an intentional full reset.
    """
    incoming: dict[str, str] = {}
    for row in records or []:
        if not isinstance(row, dict):
            continue
        uuid = str(row.get('game_uuid') or '').strip()
        state = str(row.get('state') or '').strip()
        if not uuid or state not in _VALID_STATES:
            continue
        incoming[uuid] = state

    path = _store_path(user_id)
    with _LOCK:
        mapping = {} if replace else _read_lifecycle_map(path)
        mapping.update(incoming)
        cleaned = [{'game_uuid': uuid, 'state': state} for uuid, state in sorted(mapping.items())]
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump({'records': cleaned}, fh, indent=2)
    return mapping


def installed_game_uuids(user_id: int | None) -> set[str]:
    return {
        uuid
        for uuid, state in load_lifecycle_map(user_id).items()
        if state in {'installed', 'update_available'}
    }
