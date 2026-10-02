"""Playnite library import bridge (register titles into Oneirodex — no DRM downloads)."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

from sqlalchemy import func, select

from oneirodex import db
from oneirodex.models import Game, UserOwnedTitle


@dataclass
class ImportResult:
    imported: int = 0
    matched: int = 0
    skipped: int = 0
    errors: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            'imported': self.imported,
            'matched': self.matched,
            'skipped': self.skipped,
            'errors': self.errors or [],
        }


def _match_game_by_name(name: str) -> Game | None:
    if not name:
        return None
    return db.session.execute(
        select(Game).filter(func.lower(Game.name) == func.lower(name.strip())).limit(1),
    ).scalars().first()


def import_playnite_json(user_id: int, payload: str | bytes | dict | list) -> ImportResult:
    """
    Import Playnite library export JSON.

    Accepts a list of games or an object with a 'Games' / 'games' array.
    Creates UserOwnedTitle rows with store='playnite' (register-only).
    """
    result = ImportResult(errors=[])
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode('utf-8')
    if isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload

    if isinstance(data, dict):
        games = data.get('Games') or data.get('games') or data.get('items') or []
    elif isinstance(data, list):
        games = data
    else:
        result.errors.append('Unrecognized Playnite JSON shape')
        return result

    for item in games:
        if not isinstance(item, dict):
            result.skipped += 1
            continue
        name = (item.get('Name') or item.get('name') or item.get('GameName') or '').strip()
        external_id = str(
            item.get('Id')
            or item.get('GameId')
            or item.get('PluginId')
            or item.get('id')
            or name
        )[:32]
        if not name or not external_id:
            result.skipped += 1
            continue

        existing = db.session.execute(
            select(UserOwnedTitle).filter_by(
                user_id=user_id,
                store='playnite',
                external_app_id=external_id,
            ).with_for_update().execution_options(populate_existing=True),
        ).scalars().first()
        if existing:
            existing.name = name[:255]
            result.skipped += 1
            continue

        row = UserOwnedTitle(
            user_id=user_id,
            store='playnite',
            external_app_id=external_id,
            name=name[:255],
            matched_game_uuid=None,
        )
        db.session.add(row)
        result.imported += 1

    db.session.commit()
    return result


def import_playnite_csv(user_id: int, text: str) -> ImportResult:
    """Import a simple CSV with Name and optional Id columns."""
    result = ImportResult(errors=[])
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        result.errors.append('CSV has no header row')
        return result

    # Normalize headers
    field_map = {h.lower(): h for h in reader.fieldnames}
    name_key = field_map.get('name') or field_map.get('gamename') or field_map.get('title')
    id_key = field_map.get('id') or field_map.get('gameid')
    if not name_key:
        result.errors.append('CSV must include a Name column')
        return result

    rows = []
    for row in reader:
        rows.append({
            'Name': row.get(name_key),
            'Id': row.get(id_key) if id_key else None,
        })
    return import_playnite_json(user_id, rows)
