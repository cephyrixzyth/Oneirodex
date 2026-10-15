"""Single-player assist pack storage and overlay projections."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from oneirodex.utils.library_paths import library_dir

_SAFE_UUID = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I,
)
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_PC_PLATFORMS = frozenset({'PCWIN', 'PCDOS', 'MAC', 'LINUX', 'OTHER'})


def assists_enabled(*, config=None) -> bool:
    values = config or {}
    return str(values.get('ENABLE_GAME_ASSISTS', 'true')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def assists_root(*, config=None, package_root=None) -> str:
    values = config or {}
    root = values.get('GAME_ASSISTS_PATH')
    if root:
        return str(root)
    library_root = library_dir(package_root or _PACKAGE_ROOT)
    return os.path.join(library_root, 'assists')


def pack_path(game_uuid: str, *, config=None, package_root=None) -> str:
    if not _SAFE_UUID.match(game_uuid or ''):
        raise ValueError('Invalid game UUID')
    folder = os.path.join(assists_root(config=config, package_root=package_root), game_uuid)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, 'pack.json')


def load_assist_pack(game_uuid: str, *, config=None, package_root=None) -> dict[str, Any] | None:
    path = pack_path(game_uuid, config=config, package_root=package_root)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    toggles = data.get('toggles')
    if not isinstance(toggles, list):
        toggles = []
    links = data.get('overlay_links')
    if not isinstance(links, list):
        links = []
    return {
        'game_uuid': game_uuid,
        'title': data.get('title') or 'Assists',
        'policy': data.get('policy') or 'single_player_offline_only',
        'toggles': [
            {
                'id': str(row.get('id') or ''),
                'label': str(row.get('label') or row.get('id') or 'Toggle'),
                'description': str(row.get('description') or ''),
            }
            for row in toggles if isinstance(row, dict) and row.get('id')
        ],
        'overlay_links': [
            {
                'label': str(row.get('label') or row.get('url') or '')[:120],
                'url': str(row.get('url') or '')[:2048],
                'kind': str(row.get('kind') or 'other')[:16],
            }
            for row in links
            if isinstance(row, dict)
            and str(row.get('url') or '').lower().startswith(('http://', 'https://'))
        ],
    }


def default_overlay_links(game) -> list[dict[str, str]]:
    platform = getattr(getattr(getattr(game, 'library', None), 'platform', None), 'name', None)
    if platform is not None and str(platform).upper() not in _PC_PLATFORMS:
        return []
    name = (getattr(game, 'name', None) or '').strip()
    if not name:
        return []
    return [{
        'label': 'PCGamingWiki',
        'url': f'https://www.pcgamingwiki.com/w/index.php?search={quote_plus(name)}',
        'kind': 'wiki',
    }]


def overlay_links_for(game, pack: dict | None) -> list[dict[str, str]]:
    rows = list((pack or {}).get('overlay_links') or [])
    kinds = {row.get('kind') for row in rows}
    for row in default_overlay_links(game):
        if row['kind'] not in kinds:
            rows.append(row)
    return rows
