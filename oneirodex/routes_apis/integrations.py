"""Admin Integrations inventory API."""

from flask import jsonify, current_app, request
from datetime import datetime, timezone
import os

from oneirodex import db, cache
from oneirodex.models import GlobalSettings
from oneirodex.utils.api_response import api_ok, api_error
from oneirodex.utils.global_settings import global_settings_row, global_settings_row_or_create
from oneirodex.utils.oidc import is_secure_oidc_issuer, oidc_readiness_report
from oneirodex.utils.event_logging import log_system_event
from flask_login import login_required

from oneirodex.utils.auth import admin_required
from oneirodex.utils.integrations_inventory import build_integrations_inventory

from . import apis_bp


@apis_bp.route('/admin/integrations/inventory', methods=['GET'])
@login_required
@admin_required
def integrations_inventory():
    """List all admin-facing integrations with status + deep links."""
    items = build_integrations_inventory()
    return jsonify({
        'integrations': items,
        'count': len(items),
        'hub_href': '/admin/integrations',
    })


OIDC_ADMIN_CONFIG = '/admin/integrations/oidc'
OIDC_ADMIN_FIELDS = {
    'oidc_enabled', 'oidc_display_name', 'oidc_issuer_url', 'oidc_client_id',
    'oidc_client_secret', 'oidc_redirect_uri', 'oidc_scopes',
    'oidc_role_claim', 'oidc_role_map',
}
OIDC_TEXT_LIMITS = {
    'oidc_display_name': 120, 'oidc_issuer_url': 512, 'oidc_client_id': 255,
    'oidc_client_secret': 512, 'oidc_redirect_uri': 512,
    'oidc_scopes': 255, 'oidc_role_claim': 64,
}
OIDC_ROLES = {'admin', 'librarian', 'user', 'child'}


def oidc_admin_settings(row):
    return {
        'oidc_enabled': bool(row and row.oidc_enabled),
        'oidc_display_name': (getattr(row, 'oidc_display_name', None) if row else None) or 'Sign in with SSO',
        'oidc_issuer_url': (getattr(row, 'oidc_issuer_url', None) if row else None) or '',
        'oidc_client_id': (getattr(row, 'oidc_client_id', None) if row else None) or '',
        'oidc_client_secret_configured': bool(
            (getattr(row, 'oidc_client_secret', None) if row else None)
            or os.getenv('OIDC_CLIENT_SECRET')
        ),
        'oidc_redirect_uri': (getattr(row, 'oidc_redirect_uri', None) if row else None) or '',
        'oidc_scopes': (getattr(row, 'oidc_scopes', None) if row else None) or 'openid email profile',
        'oidc_role_claim': (getattr(row, 'oidc_role_claim', None) if row else None) or 'groups',
        'oidc_role_map': (getattr(row, 'oidc_role_map', None) if row else None) or {
            'admin': 'admin', 'oneirodex-admin': 'admin', 'librarian': 'librarian',
            'oneirodex-librarian': 'librarian', 'child': 'child', 'oneirodex-child': 'child',
        },
    }


@apis_bp.route(OIDC_ADMIN_CONFIG, methods=['GET'])
@login_required
@admin_required
def oidc_admin_config_get():
    try:
        row = global_settings_row()
        response = current_app.make_response(api_ok({
            'settings': oidc_admin_settings(row),
            'readiness': oidc_readiness_report(row),
        }))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        return api_error('Could not load OIDC settings.', code='internal')


@apis_bp.route(OIDC_ADMIN_CONFIG, methods=['PUT'])
@login_required
@admin_required
def oidc_admin_config_put():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != OIDC_ADMIN_FIELDS:
        return api_error('Provide all OIDC settings fields.', code='bad_request')
    if type(payload['oidc_enabled']) is not bool:
        return api_error('OIDC enabled must be a boolean.', code='bad_request')
    for field, limit in OIDC_TEXT_LIMITS.items():
        value = payload[field]
        if not isinstance(value, str) or len(value) > limit or any(ord(ch) < 32 and ch not in '\t' for ch in value):
            return api_error('OIDC text fields are invalid or too long.', code='bad_request')
    role_map = payload['oidc_role_map']
    if (not isinstance(role_map, dict) or len(role_map) > 128
            or any(not isinstance(key, str) or not key.strip() or len(key) > 120 for key in role_map)
            or any(not isinstance(value, str) or value.strip().lower() not in OIDC_ROLES for value in role_map.values())):
        return api_error('OIDC role map must map names to supported roles.', code='bad_request')
    issuer = payload['oidc_issuer_url'].strip() or None
    if issuer and not is_secure_oidc_issuer(issuer):
        return api_error('OIDC issuer URL must use HTTPS.', code='bad_request')
    if payload['oidc_enabled'] and not all((issuer, payload['oidc_client_id'].strip(), payload['oidc_redirect_uri'].strip())):
        return api_error('When enabling SSO, provide issuer URL, client ID and redirect URI.', code='bad_request')
    try:
        row = global_settings_row_or_create()
        row.oidc_enabled = payload['oidc_enabled']
        row.oidc_display_name = payload['oidc_display_name'].strip() or 'Sign in with SSO'
        row.oidc_issuer_url = issuer
        row.oidc_client_id = payload['oidc_client_id'].strip() or None
        # Blank input retains the current database secret. Environment secrets
        # remain authoritative when the database value is empty.
        secret = payload['oidc_client_secret'].strip()
        if secret:
            row.oidc_client_secret = secret
        row.oidc_redirect_uri = payload['oidc_redirect_uri'].strip() or None
        row.oidc_scopes = payload['oidc_scopes'].strip() or 'openid email profile'
        row.oidc_role_claim = payload['oidc_role_claim'].strip() or 'groups'
        row.oidc_role_map = role_map
        row.last_updated = datetime.now(timezone.utc)
        db.session.commit()
        cache.delete('global_settings')
        log_system_event('OIDC settings updated via native integrations', event_type='audit', event_level='information')
        response = current_app.make_response(api_ok({
            'settings': oidc_admin_settings(row),
            'readiness': oidc_readiness_report(row),
        }))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        db.session.rollback()
        return api_error('Could not save OIDC settings.', code='internal')


@apis_bp.route('/admin/integrations/community', methods=['GET', 'PUT'])
@login_required
@admin_required
def community_chat_settings_api():
    """Read or update the optional household community deep-link."""
    from oneirodex.utils.security import validate_community_chat_url

    if request.method == 'GET':
        row = global_settings_row()
        response = current_app.make_response(api_ok({
            'community_chat_url': (getattr(row, 'community_chat_url', None) or '') if row else '',
            'community_chat_label': (getattr(row, 'community_chat_label', None) or 'Open community') if row else 'Open community',
        }))
        response.headers['Cache-Control'] = 'no-store'
        return response

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'community_chat_url', 'community_chat_label'}:
        return api_error('Provide the community URL and link label.', code='bad_request')
    url = data.get('community_chat_url')
    label = data.get('community_chat_label')
    if not isinstance(url, str) or len(url) > 2048 or not isinstance(label, str) or len(label) > 120 or any(ord(ch) < 32 for ch in label):
        return api_error('Community settings contain invalid text.', code='bad_request')
    ok, normalized = validate_community_chat_url(url.strip())
    if not ok:
        return api_error(normalized, code='bad_request')
    try:
        row = global_settings_row_or_create()
        row.community_chat_url = normalized or None
        row.community_chat_label = label.strip() or 'Open community'
        db.session.commit()
        cache.delete('global_settings')
        log_system_event('Community chat link updated via integrations')
        response = current_app.make_response(api_ok({
            'community_chat_url': row.community_chat_url or '',
            'community_chat_label': row.community_chat_label or 'Open community',
        }))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        db.session.rollback()
        current_app.logger.warning('Community chat settings API save failed')
        return api_error('Could not save community settings.', code='internal')
