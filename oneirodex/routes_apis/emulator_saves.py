"""Emulator save-state API (opt-in cloud sync)."""

from __future__ import annotations

from io import BytesIO

from oneirodex.utils.api_response import api_error, api_ok
from flask import current_app, jsonify, request, send_file
from flask_wtf.csrf import generate_csrf
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.utils.emulator_saves import (
    SaveRevisionConflict,
    SaveQuotaExceeded,
    delete_save,
    is_state_slot,
    list_saves,
    read_save_bytes,
    save_sync_enabled,
    store_save,
)
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.api_tokens import require_api_scope, require_save_write

from . import apis_bp


@apis_bp.route('/games/<game_uuid>/saves', methods=['GET'])
@login_required
@require_api_scope('read:library')
def list_game_saves(game_uuid):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')

    # Newest first; `is_state` separates resumable states from SRAM so the
    # shell and the details page never offer to "resume" a battery save.
    return jsonify({
        'enabled': save_sync_enabled(),
        'game_uuid': game_uuid,
        # The WebRetro room is a static file, so it has no rendered meta tag to
        # read a CSRF token from and cannot see the HttpOnly cookie. Without
        # this every save it tried to upload was rejected as "CSRF token is
        # missing" -- silently, because the room only ever surfaced the status.
        'csrf_token': generate_csrf(),
        'can_write_own_save': _can_write_saves(current_user),
        'can_delete_own_save': _can_write_saves(current_user),
        'saves': [
            {**row.to_dict(), 'is_state': is_state_slot(row)}
            for row in list_saves(current_user.id, game_uuid)
        ],
    })


def _can_write_saves(user):
    from oneirodex.utils.api_tokens import user_has_scope
    from oneirodex.utils.role_catalog import normalize_role

    role = normalize_role(getattr(user, 'role', None))
    return user_has_scope('write:saves') or (
        role != 'child' and user_has_scope('write:library')
    )


@apis_bp.route('/games/<game_uuid>/saves', methods=['POST'])
@login_required
@require_save_write
def upload_game_save(game_uuid):
    if not save_sync_enabled():
        return api_error('Emulator save sync is disabled', code='forbidden')

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')

    upload = request.files.get('file') or request.files.get('save')
    if not upload:
        return api_error('multipart file field "file" is required', code='bad_request')
    slot = (request.form.get('slot') or request.args.get('slot') or 'slot1').strip()

    try:
        raw_revision = request.form.get('expected_revision')
        expected_revision = int(raw_revision) if raw_revision not in (None, '') else None
        row = store_save(
            user_id=current_user.id,
            game_uuid=game_uuid,
            slot_name=slot,
            file_storage=upload,
            expected_revision=expected_revision,
        )
    except SaveRevisionConflict as exc:
        return api_error(
            str(exc), code=exc.code,
            detail={'current_revision': exc.current_revision},
        )
    except SaveQuotaExceeded as exc:
        return api_error(str(exc), code=exc.code)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except RuntimeError as exc:
        return api_error(str(exc), code='forbidden')

    return jsonify(row.to_dict()), 201


@apis_bp.route('/games/<game_uuid>/saves/<slot_name>', methods=['GET'])
@login_required
@require_api_scope('read:library')
def download_game_save(game_uuid, slot_name):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')

    rows = list_saves(current_user.id, game_uuid)
    row = next((item for item in rows if item.slot_name == slot_name), None)
    if not row:
        return api_error('Save not found', code='not_found')
    try:
        payload = read_save_bytes(row)
    except FileNotFoundError:
        return api_error('Save not found', code='not_found')
    except Exception:
        # An OSError's text carries the on-disk save path; the operator gets the
        # traceback in the log, the member gets a fixed sentence.
        current_app.logger.exception(
            'Failed to read emulator save (game %s, slot %r)', game_uuid, slot_name,
        )
        return api_error('Failed to read save', code='internal')

    return send_file(
        BytesIO(payload),
        as_attachment=True,
        download_name=row.filename,
        mimetype='application/octet-stream',
    )


@apis_bp.route('/games/<game_uuid>/saves/<slot_name>', methods=['DELETE'])
@login_required
@require_save_write
def delete_game_save(game_uuid, slot_name):
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('Forbidden', code='forbidden')
    if not delete_save(current_user.id, game_uuid, slot_name):
        return api_error('Save not found', code='not_found')
    return api_ok({'status': 'deleted', 'slot_name': slot_name})
