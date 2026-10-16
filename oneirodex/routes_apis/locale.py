"""Legacy Flask compatibility routes for the UI locale preference.

The primary ASGI dispatcher routes this API to ``runtime_native.locale``.
Keep the Flask handler during the reversible runtime migration for WSGI and
existing route-level compatibility callers.
"""

from flask import jsonify, make_response, request, session
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import UserPreference
from oneirodex.utils.api_response import api_error
from oneirodex.utils.locale_core import SUPPORTED_LOCALES, normalize_locale

from . import apis_bp


@apis_bp.route('/locale', methods=['GET'])
@login_required
def get_locale():
    prefs = getattr(current_user, 'preferences', None)
    current = normalize_locale(getattr(prefs, 'locale', None) if prefs else None)
    return jsonify({'locale': current, 'supported': list(SUPPORTED_LOCALES)})


@apis_bp.route('/locale', methods=['POST'])
@login_required
def set_locale():
    data = request.get_json(silent=True) or {}
    locale = normalize_locale(data.get('locale') or request.form.get('locale'))
    if locale not in SUPPORTED_LOCALES:
        return api_error('Unsupported locale', code='bad_request')

    prefs = db.session.execute(
        select(UserPreference).filter_by(user_id=current_user.id),
    ).scalars().first()
    if not prefs:
        prefs = UserPreference(user_id=current_user.id, locale=locale)
        db.session.add(prefs)
    else:
        prefs.locale = locale
    db.session.commit()
    session['locale'] = locale

    response = make_response(jsonify({'locale': locale, 'supported': list(SUPPORTED_LOCALES)}))
    response.set_cookie('gt_locale', locale, max_age=365 * 24 * 3600, samesite='Lax')
    return response
