"""Companion client presence APIs."""

import uuid

from oneirodex.utils.api_response import api_error, api_ok
from flask import current_app, g, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, GameExtra, GameUpdate
from oneirodex.utils.api_tokens import require_api_scope, user_has_scope
from oneirodex.utils.client_capabilities import (
    normalize_device_kind,
    resolve_client_capabilities,
    should_deliver_install_commands,
)
from oneirodex.utils.client_commands import (
    WRITE_DOWNLOAD_ACTIONS,
    ack_client_commands,
    claim_pending_commands,
    enqueue_client_command,
    nack_client_commands,
)
from oneirodex.utils.client_lifecycle import load_lifecycle_map, save_lifecycle_records
from oneirodex.utils.client_presence import record_client_heartbeat
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.schemas.client import ClientLifecycleBody
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _api_token():
    return getattr(g, 'api_token', None)


def _has_companion_token() -> bool:
    return _api_token() is not None


def _capabilities_payload(device_kind: str | None = None) -> dict:
    return resolve_client_capabilities(
        device_kind,
        api_token=_api_token(),
    )


@apis_bp.route('/client/capabilities', methods=['GET'])
@login_required
def client_capabilities_get():
    """Advertise browse/social/lifecycle allows and denies for the current seat."""
    kind = request.args.get('device_kind')
    return jsonify(_capabilities_payload(kind))


@apis_bp.route('/client/heartbeat', methods=['POST'])
@login_required
def client_heartbeat():
    # CSRF-exempt for companion tokens only: a session-cookie caller (a
    # browser) must pass the normal CSRF check, or any site could post here.
    if not _has_companion_token() and current_app.config.get('WTF_CSRF_ENABLED', True):
        from oneirodex import csrf

        csrf.protect()
    data = request.get_json(silent=True) or {}
    device_id = (data.get('device_id') or '').strip()
    if not device_id:
        device_id = str(uuid.uuid4())

    device_kind = normalize_device_kind(data.get('device_kind'))
    device = record_client_heartbeat(
        current_user.id,
        device_id,
        device_kind=device_kind,
        device_name=data.get('device_name'),
        client_version=data.get('client_version'),
        user_agent=request.headers.get('User-Agent'),
    )
    payload = device.to_dict()
    payload.update(_capabilities_payload(device.device_kind))
    if should_deliver_install_commands(device.device_kind, api_token=_api_token()):
        payload['commands'] = claim_pending_commands(current_user.id)
    else:
        payload['commands'] = []
    return jsonify(payload)


@apis_bp.route('/client/lifecycle', methods=['GET'])
@login_required
@require_api_scope('read:library')
def client_lifecycle_get():
    mapping = load_lifecycle_map(current_user.id)
    records = [{'game_uuid': uuid, 'state': state} for uuid, state in mapping.items()]
    return jsonify({'records': records})


@apis_bp.route('/client/lifecycle', methods=['POST'])
@login_required
@validate_body(ClientLifecycleBody)
def client_lifecycle_post(body: ClientLifecycleBody):
    # Sec-B: Bearer-only — CSRF-exempt endpoint must not accept session cookie alone.
    if not _has_companion_token():
        return api_error('Companion API token required', code='forbidden')
    # Companion tokens typically carry write:download; library write also accepted.
    if not (
        user_has_scope('write:download')
        or user_has_scope('write:library')
    ):
        return api_error('Missing scope: write:download or write:library', code='forbidden')
    mapping = save_lifecycle_records(
        current_user.id, body.records, replace=bool(body.replace),
    )
    return api_ok({
                'count': len(mapping),
        'records': [{'game_uuid': uuid, 'state': state} for uuid, state in mapping.items()],
    })


@apis_bp.route('/client/commands', methods=['POST'])
@login_required
def client_commands_post():
    """Queue a companion action from the member SPA / admin scanjobs / game details."""
    data = request.get_json(silent=True) or {}
    game_uuid = (data.get('game_uuid') or '').strip()
    action = (data.get('action') or '').strip().lower()
    kind = data.get('kind')
    version_uuid = (data.get('version_uuid') or '').strip() or None
    open_path = (data.get('path') or '').strip() or None
    select_in_folder = data.get('select')

    if action in WRITE_DOWNLOAD_ACTIONS and not user_has_scope('write:download'):
        return api_error(
            'Missing scope: write:download',
            code='forbidden',
            detail={'required_scope': 'write:download'},
        )

    if action == 'open_path':
        # Unmatched / admin scanjobs may omit game_uuid; matched titles still ACL-check.
        if game_uuid:
            game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
            if not game:
                return api_error('Game not found', code='not_found')
            if not user_can_access_game(current_user, game):
                return api_error('Forbidden', code='forbidden')
        try:
            command = enqueue_client_command(
                current_user.id,
                game_uuid,
                action,
                path=open_path,
                select=None if select_in_folder is None else bool(select_in_folder),
            )
        except ValueError as exc:
            return api_error(str(exc), code='bad_request')
        return api_ok({'command': command}, status=201)

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')

    if kind in ('update', 'extra') and version_uuid:
        Model = GameUpdate if kind == 'update' else GameExtra
        pack = db.session.execute(
            select(Model).filter_by(game_uuid=game.uuid, uuid=version_uuid)
        ).scalars().first()
        if not pack:
            return api_error('Version not found for game', code='not_found')
        if action == 'apply_patch':
            if getattr(pack, 'extra_kind', None) != 'translation_patch':
                return api_error('Version is not a translation patch', code='bad_request')

    try:
        command = enqueue_client_command(
            current_user.id,
            game_uuid,
            action,
            kind=kind,
            version_uuid=version_uuid,
        )
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'command': command}, status=201)


@apis_bp.route('/client/commands', methods=['GET'])
@login_required
@require_api_scope('read:library')
def client_commands_get():
    """Explicit poll for pending commands (companion may also use heartbeat)."""
    if not _has_companion_token():
        return api_error('Companion API token required', code='forbidden')
    device_kind = normalize_device_kind(request.args.get('device_kind'))
    if not should_deliver_install_commands(device_kind, api_token=_api_token()):
        return jsonify({'commands': []})
    limit = request.args.get('limit', 10, type=int) or 10
    limit = max(1, min(limit, 25))
    return jsonify({'commands': claim_pending_commands(current_user.id, limit=limit)})


@apis_bp.route('/client/commands/ack', methods=['POST'])
@login_required
def client_commands_ack():
    if not _has_companion_token():
        return api_error('Companion API token required', code='forbidden')
    data = request.get_json(silent=True) or {}
    ids = data.get('ids') if isinstance(data.get('ids'), list) else []
    removed = ack_client_commands(current_user.id, [str(i) for i in ids])
    return api_ok({'removed': removed})


@apis_bp.route('/client/commands/nack', methods=['POST'])
@login_required
def client_commands_nack():
    if not _has_companion_token():
        return api_error('Companion API token required', code='forbidden')
    data = request.get_json(silent=True) or {}
    ids = data.get('ids') if isinstance(data.get('ids'), list) else []
    released = nack_client_commands(current_user.id, [str(i) for i in ids])
    return api_ok({'released': released})
