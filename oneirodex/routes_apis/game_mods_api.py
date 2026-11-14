"""Per-game mod registry CRUD (ENABLE_MOD_TRACKING)."""

from __future__ import annotations

from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.api_tokens import require_api_token_scope
from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game
from oneirodex.schemas.game_mods import (
    ModPackBody,
    ModPackBulkBody,
    ModProfileBody,
    ModProfileImportBody,
    ModRowBody,
)
from oneirodex.utils.game_mod_profiles import (
    activate_profile,
    create_profile,
    delete_profile,
    export_profile,
    import_profile,
    list_profiles,
)
from oneirodex.utils.game_mods import (
    create_mod,
    delete_mod,
    list_mods_summary,
    load_mods,
    loader_conflicts,
    mods_enabled,
    save_mods,
    set_default_loader,
    update_mod,
)
from oneirodex.utils.validation import validate_body
from oneirodex.utils.library_acl import apply_game_access_filters, user_can_access_game
from oneirodex.utils.mod_catalog import catalog_search, source_ids
from oneirodex.utils.rbac import is_librarian, normalize_role

from . import apis_bp


def _mods_disabled():
    return api_error('ENABLE_MOD_TRACKING is off', code='forbidden', enabled=False)


def _forbidden(message: str = 'Forbidden'):
    return api_error(message, code='forbidden')


def _require_librarian():
    if not current_user.is_authenticated or not is_librarian(current_user):
        return _forbidden('Librarian or admin required')
    if normalize_role(current_user.role) == 'child':
        return _forbidden('Child accounts are read-only for mods')
    return None


def _game_or_404(game_uuid: str) -> Game | None:
    return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()


def _require_game_read(game: Game | None):
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return _forbidden()
    return None


@apis_bp.route('/mods/summary', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def mods_summary():
    if not mods_enabled():
        return jsonify({'enabled': False, 'games': []})
    query = apply_game_access_filters(Game.query, current_user)
    games = query.all()
    rows = list_mods_summary([game.uuid for game in games])
    by_uuid = {game.uuid: game.name for game in games}
    payload = []
    for row in rows:
        payload.append({
            **row,
            'game_name': by_uuid.get(row['game_uuid']),
        })
    return jsonify({'enabled': True, 'games': payload})


@apis_bp.route('/games/<game_uuid>/mods', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def get_game_mods(game_uuid: str):
    if not mods_enabled():
        return jsonify({'enabled': False, 'mods': []})
    game = _game_or_404(game_uuid)
    denied = _require_game_read(game)
    if denied:
        return denied
    pack = load_mods(game_uuid)
    return jsonify({'enabled': True, **pack, 'loader_conflicts': loader_conflicts(pack)})


@apis_bp.route('/games/<game_uuid>/mods/catalog', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def get_game_mods_catalog(game_uuid: str):
    """Browse a community registry for this game (INSP-22, librarian).

    ``?source=thunderstore|modrinth&q=&limit=``. Read-only: the answer is
    names, versions, loaders and registry pages -- never an archive. ``status``
    says whether the registry answered (``ok``) or had no data
    (``unavailable``); ``hits`` is ``null`` in the latter case, never ``[]``.
    """
    if not mods_enabled():
        return _mods_disabled()
    denied = _require_librarian()
    if denied:
        return denied
    game = _game_or_404(game_uuid)
    read_denied = _require_game_read(game)
    if read_denied:
        return read_denied
    source = (request.args.get('source') or '').strip().lower()
    if source not in source_ids():
        return api_error('Unknown catalogue source', code='bad_request', sources=source_ids())
    result = catalog_search(
        source,
        game.name or '',
        query=(request.args.get('q') or '').strip(),
        limit=request.args.get('limit', type=int),
        tracked=load_mods(game_uuid)['mods'],
    )
    return api_ok({'game_uuid': game_uuid, **result})


@apis_bp.route('/games/<game_uuid>/mods', methods=['POST'])
@login_required
@validate_body(ModRowBody)
def post_game_mod(game_uuid: str, body: ModRowBody):
    if not mods_enabled():
        return _mods_disabled()
    denied = _require_librarian()
    if denied:
        return denied
    game = _game_or_404(game_uuid)
    read_denied = _require_game_read(game)
    if read_denied:
        return read_denied
    data = body.payload()
    try:
        created = create_mod(game_uuid, data)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'mod': created}, status=201)


@apis_bp.route('/games/<game_uuid>/mods/<mod_id>', methods=['PUT', 'PATCH'])
@login_required
@validate_body(ModRowBody)
def patch_game_mod(game_uuid: str, mod_id: str, body: ModRowBody):
    if not mods_enabled():
        return _mods_disabled()
    denied = _require_librarian()
    if denied:
        return denied
    game = _game_or_404(game_uuid)
    read_denied = _require_game_read(game)
    if read_denied:
        return read_denied
    data = body.payload()
    try:
        updated = update_mod(game_uuid, mod_id, data)
    except LookupError:
        return api_error('Mod not found', code='not_found')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'mod': updated})


@apis_bp.route('/games/<game_uuid>/mods/<mod_id>', methods=['DELETE'])
@login_required
def delete_game_mod(game_uuid: str, mod_id: str):
    if not mods_enabled():
        return _mods_disabled()
    denied = _require_librarian()
    if denied:
        return denied
    game = _game_or_404(game_uuid)
    read_denied = _require_game_read(game)
    if read_denied:
        return read_denied
    if not delete_mod(game_uuid, mod_id):
        return api_error('Mod not found', code='not_found')
    return api_ok({'id': mod_id})


@apis_bp.route('/games/<game_uuid>/mods', methods=['PUT'])
@login_required
@validate_body(ModPackBulkBody)
def put_game_mods_bulk(game_uuid: str, body: ModPackBulkBody):
    """Replace the full mod list (librarian/admin)."""
    if not mods_enabled():
        return _mods_disabled()
    denied = _require_librarian()
    if denied:
        return denied
    game = _game_or_404(game_uuid)
    read_denied = _require_game_read(game)
    if read_denied:
        return read_denied
    return api_ok({**save_mods(game_uuid, body.mods, default_loader=body.default_loader)})


def _librarian_gate(game_uuid: str):
    """Shared preamble for the librarian write routes: None when allowed."""
    if not mods_enabled():
        return _mods_disabled()
    denied = _require_librarian()
    if denied:
        return denied
    game = _game_or_404(game_uuid)
    return _require_game_read(game)


@apis_bp.route('/games/<game_uuid>/mods/profiles', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def get_game_mod_profiles(game_uuid: str):
    """Named mod sets (INSP-37) and which one is active."""
    if not mods_enabled():
        return _mods_disabled()
    game = _game_or_404(game_uuid)
    denied = _require_game_read(game)
    if denied:
        return denied
    return api_ok({'game_uuid': game_uuid, **list_profiles(game_uuid)})


@apis_bp.route('/games/<game_uuid>/mods/profiles', methods=['POST'])
@login_required
@validate_body(ModProfileBody)
def post_game_mod_profile(game_uuid: str, body: ModProfileBody):
    denied = _librarian_gate(game_uuid)
    if denied:
        return denied
    try:
        profile = create_profile(game_uuid, name=body.name, mod_ids=body.mod_ids)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'profile': profile, **list_profiles(game_uuid)}, status=201)


@apis_bp.route('/games/<game_uuid>/mods/profiles/<profile_id>', methods=['DELETE'])
@login_required
def delete_game_mod_profile(game_uuid: str, profile_id: str):
    denied = _librarian_gate(game_uuid)
    if denied:
        return denied
    if not delete_profile(game_uuid, profile_id):
        return api_error('Profile not found', code='not_found')
    return api_ok({'id': profile_id, **list_profiles(game_uuid)})


@apis_bp.route('/games/<game_uuid>/mods/profiles/<profile_id>/activate', methods=['POST'])
@login_required
def activate_game_mod_profile(game_uuid: str, profile_id: str):
    """One-click enable set: the profile's rows on, every other row off."""
    denied = _librarian_gate(game_uuid)
    if denied:
        return denied
    try:
        pack = activate_profile(game_uuid, profile_id)
    except LookupError:
        return api_error('Profile not found', code='not_found')
    return api_ok({**pack})


@apis_bp.route('/games/<game_uuid>/mods/profiles/<profile_id>/export', methods=['GET'])
@login_required
@require_api_token_scope('read:library')
def export_game_mod_profile(game_uuid: str, profile_id: str):
    """The shareable ``od-mod:`` code for a profile (any member who can read the game)."""
    if not mods_enabled():
        return _mods_disabled()
    game = _game_or_404(game_uuid)
    denied = _require_game_read(game)
    if denied:
        return denied
    try:
        code = export_profile(game_uuid, profile_id)
    except LookupError:
        return api_error('Profile not found', code='not_found')
    return api_ok({'profile_id': profile_id, 'code': code})


@apis_bp.route('/games/<game_uuid>/mods/profiles/import', methods=['POST'])
@login_required
@validate_body(ModProfileImportBody)
def import_game_mod_profile(game_uuid: str, body: ModProfileImportBody):
    """Create a profile from a code, matched against this pack; unknown mods
    come back as ``missing`` and are never created."""
    denied = _librarian_gate(game_uuid)
    if denied:
        return denied
    try:
        result = import_profile(game_uuid, body.code, name=body.name)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({**result, **list_profiles(game_uuid)}, status=201)


@apis_bp.route('/games/<game_uuid>/mods/pack', methods=['PATCH'])
@login_required
@validate_body(ModPackBody)
def patch_game_mods_pack(game_uuid: str, body: ModPackBody):
    """Pack-level fields (INSP-36): today only ``default_loader``."""
    if not mods_enabled():
        return _mods_disabled()
    denied = _require_librarian()
    if denied:
        return denied
    game = _game_or_404(game_uuid)
    read_denied = _require_game_read(game)
    if read_denied:
        return read_denied
    return api_ok({**set_default_loader(game_uuid, body.default_loader)})
