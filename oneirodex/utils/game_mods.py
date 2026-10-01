"""Per-game mod tracking (JSON packs under library/mods)."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import uuid4

from flask import current_app
from oneirodex.utils.library_paths import library_dir

_SAFE_UUID = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.I,
)


def mods_enabled() -> bool:
    return str(current_app.config.get('ENABLE_MOD_TRACKING', 'true')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def mods_root() -> str:
    root = current_app.config.get('GAME_MODS_PATH')
    if root:
        return root
    return os.path.join(library_dir(), 'mods')


def _pack_path(game_uuid: str) -> str:
    if not _SAFE_UUID.match(game_uuid or ''):
        raise ValueError('Invalid game UUID')
    folder = os.path.join(mods_root(), game_uuid)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, 'mods.json')


# INSP-36 -- the loader a mod needs. Suggested words, not a closed list: a
# librarian can type a loader we never heard of and the row keeps it. The
# desktop only *reads* this ("needs BepInEx installed -- not managed here");
# nothing here installs a loader.
LOADERS = (
    'bepinex',
    'melonloader',
    'smapi',
    'lovely',
    'forge',
    'fabric',
    'quilt',
    'neoforge',
    'manual',
    'none',
)
_LOADER_SAFE = re.compile(r'[^a-z0-9._+-]+')


def normalize_loader(raw: Any) -> str:
    """Lower-cased slug (``BepInEx 5`` -> ``bepinex-5``), at most 40 chars; ``''`` when unset."""
    text = str(raw or '').strip().lower()
    if not text:
        return ''
    text = _LOADER_SAFE.sub('-', text).strip('-')
    return text[:40]


def _normalize_mod_row(row: dict[str, Any], *, default_order: int) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    mod_id = str(row.get('id') or '').strip()
    if not mod_id:
        return None
    source_url = str(
        row.get('source_url')
        or row.get('url')
        or ''
    ).strip()
    try:
        load_order = int(row.get('load_order', default_order))
    except (TypeError, ValueError):
        load_order = default_order
    return {
        'id': mod_id,
        'name': str(row.get('name') or mod_id),
        'version': str(row.get('version') or ''),
        'source_url': source_url,
        'url': source_url,
        'notes': str(row.get('notes') or ''),
        'enabled': bool(row.get('enabled', True)),
        'load_order': load_order,
        'loader': normalize_loader(row.get('loader')),
        # INSP-38 -- ids of rows this one needs first; unknown ids drop on the
        # next read (see _prune_requires). INSP-39 -- the newest version a
        # registry showed for this row, so the panel can say "update: vX".
        'requires': _id_list(row.get('requires')),
        'latest_seen_version': str(row.get('latest_seen_version') or '')[:64],
    }


def _id_list(raw: Any) -> list[str]:
    out: list[str] = []
    for value in raw if isinstance(raw, list) else []:
        mid = str(value or '').strip()
        if mid and mid not in out:
            out.append(mid)
    return out[:64]


def _prune_requires(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {row['id'] for row in rows}
    for row in rows:
        row['requires'] = [mid for mid in row.get('requires', []) if mid in known and mid != row['id']]
    return rows


def _read_pack(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# INSP-37 -- a named set of mod ids. Activating one flips `enabled` on every
# row: in the set on, the rest off. Profiles reference rows by id; a row that
# disappears just drops out of the set on the next read.
_SAFE_PROFILE_ID = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
MAX_PROFILES = 32


def _normalize_profile(row: Any, known_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    pid = str(row.get('id') or '').strip()
    name = str(row.get('name') or '').strip()[:120]
    if not pid or not _SAFE_PROFILE_ID.match(pid) or not name:
        return None
    raw_ids = row.get('mod_ids') if isinstance(row.get('mod_ids'), list) else []
    mod_ids: list[str] = []
    for value in raw_ids:
        mid = str(value or '').strip()
        if mid and mid in known_ids and mid not in mod_ids:
            mod_ids.append(mid)
    return {'id': pid, 'name': name, 'mod_ids': mod_ids}


def _normalize_profiles(rows: Any, known_ids: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        item = _normalize_profile(row, known_ids)
        if item and item['id'] not in seen:
            seen.add(item['id'])
            out.append(item)
        if len(out) >= MAX_PROFILES:
            break
    return out


def load_mods(game_uuid: str) -> dict[str, Any]:
    data = _read_pack(_pack_path(game_uuid))
    mods = data.get('mods')
    if not isinstance(mods, list):
        mods = []
    cleaned: list[dict[str, Any]] = []
    for index, row in enumerate(mods):
        normalized = _normalize_mod_row(row, default_order=index)
        if normalized:
            cleaned.append(normalized)
    cleaned.sort(key=lambda item: (item['load_order'], item['name'].lower()))
    _prune_requires(cleaned)
    known = {row['id'] for row in cleaned}
    profiles = _normalize_profiles(data.get('profiles'), known)
    active = str(data.get('active_profile') or '').strip()
    if active and not any(p['id'] == active for p in profiles):
        active = ''
    return {
        'game_uuid': game_uuid,
        'default_loader': normalize_loader(data.get('default_loader')),
        'loaders': list(LOADERS),
        'mods': cleaned,
        'profiles': profiles,
        'active_profile': active,
    }


def save_mods(
    game_uuid: str,
    mods: list[dict[str, Any]],
    *,
    default_loader: str | None = None,
    profiles: list[dict[str, Any]] | None = None,
    active_profile: str | None = None,
) -> dict[str, Any]:
    """Write the pack. A ``None`` keyword keeps what the pack had for that
    field (``default_loader``, ``profiles``, ``active_profile``)."""
    path = _pack_path(game_uuid)
    current = _read_pack(path)
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(mods):
        item = _normalize_mod_row(row, default_order=index)
        if item:
            normalized.append(item)
    normalized.sort(key=lambda item: (item['load_order'], item['name'].lower()))
    _prune_requires(normalized)
    known = {row['id'] for row in normalized}
    pack = {
        'game_uuid': game_uuid,
        'default_loader': normalize_loader(
            current.get('default_loader') if default_loader is None else default_loader
        ),
        'mods': normalized,
        'profiles': _normalize_profiles(
            current.get('profiles') if profiles is None else profiles, known
        ),
        'active_profile': str(
            (current.get('active_profile') if active_profile is None else active_profile) or ''
        ).strip(),
    }
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(pack, fh, indent=2)
    return load_mods(game_uuid)


# INSP-38 -- "no loader" words: a row saying one of these never conflicts.
NO_LOADER = frozenset({'', 'manual', 'none'})


def loader_conflicts(pack: dict[str, Any]) -> list[dict[str, str]]:
    """Enabled rows whose loader disagrees with the pack default (both set,
    neither a no-loader word). The apply gate reads this; the panel shows it."""
    default = normalize_loader(pack.get('default_loader'))
    if default in NO_LOADER:
        return []
    out: list[dict[str, str]] = []
    for row in pack.get('mods', []):
        loader = normalize_loader(row.get('loader'))
        if row.get('enabled') and loader not in NO_LOADER and loader != default:
            out.append({'id': row['id'], 'name': row['name'], 'loader': loader, 'default_loader': default})
    return out


def set_default_loader(game_uuid: str, loader: str | None) -> dict[str, Any]:
    pack = load_mods(game_uuid)
    return save_mods(game_uuid, pack['mods'], default_loader=loader or '')


def create_mod(game_uuid: str, payload: dict[str, Any]) -> dict[str, Any]:
    pack = load_mods(game_uuid)
    mods = pack['mods']
    mod_id = str(payload.get('id') or uuid4())
    if any(row['id'] == mod_id for row in mods):
        raise ValueError('Mod id already exists')
    next_order = max((row['load_order'] for row in mods), default=-1) + 1
    row = _normalize_mod_row(
        {
            'id': mod_id,
            'name': payload.get('name'),
            'version': payload.get('version'),
            'source_url': payload.get('source_url', payload.get('url')),
            'notes': payload.get('notes'),
            'enabled': payload.get('enabled', True),
            'load_order': payload.get('load_order', next_order),
            'loader': payload.get('loader'),
            'requires': payload.get('requires'),
            'latest_seen_version': payload.get('latest_seen_version'),
        },
        default_order=next_order,
    )
    if not row:
        raise ValueError('Invalid mod payload')
    mods.append(row)
    saved = save_mods(game_uuid, mods)
    created = next(item for item in saved['mods'] if item['id'] == mod_id)
    return created


def update_mod(game_uuid: str, mod_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    pack = load_mods(game_uuid)
    mods = pack['mods']
    index = next((i for i, row in enumerate(mods) if row['id'] == mod_id), None)
    if index is None:
        raise LookupError('Mod not found')
    current = mods[index]
    merged = {
        **current,
        **payload,
        'id': mod_id,
        'source_url': payload.get('source_url', payload.get('url', current['source_url'])),
    }
    updated = _normalize_mod_row(merged, default_order=current['load_order'])
    if not updated:
        raise ValueError('Invalid mod payload')
    mods[index] = updated
    saved = save_mods(game_uuid, mods)
    return next(item for item in saved['mods'] if item['id'] == mod_id)


def delete_mod(game_uuid: str, mod_id: str) -> bool:
    pack = load_mods(game_uuid)
    mods = [row for row in pack['mods'] if row['id'] != mod_id]
    if len(mods) == len(pack['mods']):
        return False
    save_mods(game_uuid, mods)
    return True


def list_mods_summary(game_uuids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for game_uuid in game_uuids:
        pack = load_mods(game_uuid)
        mods = pack['mods']
        if not mods:
            continue
        rows.append({
            'game_uuid': game_uuid,
            'mod_count': len(mods),
            'enabled_count': sum(1 for row in mods if row.get('enabled')),
        })
    return rows
