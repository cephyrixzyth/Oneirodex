"""Personal access token management and OpenAPI document endpoints."""

from oneirodex.utils.api_response import api_error, api_ok
from flask import current_app, jsonify, send_file
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import ApiToken
from oneirodex.schemas.tokens import CreateApiTokenBody
from oneirodex.utils.api_tokens import (
    TOKEN_SCOPE_PRESETS,
    VALID_SCOPES,
    forbidden_scopes_for_role,
    generate_api_token,
    is_raw_api_token,
    revoke_api_token,
)
from oneirodex.utils.validation import validate_body

from . import apis_bp

import os


@apis_bp.route('/tokens', methods=['GET'])
@login_required
def list_api_tokens():
    rows = db.session.execute(
        select(ApiToken)
        .filter_by(user_id=current_user.id)
        .order_by(ApiToken.created_at.desc())
    ).scalars().all()
    denied = forbidden_scopes_for_role(getattr(current_user, 'role', None))
    return jsonify({
        'tokens': [row.to_public_dict() for row in rows],
        'valid_scopes': sorted(s for s in VALID_SCOPES if s not in denied),
        'scope_presets': {
            key: preset
            for key, preset in TOKEN_SCOPE_PRESETS.items()
            if not denied.intersection(preset['scopes'])
        },
    })


def _beyond_calling_token(scopes) -> list[str]:
    """Requested scopes the calling API token does not itself hold.

    A caller on a token may only mint tokens narrower than (or equal to) its
    own: an admin's companion token (read:library, write:download) used to be
    able to mint an admin-scope token, undoing every scope check. A browser
    session has no token and is limited by the account's role as before.
    """
    from flask import g

    token = g.get('api_token')
    if token is None:
        return []
    return [s for s in (scopes or ['read:library']) if not token.has_scope(str(s).strip())]


@apis_bp.route('/tokens', methods=['POST'])
@login_required
@validate_body(CreateApiTokenBody)
def create_api_token(body: CreateApiTokenBody):
    name = body.name
    preset = (body.preset or '').strip().lower()
    scopes = body.scopes
    if preset:
        preset_def = TOKEN_SCOPE_PRESETS.get(preset)
        if preset_def is None:
            return api_error(f'Unknown preset: {preset}', code='bad_request')
        scopes = preset_def['scopes']
    if scopes is not None and not isinstance(scopes, list):
        return api_error('scopes must be a list', code='bad_request')
    if scopes is not None:
        if not all(isinstance(s, str) for s in scopes):
            return api_error('scopes must be strings', code='bad_request')
        # One cleaned list for every check below and for the stored token:
        # ' admin' used to pass the role check here and be stored as 'admin'.
        scopes = [s.strip() for s in scopes]
    if current_user.role != 'admin' and scopes and 'admin' in scopes:
        return api_error('admin scope requires admin role', code='forbidden')
    beyond = _beyond_calling_token(scopes)
    if beyond:
        return api_error(
            'A token can only create tokens with scopes it already has',
            code='forbidden',
            detail={'denied_scopes': beyond},
        )
    denied = forbidden_scopes_for_role(getattr(current_user, 'role', None))
    blocked = [str(s).strip() for s in (scopes or []) if str(s).strip() in denied]
    if blocked:
        return api_error(
            'Those scopes are not allowed for this account',
            code='forbidden',
            detail={'denied_scopes': blocked},
        )

    row, raw = generate_api_token(current_user, name, scopes)
    # Contract: `secret` is the raw token only — no labels, expiry, or HTML.
    if not is_raw_api_token(raw):
        current_app.logger.error('api_token_create_impure prefix=%s', row.token_prefix)
        return api_error('Token generation failed purity check', code='internal')
    return jsonify({
        'token': row.to_public_dict(),
        'secret': raw,
        'warning': 'Store this secret now; it will not be shown again.',
    }), 201


@apis_bp.route('/tokens/<int:token_id>', methods=['DELETE'])
@login_required
def delete_api_token(token_id: int):
    ok = revoke_api_token(token_id, user_id=current_user.id)
    if not ok:
        return api_error('Token not found', code='not_found')
    return api_ok()


@apis_bp.route('/openapi.json', methods=['GET'])
def openapi_json():
    """Serve the OpenAPI 3 document (public schema; operations still auth-gated)."""
    path = _openapi_path()
    if not os.path.isfile(path):
        return api_error('OpenAPI document not found', code='not_found')
    return send_file(path, mimetype='application/json')


@apis_bp.route('/openapi.yaml', methods=['GET'])
def openapi_yaml():
    path = _openapi_path().replace('.json', '.yaml')
    if not os.path.isfile(path):
        return api_error('OpenAPI document not found', code='not_found')
    return send_file(path, mimetype='application/yaml')


def _openapi_path() -> str:
    root = os.path.abspath(os.path.join(current_app.root_path, '..'))
    return os.path.join(root, 'docs', 'openapi', 'openapi.json')
