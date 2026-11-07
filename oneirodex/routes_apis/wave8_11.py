"""Frontend export + plugin/activity/mods API routes (Waves 8–11)."""

from __future__ import annotations

import json
from typing import Iterable

from flask import Response, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, Library
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.activity_feed import list_now_playing, list_recent_activity
from oneirodex.utils.api_response import api_error
from oneirodex.utils.auth import admin_required
from oneirodex.utils.frontend_export import (
    build_es_de_gamelist,
    build_pegasus_metadata,
    portable_export_path,
)
from oneirodex.utils.library_acl import apply_game_access_filters
from oneirodex.utils.plugins import get_plugin, list_plugins
from oneirodex.utils.rbac import normalize_role
from oneirodex.utils.security import get_allowed_base_directories
from oneirodex.utils.api_tokens import require_api_scope, require_api_token_scope
from sqlalchemy.orm import joinedload

from . import apis_bp


def _games_for_platform(platform: str | None) -> Iterable[Game]:
    query = Game.query
    query = apply_game_access_filters(query, current_user)
    query = query.join(Library).options(joinedload(Game.library))
    if platform:
        requested = str(platform).strip().lower()
        member = next((item for item in LibraryPlatform if (
            item.name.lower() == requested or item.value.lower() == requested
        )), None)
        if member is None:
            return []
        query = query.filter(Library.platform == member)
    return query.order_by(Game.name.asc(), Game.uuid.asc()).yield_per(250)


def _game_rows(games: Iterable[Game]) -> Iterable[dict]:
    roots = get_allowed_base_directories(current_app)
    def iter_rows():
        for game in games:
            disk = getattr(game, 'full_disk_path', None) or ''
            yield {
                'uuid': game.uuid,
                'name': game.name,
                'summary': getattr(game, 'summary', None) or '',
                'path': portable_export_path(disk, library_roots=roots) or game.name,
                'cover_url': getattr(game, 'cover', None) or '',
                'developer': '',
                'publisher': '',
                'genre': '',
            }
    return iter_rows()


@apis_bp.route('/export/esde', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def export_esde():
    platform = (request.args.get('platform') or '').strip()
    games = _games_for_platform(platform or None)
    roots = get_allowed_base_directories(current_app)
    xml = build_es_de_gamelist(
        _game_rows(games),
        system=platform or 'all',
        library_roots=roots,
    )
    return Response(
        xml,
        mimetype='application/xml',
        headers={'Content-Disposition': f'attachment; filename="gamelist-{platform or "all"}.xml"'},
    )


@apis_bp.route('/export/pegasus', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def export_pegasus():
    platform = (request.args.get('platform') or '').strip() or 'Library'
    games = _games_for_platform(platform if platform != 'Library' else None)
    roots = get_allowed_base_directories(current_app)
    text = build_pegasus_metadata(
        _game_rows(games),
        collection=platform,
        library_roots=roots,
    )
    return Response(
        text,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename="metadata-{platform}.pegasus.txt"'},
    )


@apis_bp.route('/plugins', methods=['GET'])
@login_required
@admin_required
def plugins_list():
    category = request.args.get('category')
    return jsonify({'plugins': list_plugins(category=category)})


@apis_bp.route('/plugins/<plugin_id>', methods=['GET'])
@login_required
@admin_required
def plugins_get(plugin_id):
    row = get_plugin(plugin_id)
    if not row:
        return api_error('Not found', code='not_found')
    return jsonify(row)


@apis_bp.route('/activity', methods=['GET'])
@login_required
@require_api_scope('read:social')
def activity_feed():
    role = normalize_role(getattr(current_user, 'role', None))
    # Child accounts only see their own sessions via playtime/me; keep feed for others.
    if role == 'child':
        return jsonify({'activity': [], 'now_playing': [], 'restricted': True})
    try:
        limit = min(100, max(1, int(request.args.get('limit') or 25)))
    except (TypeError, ValueError, OverflowError):
        # Match the native ASGI route: malformed pagination uses its default.
        limit = 25
    friends_only = str(request.args.get('friends_only') or '').lower() in ('1', 'true', 'yes')
    return jsonify({
        'activity': list_recent_activity(
            limit=limit, viewer=current_user, friends_only=friends_only,
        ),
        'now_playing': list_now_playing(viewer=current_user, friends_only=friends_only),
        'friends_only': friends_only,
    })


@apis_bp.route('/activity/stream', methods=['GET'])
@login_required
@require_api_scope('read:social')
def activity_stream():
    """WSGI fallback — real SSE is native ASGI (`asgi.py`) to avoid worker starvation."""
    role = normalize_role(getattr(current_user, 'role', None))
    if role == 'child':
        return api_error('Restricted', code='forbidden')
    return api_error(
        'SSE requires ASGI',
        code='unavailable',
        detail=(
            'Serve Oneirodex with uvicorn asgi:asgi_app. '
            '/api/activity/stream is handled natively outside WsgiToAsgi.'
        ),
    )


@apis_bp.route('/emulator/health', methods=['GET'])
@login_required
def emulator_core_health():
    from oneirodex.platform import core_is_browser_playable
    from oneirodex.utils.webretro_cores import (
        deferred_core_status,
        get_effective_installed_cores,
    )

    cores = sorted(get_effective_installed_cores())
    return jsonify({
        'installed_cores': cores,
        'pcdos_browser': bool(current_app.config.get('ENABLE_PCDOS_BROWSER')),
        'core_checks': {core: core_is_browser_playable(core) for core in cores},
        'deferred_cores': deferred_core_status(),
    })


@apis_bp.route('/emulator/installed-cores.js', methods=['GET'])
def emulator_installed_cores_js():
    """Disk-backed allowlist for WebRetro (no login — play iframe needs it early)."""
    from oneirodex.utils.webretro_cores import get_effective_installed_cores

    cores = sorted(get_effective_installed_cores())
    # Compact JSON array; names are [a-z0-9_] only from our discovery/allowlist.
    payload = 'var OD_INSTALLED_CORES = ' + json.dumps(cores) + ';\n'
    return Response(
        payload,
        mimetype='application/javascript',
        headers={'Cache-Control': 'private, max-age=300'},
    )
