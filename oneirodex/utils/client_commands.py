"""Queued companion commands from the web UI (install / update / uninstall / open_path)."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from oneirodex.utils.library_paths import library_dir

_LOCK = threading.Lock()
_VALID_ACTIONS = frozenset({
    'download',
    'install',
    'update',
    'uninstall',
    'apply_patch',
    'apply_mod_pack',
    'open_path',
})
# Companion actions that pull or mutate installs. Child accounts and anyone
# without write:download must not queue these; open_path stays ACL-only.
WRITE_DOWNLOAD_ACTIONS = frozenset({
    'download',
    'install',
    'update',
    'uninstall',
    'apply_patch',
    'apply_mod_pack',
})
_VALID_KINDS = frozenset({'base', 'update', 'extra'})
_IN_FLIGHT_TTL_SECONDS = 600
_OPEN_PATH_MAX_LEN = 4096


def rom_patch_apply_enabled() -> bool:
    """True when companion Flips apply is allowed (ENABLE_ROM_PATCH_APPLY)."""
    try:
        from flask import current_app

        return str(current_app.config.get('ENABLE_ROM_PATCH_APPLY', '')).lower() in (
            '1',
            'true',
            'yes',
            'on',
        )
    except RuntimeError:
        return os.getenv('ENABLE_ROM_PATCH_APPLY', 'true').lower() in (
            '1',
            'true',
            'yes',
            'on',
        )


def mod_tracking_enabled() -> bool:
    """True when companion mod pack apply is allowed (ENABLE_MOD_TRACKING)."""
    try:
        from flask import current_app

        return str(current_app.config.get('ENABLE_MOD_TRACKING', 'true')).lower() in (
            '1',
            'true',
            'yes',
            'on',
        )
    except RuntimeError:
        return os.getenv('ENABLE_MOD_TRACKING', 'true').lower() in (
            '1',
            'true',
            'yes',
            'on',
        )


def _library_root() -> str:
    try:
        from flask import current_app

        upload = current_app.config.get('UPLOAD_FOLDER')
        if upload:
            return upload
    except RuntimeError:
        pass
    return library_dir(os.path.dirname(os.path.dirname(__file__)))


def _open_path_allowed_bases() -> list[str]:
    """Configured library / scan roots that may be revealed via open_path."""
    bases: list[str] = []
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            from oneirodex.utils.security import get_allowed_base_directories

            for base in get_allowed_base_directories(current_app):
                if base and base not in bases:
                    bases.append(base)
            # Include last successful scan roots (UnmatchedFolder paths live under these).
            try:
                from sqlalchemy import select

                from oneirodex import db
                from oneirodex.models import Library

                for folder in db.session.execute(
                    select(Library.last_scan_folder).where(Library.last_scan_folder.isnot(None))
                ).scalars():
                    cleaned = str(folder or '').strip()
                    if cleaned and cleaned not in bases:
                        bases.append(cleaned)
            except Exception:
                pass
    except RuntimeError:
        pass
    return bases


def _validate_open_path(path: str | None) -> str:
    """Require an absolute path under configured library roots. Raises ValueError."""
    cleaned = str(path or '').strip()
    if not cleaned:
        raise ValueError('path is required for open_path')
    if len(cleaned) > _OPEN_PATH_MAX_LEN:
        raise ValueError('path too long')
    if any(ch in cleaned for ch in ('\x00', '\n', '\r')):
        raise ValueError('path contains invalid characters')
    try:
        path_obj = Path(cleaned)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError('invalid path') from exc
    if not path_obj.is_absolute():
        raise ValueError('path must be absolute')

    bases = _open_path_allowed_bases()
    if not bases:
        raise ValueError('no library roots configured for open_path')

    from oneirodex.utils.security import is_safe_path

    try:
        ok, err = is_safe_path(cleaned, bases)
    except RuntimeError:
        # is_safe_path may log via Flask; fall back to relative_to checks.
        ok, err = False, 'Access denied - path outside allowed directories'
        try:
            resolved = path_obj.resolve(strict=False)
            for base in bases:
                if not base:
                    continue
                try:
                    resolved.relative_to(Path(base).resolve(strict=False))
                    ok, err = True, None
                    break
                except ValueError:
                    continue
        except (OSError, ValueError):
            ok, err = False, 'invalid path'

    if not ok:
        raise ValueError(err or 'path outside allowed library roots')
    return cleaned


def _store_path(user_id: int) -> str:
    folder = os.path.join(_library_root(), 'client_commands')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f'user_{int(user_id)}.json')


def _read_queue(path: str) -> list[dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    commands = data.get('commands') if isinstance(data, dict) else None
    if not isinstance(commands, list):
        return []
    return [row for row in commands if isinstance(row, dict)]


def _write_queue(path: str, commands: list[dict[str, Any]]) -> None:
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'commands': commands}, fh, indent=2)


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _reclaim_stale(queue: list[dict[str, Any]], *, now: datetime) -> list[dict[str, Any]]:
    refreshed: list[dict[str, Any]] = []
    for row in queue:
        if row.get('status') != 'in_flight':
            refreshed.append(row)
            continue
        claimed_at = _parse_iso(row.get('claimed_at'))
        age = (now - claimed_at).total_seconds() if claimed_at else _IN_FLIGHT_TTL_SECONDS + 1
        if age > _IN_FLIGHT_TTL_SECONDS:
            pending = dict(row)
            pending['status'] = 'pending'
            pending.pop('claimed_at', None)
            refreshed.append(pending)
        else:
            refreshed.append(row)
    return refreshed


def _public_command(row: dict[str, Any]) -> dict[str, Any]:
    delivered = {
        'id': str(row.get('id') or uuid.uuid4()),
        'game_uuid': str(row.get('game_uuid') or ''),
        'action': str(row['action']),
        'created_at': row.get('created_at'),
        'status': row.get('status') or 'pending',
    }
    if row.get('kind'):
        delivered['kind'] = str(row['kind'])
    if row.get('version_uuid'):
        delivered['version_uuid'] = str(row['version_uuid'])
    if row.get('path'):
        delivered['path'] = str(row['path'])
    if 'select' in row and row.get('select') is not None:
        delivered['select'] = bool(row['select'])
    return delivered


def _claimable(row: dict[str, Any]) -> bool:
    action = row.get('action')
    if action not in _VALID_ACTIONS:
        return False
    if row.get('status') != 'pending':
        return False
    if action == 'open_path':
        return bool(str(row.get('path') or '').strip())
    return bool(str(row.get('game_uuid') or '').strip())


def enqueue_client_command(
    user_id: int,
    game_uuid: str,
    action: str,
    *,
    kind: str | None = None,
    version_uuid: str | None = None,
    path: str | None = None,
    select: bool | None = None,
) -> dict[str, Any]:
    """Append a pending command for the companion to claim."""
    cleaned_uuid = str(game_uuid or '').strip()
    cleaned_action = str(action or '').strip().lower()
    cleaned_kind = str(kind or '').strip().lower() or None
    cleaned_version = str(version_uuid or '').strip() or None
    if cleaned_action not in _VALID_ACTIONS:
        raise ValueError(f'action must be one of: {", ".join(sorted(_VALID_ACTIONS))}')

    cleaned_path: str | None = None
    cleaned_select: bool | None = None
    if cleaned_action == 'open_path':
        cleaned_path = _validate_open_path(path)
        cleaned_select = True if select is None else bool(select)
        # game_uuid optional for unmatched folders / admin scanjobs.
    else:
        if not cleaned_uuid:
            raise ValueError('game_uuid is required')

    if cleaned_action == 'apply_patch':
        if not rom_patch_apply_enabled():
            raise ValueError(
                'ROM patch apply is disabled. Set ENABLE_ROM_PATCH_APPLY=true and configure Flips.'
            )
        if cleaned_kind != 'extra' or not cleaned_version:
            raise ValueError('apply_patch requires kind=extra and version_uuid')
    if cleaned_action == 'apply_mod_pack':
        if not mod_tracking_enabled():
            raise ValueError('Mod tracking is disabled. Set ENABLE_MOD_TRACKING=true.')
    if cleaned_kind is not None and cleaned_kind not in _VALID_KINDS:
        raise ValueError(f'kind must be one of: {", ".join(sorted(_VALID_KINDS))}')
    if cleaned_kind in {'update', 'extra'} and not cleaned_version:
        raise ValueError('version_uuid required for update/extra kind')

    command = {
        'id': str(uuid.uuid4()),
        'game_uuid': cleaned_uuid,
        'action': cleaned_action,
        'status': 'pending',
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    if cleaned_kind:
        command['kind'] = cleaned_kind
    if cleaned_version:
        command['version_uuid'] = cleaned_version
    if cleaned_path is not None:
        command['path'] = cleaned_path
    if cleaned_select is not None:
        command['select'] = cleaned_select

    store = _store_path(user_id)
    with _LOCK:
        queue = _read_queue(store)
        # Drop duplicate pending for same game+action+version (or same open_path target).
        def _is_duplicate(row: dict[str, Any]) -> bool:
            if row.get('status') != 'pending' or row.get('action') != cleaned_action:
                return False
            if cleaned_action == 'open_path':
                return (row.get('path') or None) == cleaned_path
            return (
                row.get('game_uuid') == cleaned_uuid
                and (row.get('version_uuid') or None) == cleaned_version
            )

        queue = [row for row in queue if not _is_duplicate(row)]
        queue.append(command)
        if len(queue) > 50:
            queue = queue[-50:]
        _write_queue(store, queue)
    return command


def claim_pending_commands(user_id: int, *, limit: int = 10) -> list[dict[str, Any]]:
    """Mark up to ``limit`` pending commands in_flight and return them (durable until ack)."""
    path = _store_path(user_id)
    claimed: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    with _LOCK:
        queue = _reclaim_stale(_read_queue(path), now=now)
        updated: list[dict[str, Any]] = []
        for row in queue:
            if len(claimed) < limit and _claimable(row):
                in_flight = dict(row)
                in_flight['status'] = 'in_flight'
                in_flight['claimed_at'] = now.isoformat()
                if not in_flight.get('id'):
                    in_flight['id'] = str(uuid.uuid4())
                updated.append(in_flight)
                claimed.append(_public_command(in_flight))
            else:
                updated.append(row)
        _write_queue(path, updated)
    return claimed


def ack_client_commands(user_id: int, command_ids: list[str]) -> int:
    """Remove successfully handled commands from the queue."""
    wanted = {str(cid).strip() for cid in command_ids if str(cid).strip()}
    if not wanted:
        return 0
    path = _store_path(user_id)
    with _LOCK:
        queue = _read_queue(path)
        remaining = [row for row in queue if str(row.get('id') or '') not in wanted]
        removed = len(queue) - len(remaining)
        if removed:
            _write_queue(path, remaining)
        return removed


def nack_client_commands(user_id: int, command_ids: list[str]) -> int:
    """Return in-flight commands to pending so they can be retried."""
    wanted = {str(cid).strip() for cid in command_ids if str(cid).strip()}
    if not wanted:
        return 0
    path = _store_path(user_id)
    released = 0
    with _LOCK:
        queue = _read_queue(path)
        updated: list[dict[str, Any]] = []
        for row in queue:
            if str(row.get('id') or '') in wanted:
                pending = dict(row)
                pending['status'] = 'pending'
                pending.pop('claimed_at', None)
                updated.append(pending)
                released += 1
            else:
                updated.append(row)
        if released:
            _write_queue(path, updated)
    return released
