"""Single-player assist packs (Wand-inspired) for the desktop companion."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from flask import current_app, jsonify
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.schemas.assists import AssistPackBody
from oneirodex.utils.validation import validate_body

from . import apis_bp
from oneirodex.utils.library_paths import library_dir

_SAFE_UUID = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.I,
)


def assists_enabled() -> bool:
    return str(current_app.config.get('ENABLE_GAME_ASSISTS', 'true')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def assists_root() -> str:
    root = current_app.config.get('GAME_ASSISTS_PATH')
    if root:
        return root
    return os.path.join(library_dir(), 'assists')


def _pack_path(game_uuid: str) -> str:
    if not _SAFE_UUID.match(game_uuid or ''):
        raise ValueError('Invalid game UUID')
    folder = os.path.join(assists_root(), game_uuid)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, 'pack.json')


def load_assist_pack(game_uuid: str) -> dict[str, Any] | None:
    path = _pack_path(game_uuid)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
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
            for row in toggles
            if isinstance(row, dict) and row.get('id')
        ],
        # INSP-45 -- pages the companion overlay lists beside the game: maps,
        # guides, clips, a wiki. Links only; nothing reads or touches a process.
        'overlay_links': [
            {
                'label': str(row.get('label') or row.get('url') or '')[:120],
                'url': str(row.get('url') or '')[:2048],
                'kind': str(row.get('kind') or 'other')[:16],
            }
            for row in links
            if isinstance(row, dict) and str(row.get('url') or '').lower().startswith(('http://', 'https://'))
        ],
    }


PC_PLATFORMS = frozenset({'PCWIN', 'PCDOS', 'MAC', 'LINUX', 'OTHER'})


def default_overlay_links(game) -> list[dict[str, str]]:
    """What the overlay can always offer a PC title with no pack: the
    PCGamingWiki page (a search deep link -- the wiki resolves the title)."""
    platform = getattr(getattr(getattr(game, 'library', None), 'platform', None), 'name', None)
    if platform is not None and str(platform).upper() not in PC_PLATFORMS:
        return []
    name = (getattr(game, 'name', None) or '').strip()
    if not name:
        return []
    from urllib.parse import quote_plus

    return [{
        'label': 'PCGamingWiki',
        'url': f'https://www.pcgamingwiki.com/w/index.php?search={quote_plus(name)}',
        'kind': 'wiki',
    }]


def overlay_links_for(game, pack: dict | None) -> list[dict[str, str]]:
    """Pack links first, then the defaults not already covered by kind."""
    rows = list((pack or {}).get('overlay_links') or [])
    kinds = {row.get('kind') for row in rows}
    for row in default_overlay_links(game):
        if row['kind'] not in kinds:
            rows.append(row)
    return rows


@apis_bp.route('/games/<game_uuid>/assists', methods=['GET'])
@login_required
def get_game_assists(game_uuid):
    if not assists_enabled():
        return jsonify({'enabled': False, 'pack': None})
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    pack = load_assist_pack(game_uuid)
    return jsonify({'enabled': True, 'pack': pack, 'overlay_links': overlay_links_for(game, pack)})


@apis_bp.route('/games/<game_uuid>/assists', methods=['PUT', 'POST'])
@login_required
@admin_required
@validate_body(AssistPackBody)
def put_game_assists(game_uuid, body: AssistPackBody):
    if not assists_enabled():
        return api_error('ENABLE_GAME_ASSISTS is off', code='forbidden')
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    pack = {
        'title': body.title or game.name,
        'policy': 'single_player_offline_only',
        'toggles': [row.model_dump(exclude_none=True) for row in body.toggles],
        'overlay_links': [row.model_dump() for row in body.overlay_links],
    }
    path = _pack_path(game_uuid)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(pack, fh, indent=2)
    saved = load_assist_pack(game_uuid)
    return api_ok({'pack': saved, 'overlay_links': overlay_links_for(game, saved)})
