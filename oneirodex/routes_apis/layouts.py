"""Detail layout API."""

from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user, login_required

from oneirodex.schemas.layouts import CreateLayoutPresetBody
from oneirodex.utils.api_response import api_error
from oneirodex.utils.api_tokens import require_api_token_scope
from oneirodex.utils.auth import admin_required
from oneirodex.utils.detail_layouts import (
    clear_user_detail_layout,
    delete_layout_preset,
    get_detail_layout,
    get_user_detail_layout,
    list_layout_presets,
    save_detail_layout,
    save_layout_preset,
    save_user_detail_layout,
    user_has_detail_override,
)
from oneirodex.utils.validation import validate_body

from . import apis_bp


@apis_bp.route('/layouts/detail', methods=['GET'])
@login_required
def layouts_detail_get():
    return jsonify(get_detail_layout())


@apis_bp.route('/layouts/detail', methods=['PUT'])
@login_required
@admin_required
def layouts_detail_put():
    data = request.get_json(silent=True) or {}
    try:
        saved = save_detail_layout(data)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return jsonify(saved)


# --- Per-member layout + named presets ----------------------------------
#
# The layout above is the *install* default and stays admin-only. Everything
# below belongs to whoever is signed in: one member arranging their own details
# page must not change it for the household, which is what the single shared
# layout meant before.


@apis_bp.route('/layouts/detail/mine', methods=['GET'])
@login_required
def layouts_detail_mine_get():
    """This member's effective layout — theirs if set, the install's if not."""
    return jsonify({
        'layout': get_user_detail_layout(current_user.id),
        # Whether it is actually *theirs* changes what the editor should offer
        # ("Reset to default" only means something if an override exists), and
        # the layout alone cannot answer that: a member's arrangement may be
        # identical to the install's by coincidence.
        'is_override': user_has_detail_override(current_user.id),
    })


@apis_bp.route('/layouts/detail/mine', methods=['PUT'])
@login_required
@require_api_token_scope('write:library')
def layouts_detail_mine_put():
    data = request.get_json(silent=True) or {}
    try:
        saved = save_user_detail_layout(current_user.id, data)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return jsonify({'layout': saved, 'is_override': True})


@apis_bp.route('/layouts/detail/mine', methods=['DELETE'])
@login_required
@require_api_token_scope('write:library')
def layouts_detail_mine_delete():
    """Stop overriding and follow the install default again."""
    return jsonify({
        'layout': clear_user_detail_layout(current_user.id),
        'is_override': False,
    })


@apis_bp.route('/layouts/detail/presets', methods=['GET'])
@login_required
def layouts_detail_presets_get():
    return jsonify({'presets': list_layout_presets(current_user.id)})


@apis_bp.route('/layouts/detail/presets', methods=['POST'])
@login_required
@require_api_token_scope('write:library')
@validate_body(CreateLayoutPresetBody)
def layouts_detail_presets_post(body: CreateLayoutPresetBody):
    try:
        saved = save_layout_preset(
            current_user.id,
            body.name,
            body.layout,
        )
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return jsonify(saved), 201


@apis_bp.route('/layouts/detail/presets/<int:preset_id>', methods=['DELETE'])
@login_required
@require_api_token_scope('write:library')
def layouts_detail_presets_delete(preset_id: int):
    # 404 rather than 403 for someone else's preset: confirming a preset exists
    # but belongs to another member is a fact this endpoint has no reason to
    # disclose.
    if not delete_layout_preset(current_user.id, preset_id):
        return api_error('Preset not found', code='not_found')
    return jsonify({'deleted': preset_id})
