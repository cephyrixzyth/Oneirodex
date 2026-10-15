"""Member preference JSON API used by the React shells."""

from __future__ import annotations

from flask import current_app, g, request
from flask_login import current_user, login_required
from werkzeug.datastructures import MultiDict

from oneirodex import db
from oneirodex.forms import UserPreferencesForm
from oneirodex.models import UserPreference
from oneirodex.routes_settings import _normalize_tile_percent, _stored_preference_formdata
from oneirodex.schemas.preferences import MemberPreferencesBody
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.api_tokens import user_has_scope
from oneirodex.utils.browser_player import play_engine_fields
from oneirodex.utils.icon_themes import list_icon_packs
from oneirodex.utils.preset_themes import theme_picker_groups
from oneirodex.utils.validation import validate_body

from . import apis_bp


@apis_bp.route('/account/preferences', methods=['GET', 'PUT'])
@login_required
@validate_body(MemberPreferencesBody)
def account_preferences(body: MemberPreferencesBody):
    """Read or update validated member preferences without a Jinja fragment."""
    if (
        request.method == 'PUT'
        and getattr(g, 'api_token', None) is not None
        and not user_has_scope('write:library')
    ):
        return api_error(
            'Missing scope: write:library', code='forbidden',
            detail={'required_scope': 'write:library'},
        )
    form = UserPreferencesForm(formdata=None)
    prefs = current_user.preferences
    if request.method == 'GET':
        values = _stored_preference_formdata(prefs)
        groups = theme_picker_groups(form.theme.choices)
        return api_ok({
            'preferences': values,
            'choices': {
                'items_per_page': [{'value': value, 'label': label} for value, label in form.items_per_page.choices],
                'default_sort': [{'value': value, 'label': label} for value, label in form.default_sort.choices],
                'default_sort_order': [{'value': value, 'label': label} for value, label in form.default_sort_order.choices],
                'themes': groups,
                'icon_packs': list_icon_packs(),
                'fonts': [{'value': value, 'label': label} for value, label in form.font.choices],
                'browser_player_engines': [{'value': value, 'label': label} for value, label in form.browser_player_engine.choices],
                'game_locales': [{'value': value, 'label': label} for value, label in form.preferred_game_locale.choices],
            },
            'member_engine_choice': play_engine_fields()['browser_player_member_choice'],
            'is_admin': current_user.role == 'admin',
        })

    payload = body.model_dump(exclude_unset=True)
    values = _stored_preference_formdata(prefs)
    for key in values:
        if key in payload:
            raw = payload[key]
            values[key] = 'true' if raw is True else 'false' if raw is False else str(raw)
    form = UserPreferencesForm(formdata=MultiDict(values), meta={'csrf': False})
    if not form.validate():
        return api_error('Preferences validation failed', code='bad_request', errors=form.errors)

    if prefs is None:
        prefs = UserPreference(user_id=current_user.id)
        current_user.preferences = prefs
    prefs.items_per_page = form.items_per_page.data
    prefs.default_sort = form.default_sort.data
    prefs.default_sort_order = form.default_sort_order.data
    prefs.theme = form.theme.data or 'default'
    prefs.icon_pack = form.icon_pack.data or 'outline'
    prefs.font = form.font.data or 'system-ui'
    prefs.tile_size = _normalize_tile_percent(form.tile_size.data)
    prefs.show_tile_titles = bool(form.show_tile_titles.data)
    prefs.browser_player_engine = form.browser_player_engine.data or None
    prefs.preferred_game_locale = form.preferred_game_locale.data or 'en-US'
    try:
        db.session.add(prefs)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to save member preferences')
        return api_error('Preferences could not be saved', code='internal')
    return api_ok({'preferences': _stored_preference_formdata(prefs)})
