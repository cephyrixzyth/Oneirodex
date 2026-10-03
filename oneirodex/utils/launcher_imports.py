"""Launcher import framework: bring a library in from another launcher's export.

Register-only, like every ownership source: an import records *that a member
owns a title*, never downloads, installs or reads credentials. Each launcher is
one :class:`LauncherFormat` -- a name, the ``store`` its rows are recorded
under, a sniffer and a parser. Adding a launcher that has an export is one
entry in :data:`FORMATS` plus a parser; nothing else in the pipeline changes.

Rows go through :func:`upsert_owned_title`, so an import is idempotent (same id
refreshes the name), never overwrites a reviewed match, and never auto-links on
a name alone -- unmatched titles land in the existing review queue.

Supported today: Playnite (JSON/CSV), Heroic (``legendary_library.json``,
``gog_library.json``, ``nile_library.json``, sideload library), Lutris
(``lutris -l -j``), GOG Galaxy (community JSON exports) and a generic CSV.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Callable

from oneirodex import db
from oneirodex.utils.store_ownership_common import EXTERNAL_APP_ID_MAX, upsert_owned_title

__all__ = [
    'FORMATS', 'LauncherFormat', 'ParsedTitle', 'ImportOutcome',
    'detect_format', 'import_launcher_export', 'parse_export',
]

#: Hard cap so a pasted multi-hundred-MB file cannot hold a worker.
MAX_TITLES = 50_000


@dataclass(frozen=True)
class ParsedTitle:
    external_id: str
    name: str


@dataclass
class ImportOutcome:
    launcher: str
    store: str
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'launcher': self.launcher,
            'store': self.store,
            'imported': self.imported,
            'updated': self.updated,
            'skipped': self.skipped,
            'errors': list(self.errors),
        }


@dataclass(frozen=True)
class LauncherFormat:
    key: str
    name: str
    store: str  # value recorded in UserOwnedTitle.store (<= 16 chars)
    sniff: Callable[[object], bool]
    parse: Callable[[object], list[ParsedTitle]]
    accepts_csv: bool = True


class _CsvRows(list):
    """Rows read from a CSV: already normalised to ``Name`` / ``Id`` keys."""


def _items(data) -> list:
    """The list of game objects inside the common export envelopes."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ('Games', 'games', 'library', 'items', 'Library'):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _first(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ''):
            return str(value).strip()
    return ''


def _dicts(data) -> list[dict]:
    return [item for item in _items(data) if isinstance(item, dict)]


# --- Playnite -----------------------------------------------------------------

def _sniff_playnite(data) -> bool:
    items = _dicts(data)
    return bool(items) and any(('Name' in i or 'GameName' in i or 'name' in i) for i in items[:20])


def _parse_playnite(data) -> list[ParsedTitle]:
    out = []
    for item in _dicts(data):
        name = _first(item, 'Name', 'name', 'GameName')
        ident = _first(item, 'Id', 'GameId', 'PluginId', 'id') or name
        if name and ident:
            out.append(ParsedTitle(ident, name))
    return out


# --- Heroic ---------------------------------------------------------------------

def _sniff_heroic(data) -> bool:
    items = _dicts(data)
    return bool(items) and any('app_name' in i for i in items[:20])


def _parse_heroic(data) -> list[ParsedTitle]:
    out = []
    for item in _dicts(data):
        ident = _first(item, 'app_name', 'appName', 'id')
        name = _first(item, 'title', 'name') or ident
        runner = _first(item, 'runner')
        if ident and name:
            # Heroic app names are only unique per runner (store).
            out.append(ParsedTitle(f'{runner}:{ident}' if runner else ident, name))
    return out


# --- Lutris ---------------------------------------------------------------------

def _sniff_lutris(data) -> bool:
    items = _dicts(data)
    return bool(items) and any(('slug' in i and 'runner' in i) for i in items[:20])


def _parse_lutris(data) -> list[ParsedTitle]:
    out = []
    for item in _dicts(data):
        ident = _first(item, 'slug', 'id')
        name = _first(item, 'name')
        if ident and name:
            out.append(ParsedTitle(ident, name))
    return out


# --- GOG Galaxy -----------------------------------------------------------------

def _sniff_galaxy(data) -> bool:
    items = _dicts(data)
    return bool(items) and any(
        ('releaseKey' in i or 'release_key' in i or ('title' in i and 'platform' in i))
        for i in items[:20]
    )


def _parse_galaxy(data) -> list[ParsedTitle]:
    out = []
    for item in _dicts(data):
        name = _first(item, 'title', 'Title', 'name')
        platform = _first(item, 'platform', 'platformId', 'Platform')
        ident = _first(item, 'releaseKey', 'release_key')
        if not ident and name:
            ident = f'{platform}:{name}' if platform else name
        if ident and name:
            out.append(ParsedTitle(ident, name))
    return out


# --- Generic CSV ------------------------------------------------------------------

def _sniff_generic(data) -> bool:
    return bool(_dicts(data))


FORMATS: dict[str, LauncherFormat] = {
    # Order matters for auto-detection: the most specific sniffers first.
    'heroic': LauncherFormat('heroic', 'Heroic', 'heroic', _sniff_heroic, _parse_heroic),
    'lutris': LauncherFormat('lutris', 'Lutris', 'lutris', _sniff_lutris, _parse_lutris),
    'galaxy': LauncherFormat('galaxy', 'GOG Galaxy', 'galaxy', _sniff_galaxy, _parse_galaxy),
    'playnite': LauncherFormat('playnite', 'Playnite', 'playnite', _sniff_playnite, _parse_playnite),
    'import': LauncherFormat('import', 'Other launcher (CSV)', 'import', _sniff_generic, _parse_playnite),
}

_CSV_NAME_HEADERS = ('name', 'title', 'gamename', 'game')
_CSV_ID_HEADERS = ('id', 'gameid', 'appid', 'app_id', 'app_name', 'slug', 'releasekey')


def _load(text: str | bytes | object, filename: str = ''):
    """Decode an export to a JSON-like value (CSV becomes a list of dicts)."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode('utf-8-sig')
    if not isinstance(text, str):
        return text
    stripped = text.lstrip('﻿').strip()
    if not stripped:
        raise ValueError('The file is empty')
    if filename.lower().endswith('.csv') or stripped[0] not in '[{':
        reader = csv.DictReader(io.StringIO(stripped))
        if not reader.fieldnames:
            raise ValueError('CSV has no header row')
        names = {h.strip().lower(): h for h in reader.fieldnames if h}
        name_key = next((names[h] for h in _CSV_NAME_HEADERS if h in names), None)
        if not name_key:
            raise ValueError('CSV must include a Name or Title column')
        id_key = next((names[h] for h in _CSV_ID_HEADERS if h in names), None)
        return _CsvRows(
            {'Name': row.get(name_key), 'Id': row.get(id_key) if id_key else None}
            for row in reader
        )
    return json.loads(stripped)


def detect_format(data) -> LauncherFormat | None:
    if isinstance(data, _CsvRows):
        return FORMATS['import']
    for fmt in FORMATS.values():
        if fmt.key != 'import' and fmt.sniff(data):
            return fmt
    return FORMATS['import'] if FORMATS['import'].sniff(data) else None


def parse_export(text, *, filename: str = '', launcher: str | None = None) -> tuple[LauncherFormat, list[ParsedTitle]]:
    """Decode and parse an export. ``launcher`` pins the format; otherwise sniffed.

    Raises ``ValueError`` with a member-safe sentence for anything unreadable.
    """
    try:
        data = _load(text, filename)
    except json.JSONDecodeError as exc:
        raise ValueError('The file is not valid JSON or CSV') from exc
    except UnicodeDecodeError as exc:
        raise ValueError('The file must be UTF-8 text') from exc
    if launcher:
        fmt = FORMATS.get(launcher)
        if fmt is None:
            raise ValueError(f'Unknown launcher: {launcher}')
    else:
        fmt = detect_format(data)
        if fmt is None:
            raise ValueError('No games found in that export')
    # CSV rows are already normalised, whichever launcher the member says they
    # came from; the hint only decides which store the rows are recorded under.
    titles = (_parse_playnite if isinstance(data, _CsvRows) else fmt.parse)(data)
    if len(titles) > MAX_TITLES:
        raise ValueError(f'That export has more than {MAX_TITLES} titles')
    return fmt, titles


def import_launcher_export(
    user_id: int,
    text,
    *,
    filename: str = '',
    launcher: str | None = None,
) -> ImportOutcome:
    """Parse an export and record its titles as owned by ``user_id``."""
    fmt, titles = parse_export(text, filename=filename, launcher=launcher)
    outcome = ImportOutcome(launcher=fmt.key, store=fmt.store)
    if not titles:
        outcome.errors.append('No games found in that export')
        return outcome
    seen: set[str] = set()
    for title in titles:
        ident = title.external_id[:EXTERNAL_APP_ID_MAX]
        if ident in seen:
            outcome.skipped += 1
            continue
        seen.add(ident)
        row = upsert_owned_title(user_id, fmt.store, ident, title.name)
        if row.id is None:
            outcome.imported += 1
        else:
            outcome.updated += 1
    db.session.commit()
    return outcome
