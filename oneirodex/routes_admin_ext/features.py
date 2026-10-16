"""Admin: product feature toggles (on by default; auth/OIDC stays separate)."""

from __future__ import annotations

import os

from flask import current_app, flash, redirect, request, url_for
from flask_login import login_required

from oneirodex import db
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.forms import CsrfProtectForm
from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)
from oneirodex.utils.malware_scan import module_status as malware_module_status
from oneirodex.utils.challenge_solver import challenge_solver_status, get_challenge_config, save_challenge_config
from oneirodex.utils.feature_catalog import FEATURE_ENV_TOGGLES
from oneirodex.schemas.admin_features import FeaturePreferencesBody, ChallengeSolverBody
from oneirodex.utils.validation import validate_body

from . import admin2_bp

# Env flags that must never be flipped by Features/setup bulk save (opt-in / safety only).
NEVER_BULK_ENABLE_ENV = frozenset({
    'OIDC_ENABLED',
    'ENABLE_AI_AUTO_APPLY',
    'ALLOW_HARDLINK_APPLY',
    'ENABLE_CHALLENGE_SOLVER',
    'ENABLE_AMBIENT_LIGHTING',
    'ENABLE_REMOTE_PLAY',
})

def _env_bool(key: str, default: bool = True) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == '':
        return bool(current_app.config.get(key, default))
    return raw.lower() in ('1', 'true', 'yes', 'on')


FEATURE_DB_FIELDS = (
    'enable_arr_module', 'enable_ai_assist', 'enable_malware_scan',
    'enable_game_updates', 'enable_game_extras', 'attract_mode_enabled',
    'allow_children_in_household_lobby',
)


def _feature_preferences(settings):
    return {key: bool(getattr(settings, key, key != 'allow_children_in_household_lobby'))
            for key in FEATURE_DB_FIELDS}


def _challenge_public(config):
    # No token, token URL, exception text, or other arbitrary provider output.
    return {key: config.get(key) for key in (
        'enabled', 'env_enabled', 'db_enabled', 'url', 'provider', 'max_tier')}


def _scanner_public():
    status = malware_module_status()
    clamav = status.get('clamav') or {}
    settings = status.get('settings') or {}
    return {
        'enabled': bool(status.get('enabled')),
        'block_on_hit': bool(status.get('block_on_hit')),
        'heuristics': {
            'enabled': bool((status.get('heuristics') or {}).get('enabled')),
            'block_on_match': bool((status.get('heuristics') or {}).get('block_on_match')),
        },
        'clamav': {'reachable': bool(clamav.get('reachable')),
                   'version': str(clamav.get('version') or '')[:200] if clamav.get('reachable') else '',
                   'error': 'Scanner unavailable. Check its connection settings.' if clamav.get('error') else None},
        'settings': {'host': settings.get('host'), 'port': settings.get('port'),
                     'socket_configured': bool(settings.get('socket'))},
    }


def _invalid_feature_preferences(_exc):
    return api_error(
        'Provide all seven feature preferences as booleans. Process flags cannot be changed here.',
        code='bad_request',
    )


def _invalid_challenge_settings(_exc):
    return api_error(
        'Provide a boolean enable preference, URL, supported provider, and positive integer tier.',
        code='bad_request',
    )


@admin2_bp.route('/api/admin/features/settings', methods=['GET', 'PUT'])
@login_required
@admin_required
@validate_body(FeaturePreferencesBody, methods={'PUT'}, on_error=_invalid_feature_preferences)
def features_settings_api(body: FeaturePreferencesBody | None = None):
    if body is not None:
        data = body.model_dump()
        try:
            settings = global_settings_row_or_create()
            for key, value in data.items():
                setattr(settings, key, value)
            db.session.commit()
        except Exception:
            db.session.rollback()
            return api_error('Could not save feature preferences', code='internal')
        return api_ok({'preferences': _feature_preferences(settings)})
    try:
        settings = global_settings_row()
        process = [{'key': key, 'label': label, 'help': help_text,
                    'on': _env_bool(key, key not in ('ENABLE_REMOTE_PLAY', 'ENABLE_AMBIENT_LIGHTING')),
                    'opt_in': key in NEVER_BULK_ENABLE_ENV}
                   for _, key, label, help_text, _ in FEATURE_ENV_TOGGLES]
        process.extend([
            {'key': 'OIDC_ENABLED', 'label': 'OIDC authentication', 'on': _env_bool('OIDC_ENABLED', False) or bool(getattr(settings, 'oidc_enabled', False)), 'opt_in': True},
            {'key': 'ENABLE_AI_AUTO_APPLY', 'label': 'AI automatic apply', 'on': _env_bool('ENABLE_AI_AUTO_APPLY', False), 'opt_in': True},
            {'key': 'ALLOW_HARDLINK_APPLY', 'label': 'Hardlink apply', 'on': _env_bool('ALLOW_HARDLINK_APPLY', False), 'opt_in': True},
            {'key': 'ENABLE_CHALLENGE_SOLVER', 'label': 'Challenge solver', 'on': _env_bool('ENABLE_CHALLENGE_SOLVER', False), 'opt_in': True},
        ])
        response = current_app.make_response(api_ok({'preferences': _feature_preferences(settings), 'process': process,
                                                     'challenge': _challenge_public(get_challenge_config()), 'scanner': _scanner_public()}))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        return api_error('Could not load feature settings', code='internal')


@admin2_bp.route('/api/admin/features/challenge', methods=['PUT'])
@login_required
@admin_required
@validate_body(ChallengeSolverBody, on_error=_invalid_challenge_settings)
def features_challenge_save_api(body: ChallengeSolverBody):
    data = body.model_dump()
    try:
        config = save_challenge_config(data)
        return api_ok({'challenge': _challenge_public(config)})
    except ValueError:
        return api_error('Check the solver URL, provider, and tier.', code='bad_request')
    except Exception:
        db.session.rollback()
        return api_error('Could not save solver settings', code='internal')


@admin2_bp.route('/api/admin/features/challenge/test', methods=['POST'])
@login_required
@admin_required
def features_challenge_test_api():
    try:
        status = challenge_solver_status(probe=True)
        return api_ok({'result': {'enabled': bool(status.get('enabled')), 'reachable': bool(status.get('reachable')),
                                 'probe_ok': bool(status.get('probe_ok')),
                                 'error': 'Solver test failed. Check the saved connection settings.' if status.get('last_error') else None}})
    except Exception:
        return api_error('Could not test the solver connection', code='bad_gateway')


@admin2_bp.route('/admin/features', methods=['GET', 'POST'])
@login_required
@admin_required
def features_settings_page():
    """Toggle product modules. OIDC/auth is under Integrations — stays off by default."""
    if request.method == 'GET':
        return render_admin_spa(title='Features · Oneirodex Admin')

    form = CsrfProtectForm()
    settings = global_settings_row()
    if settings is None:
        # Kept conditional so a plain GET does not commit on every page view;
        # the row only needs persisting the once, when it did not exist.
        settings = global_settings_row_or_create()
        db.session.commit()

    if request.method == 'POST' and form.validate_on_submit():
        settings.enable_arr_module = request.form.get('db_enable_arr_module') == 'on'
        settings.enable_ai_assist = request.form.get('db_enable_ai_assist') == 'on'
        settings.enable_malware_scan = request.form.get('db_enable_malware_scan') == 'on'
        settings.enable_game_updates = request.form.get('db_enable_game_updates') == 'on'
        settings.enable_game_extras = request.form.get('db_enable_game_extras') == 'on'
        settings.attract_mode_enabled = request.form.get('db_attract_mode_enabled') == 'on'
        # Parental control, so it is written like the rest but read fail-closed
        # in livekit_rtc — an unchecked box means children stay out.
        settings.allow_children_in_household_lobby = (
            request.form.get('db_allow_children_in_household_lobby') == 'on'
        )
        # Never enable OIDC from this page — auth stays opt-in on Integrations.
        db.session.commit()
        flash(
            'Feature preferences saved. Env flags (docker/.env) still override process defaults until restart.',
            'success',
        )
        return redirect(url_for('admin2.features_settings_page'))

    if form.errors:
        flash('Please correct the errors below.', 'error')
    return redirect(url_for('admin2.features_settings_page'))
