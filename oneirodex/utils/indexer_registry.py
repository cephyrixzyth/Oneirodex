"""Native Torznab/Newznab indexer registry in GlobalSettings.arr_settings."""

from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.security import validate_outbound_http_url

_PRESETS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'indexer_presets.json'
_VALID_PROTOCOLS = frozenset({'torznab', 'newznab'})
_VALID_SOURCES = frozenset({'manual', 'preset'})


def _settings_row() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def _raw_arr_settings() -> dict[str, Any]:
    row = _settings_row()
    cfg = getattr(row, 'arr_settings', None) if row else None
    return dict(cfg) if isinstance(cfg, dict) else {}


def _save_raw_arr_settings(cfg: dict[str, Any]) -> None:
    row = _settings_row()
    if not row:
        row = GlobalSettings()
        db.session.add(row)
    row.arr_settings = cfg
    db.session.commit()


def load_indexer_presets() -> list[dict[str, Any]]:
    """Read curated pack from disk (never mutated by enable-presets)."""
    if not _PRESETS_PATH.is_file():
        return []
    try:
        payload = json.loads(_PRESETS_PATH.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []
    presets = payload.get('presets') if isinstance(payload, dict) else payload
    if not isinstance(presets, list):
        return []
    out: list[dict[str, Any]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        pid = str(item.get('id') or '').strip()
        if not pid:
            continue
        protocol = str(item.get('protocol') or 'torznab').strip().lower()
        if protocol not in _VALID_PROTOCOLS:
            continue
        out.append({
            'id': pid,
            'name': str(item.get('name') or pid).strip(),
            'protocol': protocol,
            'url': str(item.get('url') or '').strip(),
            'notes': str(item.get('notes') or '').strip(),
        })
    return out


def presets_path() -> Path:
    return _PRESETS_PATH


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _validate_indexer_url(url: str) -> str:
    """Native indexer hosts — never LAN even when ALLOW_PRIVATE_LAN_URLS is on."""
    ok, result = validate_outbound_http_url(url, allow_http=True, allow_private_lan=False)
    if not ok:
        raise ValueError(result)
    return result.rstrip('/')


def normalize_indexer(
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
    require_url: bool = True,
) -> dict[str, Any]:
    base = dict(existing or {})
    name = str(payload.get('name', base.get('name') or '')).strip()
    if not name:
        raise ValueError('name is required')
    protocol = str(payload.get('protocol', base.get('protocol') or 'torznab')).strip().lower()
    if protocol not in _VALID_PROTOCOLS:
        raise ValueError('protocol must be torznab or newznab')
    url_raw = payload.get('url', base.get('url') or '')
    url = str(url_raw or '').strip().rstrip('/')
    if require_url and not url:
        raise ValueError('url is required')
    if url:
        url = _validate_indexer_url(url)
    api_key = base.get('api_key') or ''
    if 'api_key' in payload and payload['api_key'] is not None:
        key = str(payload.get('api_key') or '').strip()
        if key != '***':
            api_key = key
    enabled = base.get('enabled', True)
    if 'enabled' in payload:
        enabled = bool(payload.get('enabled'))
    source = str(payload.get('source', base.get('source') or 'manual')).strip().lower()
    if source not in _VALID_SOURCES:
        source = 'manual'
    preset_id = payload.get('preset_id', base.get('preset_id'))
    if preset_id is not None:
        preset_id = str(preset_id).strip() or None
    indexer_id = str(base.get('id') or payload.get('id') or _new_id()).strip() or _new_id()
    return {
        'id': indexer_id,
        'name': name,
        'protocol': protocol,
        'url': url,
        'api_key': api_key,
        'enabled': bool(enabled),
        'source': source,
        'preset_id': preset_id,
    }


def indexer_public_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': row.get('id'),
        'name': row.get('name'),
        'protocol': row.get('protocol'),
        'url': row.get('url') or '',
        'api_key_set': bool(row.get('api_key')),
        'enabled': bool(row.get('enabled')),
        'source': row.get('source') or 'manual',
        'preset_id': row.get('preset_id'),
        'ready': bool(row.get('enabled') and row.get('url') and row.get('api_key')),
    }


def list_indexers() -> list[dict[str, Any]]:
    raw = _raw_arr_settings()
    items = raw.get('indexers')
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict) and item.get('id')]


def get_indexer(indexer_id: str) -> dict[str, Any] | None:
    for item in list_indexers():
        if item.get('id') == indexer_id:
            return item
    return None


def _persist_indexers(indexers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = _raw_arr_settings()
    raw['indexers'] = indexers
    _save_raw_arr_settings(raw)
    return indexers


def add_indexer(payload: dict[str, Any]) -> dict[str, Any]:
    row = normalize_indexer(payload, require_url=True)
    indexers = list_indexers()
    if any(i.get('id') == row['id'] for i in indexers):
        row['id'] = _new_id()
    indexers.append(row)
    _persist_indexers(indexers)
    return row


def update_indexer(indexer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    indexers = list_indexers()
    for idx, item in enumerate(indexers):
        if item.get('id') != indexer_id:
            continue
        updated = normalize_indexer(payload, existing=item, require_url=False)
        updated['id'] = indexer_id
        if not updated.get('url'):
            raise ValueError('url is required')
        indexers[idx] = updated
        _persist_indexers(indexers)
        return updated
    raise KeyError(indexer_id)


def delete_indexer(indexer_id: str) -> bool:
    indexers = list_indexers()
    next_rows = [i for i in indexers if i.get('id') != indexer_id]
    if len(next_rows) == len(indexers):
        return False
    _persist_indexers(next_rows)
    return True


def bulk_import_indexers(payload: Any) -> list[dict[str, Any]]:
    """Import from JSON list or CSV text (name,protocol,url,api_key)."""
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get('indexers'), list):
            rows = list(payload['indexers'])
        elif isinstance(payload.get('items'), list):
            rows = list(payload['items'])
        elif 'csv' in payload or 'text' in payload:
            text = str(payload.get('csv') or payload.get('text') or '')
            rows = _parse_csv_indexers(text)
        else:
            raise ValueError('Provide indexers array or csv/text')
    elif isinstance(payload, list):
        rows = list(payload)
    elif isinstance(payload, str):
        text = payload.strip()
        if text.startswith('['):
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError('JSON bulk import must be an array')
            rows = parsed
        else:
            rows = _parse_csv_indexers(text)
    else:
        raise ValueError('Unsupported bulk import payload')

    created: list[dict[str, Any]] = []
    indexers = list_indexers()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError('Each indexer must be an object')
        row = normalize_indexer({**item, 'source': item.get('source') or 'manual'}, require_url=True)
        if any(i.get('id') == row['id'] for i in indexers):
            row['id'] = _new_id()
        indexers.append(row)
        created.append(row)
    _persist_indexers(indexers)
    return created


def _parse_csv_indexers(text: str) -> list[dict[str, Any]]:
    text = (text or '').strip()
    if not text:
        return []
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if not fieldnames or 'name' not in fieldnames:
        # Headerless: name,protocol,url,api_key
        reader = csv.reader(io.StringIO(text))
        rows: list[dict[str, Any]] = []
        for parts in reader:
            if not parts or all(not str(p).strip() for p in parts):
                continue
            if len(parts) < 3:
                raise ValueError('CSV rows need name,protocol,url[,api_key]')
            # Skip accidental header row
            if str(parts[0]).strip().lower() == 'name' and str(parts[1]).strip().lower() == 'protocol':
                continue
            rows.append({
                'name': parts[0].strip(),
                'protocol': parts[1].strip(),
                'url': parts[2].strip(),
                'api_key': parts[3].strip() if len(parts) > 3 else '',
            })
        return rows
    out: list[dict[str, Any]] = []
    for row in reader:
        mapped = {str(k).strip().lower(): (v or '').strip() for k, v in row.items() if k}
        if not mapped.get('name'):
            continue
        out.append({
            'name': mapped.get('name', ''),
            'protocol': mapped.get('protocol', 'torznab'),
            'url': mapped.get('url', ''),
            'api_key': mapped.get('api_key', ''),
        })
    return out


def enable_presets(preset_ids: list[str]) -> list[dict[str, Any]]:
    """Copy presets into indexers with empty api_key. Does not mutate the pack file."""
    if not preset_ids:
        raise ValueError('preset_ids is required')
    pack = {p['id']: p for p in load_indexer_presets()}
    indexers = list_indexers()
    existing_preset_ids = {
        i.get('preset_id') for i in indexers if i.get('source') == 'preset' and i.get('preset_id')
    }
    created: list[dict[str, Any]] = []
    for pid in preset_ids:
        pid = str(pid or '').strip()
        if not pid:
            continue
        preset = pack.get(pid)
        if not preset:
            raise KeyError(pid)
        if pid in existing_preset_ids:
            continue
        row = normalize_indexer(
            {
                'name': preset['name'],
                'protocol': preset['protocol'],
                'url': preset.get('url') or '',
                'api_key': '',
                'enabled': True,
                'source': 'preset',
                'preset_id': pid,
            },
            require_url=bool(preset.get('url')),
        )
        # Placeholder .invalid URLs are intentional; still validate shape.
        if not row.get('url') and preset.get('url'):
            row['url'] = str(preset['url']).rstrip('/')
        indexers.append(row)
        existing_preset_ids.add(pid)
        created.append(row)
    _persist_indexers(indexers)
    return created


def indexer_status_summary() -> dict[str, Any]:
    rows = list_indexers()
    warnings: list[str] = []
    ready = 0
    enabled = 0
    for row in rows:
        if row.get('enabled'):
            enabled += 1
        if row.get('enabled') and row.get('url') and row.get('api_key'):
            ready += 1
        elif row.get('enabled') and not row.get('api_key'):
            warnings.append(f"Indexer '{row.get('name')}' skipped: missing api_key")
        elif row.get('enabled') and not row.get('url'):
            warnings.append(f"Indexer '{row.get('name')}' skipped: missing url")
    return {
        'id': 'native_indexers',
        'configured': ready > 0,
        'count': len(rows),
        'enabled': enabled,
        'ready': ready,
        'warnings': warnings,
        'url': None,
    }


def ready_native_indexers() -> list[dict[str, Any]]:
    return [
        row for row in list_indexers()
        if row.get('enabled') and row.get('url') and row.get('api_key')
    ]
