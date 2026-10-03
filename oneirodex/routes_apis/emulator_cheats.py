"""Emulator cheats (.cht) and BIOS management APIs."""

from __future__ import annotations

import os
from io import BytesIO

from flask import current_app, jsonify, request, send_file
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.platform import cheat_surface_for_platform
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.bios_install import (
    apply_firmware_import,
    firmware_import_allowed_bases,
    plan_firmware_import,
    volume_missing_markdown,
)
from oneirodex.utils.emulator_bios import (
    bios_status_for_cores,
    bios_status_for_platforms,
    list_bios_files,
    store_bios_file,
)
from oneirodex.utils.emulator_cheats import (
    CheatLimitError,
    create_cheat_file,
    delete_cheat_file,
    list_cheat_files,
    read_cheat_file,
    store_cheat_file,
)
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.play_url import library_platform_key
from oneirodex.utils.rbac import librarian_required, normalize_role
from oneirodex.utils.security import is_safe_path
from oneirodex.schemas.emulator_cheats import CreatePcCheatBody
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _game_cheat_surface(game) -> str:
    return cheat_surface_for_platform(library_platform_key(game))


def _accessible_game(game_uuid: str):
    """Load a game the caller may see, or the response that refuses it.

    Five handlers opened with these four lines. Returns ``(game, None)`` on
    success and ``(None, response)`` otherwise.

    Note `pc_cheats_create` deliberately keeps its own lookup: it is
    `librarian_required` and does not apply the per-library ACL, matching how
    privileged roles bypass ownership elsewhere in the tree.
    """
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return None, api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return None, api_error('You do not have access to that game', code='forbidden')
    return game, None


def _refuse_non_retroarch(game):
    """Mutating .cht ops only for RetroArch-capable platforms (GM Wave 19)."""
    surface = _game_cheat_surface(game)
    if surface != 'retroarch':
        return api_error(
            'RetroArch cheats are not available for this platform',
            code='forbidden',
            cheat_surface=surface,
        )
    return None


@apis_bp.route('/games/<game_uuid>/cheats', methods=['GET'])
@login_required
def list_game_cheats(game_uuid):
    game, refusal = _accessible_game(game_uuid)
    if refusal is not None:
        return refusal
    surface = _game_cheat_surface(game)
    cheats = list_cheat_files(game_uuid) if surface == 'retroarch' else []
    return jsonify({
        'game_uuid': game_uuid,
        'cheat_surface': surface,
        'cheats': cheats,
    })


@apis_bp.route('/games/<game_uuid>/cheats', methods=['POST'])
@login_required
def upload_game_cheat(game_uuid):
    """Upload a prebuilt .cht or easy-create from JSON body.

    Multipart: ``file`` = .cht upload (legacy).
    JSON: ``{ name, codes: [{desc?, code}], dialect? }`` → write .cht.
    """
    game, refusal = _accessible_game(game_uuid)
    if refusal is not None:
        return refusal
    if normalize_role(current_user.role) == 'child':
        return api_error('Children cannot modify cheats', code='forbidden')
    refused = _refuse_non_retroarch(game)
    if refused is not None:
        return refused

    upload = request.files.get('file')
    if upload is not None and (getattr(upload, 'filename', None) or '').strip():
        try:
            row = store_cheat_file(game_uuid, upload)
        except CheatLimitError as exc:
            return api_error(str(exc), code=exc.code)
        except ValueError as exc:
            return api_error(str(exc), code='bad_request')
        return jsonify(row), 201

    data = request.get_json(silent=True)
    if isinstance(data, dict):
        try:
            row = create_cheat_file(
                game_uuid,
                name=data.get('name'),
                codes=data.get('codes'),
                dialect=data.get('dialect'),
            )
        except CheatLimitError as exc:
            return api_error(str(exc), code=exc.code)
        except ValueError as exc:
            return api_error(str(exc), code='bad_request')
        return jsonify(row), 201

    return api_error('Send a .cht file, or a JSON body with name and codes', code='bad_request')


@apis_bp.route('/games/<game_uuid>/cheats/<path:filename>', methods=['GET'])
@login_required
def download_game_cheat(game_uuid, filename):
    game, refusal = _accessible_game(game_uuid)
    if refusal is not None:
        return refusal
    refused = _refuse_non_retroarch(game)
    if refused is not None:
        return refused
    try:
        payload = read_cheat_file(game_uuid, filename)
    except (ValueError, FileNotFoundError) as exc:
        return api_error(str(exc), code='not_found')
    return send_file(
        BytesIO(payload),
        mimetype='text/plain',
        as_attachment=True,
        download_name=filename,
    )


@apis_bp.route('/games/<game_uuid>/cheats/<path:filename>', methods=['DELETE'])
@login_required
def remove_game_cheat(game_uuid, filename):
    game, refusal = _accessible_game(game_uuid)
    if refusal is not None:
        return refusal
    if normalize_role(current_user.role) == 'child':
        return api_error('Children cannot modify cheats', code='forbidden')
    refused = _refuse_non_retroarch(game)
    if refused is not None:
        return refused
    try:
        delete_cheat_file(game_uuid, filename)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok()


def _firmware_collection_source():
    """Resolve the operator's collection folder, or an envelope error.

    Allowed bases are library roots plus ``BIOS_IMPORT_SOURCE``. The error
    sentence does not echo the path.
    """
    payload = request.get_json(silent=True) or {}
    raw = (payload.get('source') or '').strip()
    if not raw:
        raw = (current_app.config.get('BIOS_IMPORT_SOURCE') or '').strip()
    if not raw:
        return None, api_error(
            'Set a firmware collection folder, or configure BIOS_IMPORT_SOURCE.',
            code='bad_request',
        )
    if not os.path.isdir(raw):
        return None, api_error(
            'That folder does not exist on the server.',
            code='not_found',
        )
    allowed, _reason = is_safe_path(raw, firmware_import_allowed_bases(current_app))
    if not allowed:
        return None, api_error(
            'That folder is outside the allowed directories. Point '
            'BIOS_IMPORT_SOURCE at it, or use a path under a library root.',
            code='forbidden',
        )
    return raw, None


@apis_bp.route('/emulator-bios', methods=['GET'])
@login_required
@admin_required
def emulator_bios_list():
    return jsonify({
        'files': list_bios_files(),
        'cores': bios_status_for_cores(),
        # Per-system view: which consoles can actually boot, and what is missing.
        'platforms': bios_status_for_platforms(),
        'import_source': current_app.config.get('BIOS_IMPORT_SOURCE') or '',
        'missing_markdown': volume_missing_markdown(),
    })


@apis_bp.route('/emulator-bios/scan', methods=['POST'])
@login_required
@admin_required
def emulator_bios_scan():
    source, err = _firmware_collection_source()
    if err is not None:
        return err
    try:
        plan = plan_firmware_import(source)
    except OSError:
        return api_error(
            'Could not read that firmware collection.',
            code='internal',
        )
    return api_ok(plan)


@apis_bp.route('/emulator-bios/install', methods=['POST'])
@login_required
@admin_required
def emulator_bios_install():
    source, err = _firmware_collection_source()
    if err is not None:
        return err
    payload = request.get_json(silent=True) or {}
    selections = payload.get('selections') or {}
    if selections and not isinstance(selections, dict):
        return api_error('selections must be a map of filename to dump.', code='bad_request')
    skipped = payload.get('skipped') or []
    if skipped and not isinstance(skipped, list):
        return api_error('skipped must be a list of filenames.', code='bad_request')
    try:
        result = apply_firmware_import(
            source,
            selections={str(k): str(v) for k, v in selections.items()},
            skipped=[str(name) for name in skipped],
            overwrite=bool(payload.get('overwrite')),
        )
    except OSError:
        return api_error(
            'Could not write to the firmware volume. Check the mount is present and writable.',
            code='internal',
        )
    return api_ok(result)


@apis_bp.route('/emulator-bios', methods=['POST'])
@login_required
@admin_required
def emulator_bios_upload():
    upload = request.files.get('file')
    if upload is None:
        return api_error('Choose a firmware file to upload.', code='bad_request')
    try:
        row = store_bios_file(upload)
    except ValueError as exc:
        # store_bios_file raises user-safe messages only (no paths, no secrets).
        return api_error(str(exc), code='unprocessable')
    except OSError:
        return api_error(
            'Could not write to the firmware volume. Check the mount is present and writable.',
            code='internal',
        )
    return api_ok(row, status=201)


# --- FEAT-D2: PC cheat notes -------------------------------------------------
# The stance reversal that opened this kept three guardrails, enforced here:
#   1. `.cht` stays RetroArch-only — this is a separate surface, not a way to
#      write cheat files for cores.
#   2. Data is operator-authored. Nothing scrapes third-party trainer sites.
#   3. Never writes to a game binary or a running process — these are notes.

PC_CHEAT_METHODS = {
    'console': 'In-game console command',
    'config': 'Config / ini file edit',
    'save': 'Save-file field (external editor)',
    'launch_flag': 'Launch option / command-line flag',
    'note': 'Note',
}


def _pc_surface_or_error(game):
    """PC cheats only apply to the native-PC surface."""
    surface = _game_cheat_surface(game)
    if surface != 'pc_wand':
        return None, api_error(
            'PC cheats apply to PC titles. This platform uses the '
            'RetroArch cheat surface.',
            code='bad_request',
            cheat_surface=surface,
        )
    return surface, None


@apis_bp.route('/games/<game_uuid>/pc_cheats', methods=['GET'])
@login_required
def pc_cheats_list(game_uuid: str):
    """Cheat notes for a PC game."""
    from oneirodex.models import PcCheat

    game, refusal = _accessible_game(game_uuid)
    if refusal is not None:
        return refusal

    _, error = _pc_surface_or_error(game)
    if error:
        return error

    rows = db.session.execute(
        select(PcCheat).filter_by(game_uuid=game_uuid).order_by(PcCheat.id.asc())
    ).scalars().all()
    return api_ok({
        'game_uuid': game_uuid,
        'methods': [{'id': k, 'label': v} for k, v in PC_CHEAT_METHODS.items()],
        'cheats': [row.to_dict() for row in rows],
        'stance': (
            'Notes only — Oneirodex never modifies game files or injects into a '
            'running game. Single-player use.'
        ),
    })


@apis_bp.route('/games/<game_uuid>/pc_cheats', methods=['POST'])
@login_required
@librarian_required
@validate_body(CreatePcCheatBody)
def pc_cheats_create(game_uuid: str, body: CreatePcCheatBody):
    """Record a cheat note. Librarian+, because it is shared household content."""
    from oneirodex.models import PcCheat

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')

    _, error = _pc_surface_or_error(game)
    if error:
        return error

    label = body.label

    method = (body.method or 'note').strip().lower()
    if method not in PC_CHEAT_METHODS:
        return api_error(
            f"method must be one of: {', '.join(sorted(PC_CHEAT_METHODS))}",
            code='bad_request',
        )

    row = PcCheat(
        game_uuid=game_uuid,
        method=method,
        label=label[:160],
        payload=(body.payload or '').strip() or None,
        notes=(body.notes or '').strip()[:1000] or None,
        single_player_only=bool(body.single_player_only),
        created_by_user_id=getattr(current_user, 'id', None),
    )
    db.session.add(row)
    db.session.commit()
    return api_ok({'cheat': row.to_dict()}, status=201)


@apis_bp.route('/games/<game_uuid>/pc_cheats/<int:cheat_id>', methods=['DELETE'])
@login_required
@librarian_required
def pc_cheats_delete(game_uuid: str, cheat_id: int):
    from oneirodex.models import PcCheat

    row = db.session.get(PcCheat, cheat_id)
    if row is None or row.game_uuid != game_uuid:
        return api_error('Cheat not found', code='not_found')
    db.session.delete(row)
    db.session.commit()
    return api_ok({'removed': cheat_id})
