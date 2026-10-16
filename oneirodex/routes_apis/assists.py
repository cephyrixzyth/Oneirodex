"""Single-player assist packs (Wand-inspired) for the desktop companion."""

from __future__ import annotations

import json
from typing import Any

from flask import current_app, has_app_context, jsonify
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.schemas.assists import AssistPackBody
from oneirodex.utils.validation import validate_body
from oneirodex.utils.assist_packs import (
    assists_enabled as _assists_enabled,
    assists_root as _assists_root,
    default_overlay_links,
    load_assist_pack as _load_assist_pack,
    overlay_links_for,
    pack_path as _assist_pack_path,
)

from . import apis_bp


def _package_root(package_root):
    if package_root is not None:
        return package_root
    return current_app.root_path if has_app_context() else None

def assists_enabled(*, config=None) -> bool:
    return _assists_enabled(config=config if config is not None else current_app.config)


def assists_root(*, config=None, package_root=None) -> str:
    return _assists_root(
        config=config if config is not None else current_app.config,
        package_root=_package_root(package_root),
    )


def _pack_path(game_uuid: str, *, config=None, package_root=None) -> str:
    return _assist_pack_path(
        game_uuid,
        config=config if config is not None else current_app.config,
        package_root=_package_root(package_root),
    )


def load_assist_pack(game_uuid: str, *, config=None, package_root=None) -> dict[str, Any] | None:
    return _load_assist_pack(
        game_uuid, config=config if config is not None else current_app.config,
        package_root=_package_root(package_root),
    )


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
