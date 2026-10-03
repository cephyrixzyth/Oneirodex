from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user, login_user
from oneirodex.forms import ChangePasswordForm, EditProfileForm, UserPreferencesForm
from oneirodex.models import User, InviteToken, UserPreference
from sqlalchemy import select, func
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.avatar import DEFAULT_AVATAR, save_avatar, thumbnail_for
from oneirodex.utils.processors import get_global_settings
from oneirodex import cache
from oneirodex import db

settings_bp = Blueprint('settings', __name__)

_TILE_LEGACY = {'S': '25', 'M': '50', 'L': '75', 'XL': '100'}


def _normalize_tile_percent(raw) -> str:
    text = str(raw or '').strip().upper()
    if text in _TILE_LEGACY:
        return _TILE_LEGACY[text]
    try:
        value = int(text)
    except (TypeError, ValueError):
        return '50'
    return str(max(0, min(100, value)))


@settings_bp.context_processor
@cache.cached(timeout=500, key_prefix='global_settings')
def inject_settings():
    """Context processor to inject global settings into templates"""
    return get_global_settings()

@settings_bp.route('/settings_profile_edit', methods=['GET', 'POST'])
@login_required
def settings_profile_edit():
    print("Route: Settings profile edit")
    form = EditProfileForm()

    if form.validate_on_submit():
        file = form.avatar.data
        if file:
            # One implementation of "what is a valid avatar and what happens to
            # the old one", shared with POST /api/account/avatar.
            _path, error = save_avatar(file, current_user, current_app)
            if error:
                flash(error, 'error')
                return redirect(url_for('settings.settings_profile_edit'))
        elif not current_user.avatarpath:
            current_user.avatarpath = DEFAULT_AVATAR

        try:
            db.session.commit()
            flash('Profile updated successfully!', 'success')
        except Exception as e:
            db.session.rollback()
            print(f"Error updating profile: {e}")
            flash('Failed to update profile. Please try again.', 'error')

        return redirect(url_for('settings.settings_profile_edit'))

    print("Form validation failed" if request.method == 'POST' else "Settings profile Form rendering")

    for field, errors in form.errors.items():
        for error in errors:
            print(f"Error in field '{getattr(form, field).label.text}': {error}")
            flash(f"Error in field '{getattr(form, field).label.text}': {error}", 'error')

    # The thumbnail name is a rule about how avatars are stored, so the route
    # answers it rather than the template deriving it with a string replace —
    # which produced a request for a `_thumbnail` file the shipped avatars never
    # had.
    return render_template(
        'settings/settings_profile_edit.html',
        form=form,
        avatarpath=current_user.avatarpath,
        thumbnailpath=thumbnail_for(current_user.avatarpath),
    )

@settings_bp.route('/settings_profile_view', methods=['GET'])
@login_required
def settings_profile_view():
    print("Route: Settings profile view")
    unused_invites = db.session.execute(
        select(func.count(InviteToken.id)).filter_by(
            creator_user_id=current_user.user_id, 
            used=False
        )
    ).scalar()
    remaining_invites = max(0, current_user.invite_quota - unused_invites)
    
    return render_template('settings/settings_profile_view.html', 
                         remaining_invites=remaining_invites,
                         total_invites=current_user.invite_quota)

@settings_bp.route('/settings_password', methods=['GET', 'POST'])
@login_required
def account_pw():
    form = ChangePasswordForm()
    user = db.session.get(User, current_user.id)

    if form.validate_on_submit():
        if not user.check_password(form.current_password.data):
            form.current_password.errors.append('Current password is incorrect.')
            flash('Current password is incorrect.', 'error')
            return render_template('settings/settings_password.html', title='Change Password', form=form, user=user)
        try:
            user.set_password(form.password.data)
            db.session.commit()
            # A new password ends every session (User.get_id); keep this one.
            login_user(user, remember=True)
            flash('Password changed successfully!', 'success')
            print('Password changed successfully for user ID:', current_user.id)
            return redirect(url_for('settings.account_pw'))
        except Exception as e:
            db.session.rollback()
            print('An error occurred while changing the password:', str(e))
            flash('An error occurred. Please try again.', 'error')

    return render_template('settings/settings_password.html', title='Change Password', form=form, user=user)

def _stored_preference_formdata(prefs) -> dict:
    """The current preferences as the form would post them.

    ``/settings_panel`` validates the whole form, and WTForms rejects a
    SelectField that is simply absent ("Not a valid choice"). The top-bar tile
    slider posts one field, so it used to fail validation every time and the
    size never persisted. Absent fields now mean "keep what is stored".
    """
    # No row yet (first save ever) -> the model defaults, same as a GET shows.
    return {
        'items_per_page': str(getattr(prefs, 'items_per_page', None) or 50),
        'default_sort': getattr(prefs, 'default_sort', None) or 'name',
        'default_sort_order': getattr(prefs, 'default_sort_order', None) or 'asc',
        'theme': getattr(prefs, 'theme', None) or 'default',
        'icon_pack': getattr(prefs, 'icon_pack', None) or 'outline',
        'font': getattr(prefs, 'font', None) or 'system-ui',
        'tile_size': _normalize_tile_percent(getattr(prefs, 'tile_size', None)),
        'show_tile_titles': 'true' if getattr(prefs, 'show_tile_titles', True) else 'false',
        'browser_player_engine': getattr(prefs, 'browser_player_engine', None) or '',
        'preferred_game_locale': getattr(prefs, 'preferred_game_locale', None) or 'en-US',
    }


def _member_engine_choice_open() -> bool:
    """Whether the Preferences modal shows the engine picker at all."""
    try:
        from oneirodex.utils.browser_player import play_engine_fields

        return bool(play_engine_fields().get('browser_player_member_choice'))
    except Exception:
        return False


@settings_bp.route('/settings_panel', methods=['GET', 'POST'])
@login_required
def settings_panel():
    # The modal posts every field (plus `_full_form`), and an unchecked box is
    # simply absent there — so no merge, or a box could never be switched off.
    # Anything else (the top-bar tile slider) is a partial save and gets the
    # stored values filled in underneath it.
    if request.method == 'POST' and not request.form.get('_full_form'):
        from werkzeug.datastructures import MultiDict

        merged = MultiDict(_stored_preference_formdata(current_user.preferences))
        for key, values in request.form.lists():
            merged.setlist(key, values)
        form = UserPreferencesForm(formdata=merged)
    else:
        form = UserPreferencesForm()

    if request.method == 'POST' and form.validate_on_submit():
        if not current_user.preferences:
            current_user.preferences = UserPreference(user_id=current_user.id)
        
        current_user.preferences.items_per_page = form.items_per_page.data
        current_user.preferences.default_sort = form.default_sort.data
        current_user.preferences.default_sort_order = form.default_sort_order.data
        current_user.preferences.theme = form.theme.data or 'default'
        current_user.preferences.icon_pack = form.icon_pack.data or 'outline'
        current_user.preferences.font = form.font.data or 'system-ui'
        current_user.preferences.tile_size = _normalize_tile_percent(form.tile_size.data)
        current_user.preferences.show_tile_titles = bool(form.show_tile_titles.data)
        # Stored even when the admin has member choice off: the picker is
        # hidden then, so the value is whatever was already there, and it
        # comes back into force if the admin opens the choice later.
        current_user.preferences.browser_player_engine = (
            form.browser_player_engine.data or None
        )
        current_user.preferences.preferred_game_locale = (
            form.preferred_game_locale.data or 'en-US'
        )
        
        try:
            db.session.add(current_user.preferences)
            db.session.commit()
            return api_ok({
                'message': 'Preferences updated successfully!',
                'icon_pack': current_user.preferences.icon_pack or 'outline',
                'font': current_user.preferences.font or 'system-ui',
                'theme': current_user.preferences.theme or 'default',
            })
        except Exception as e:
            db.session.rollback()
            return api_error(str(e), code='internal')
    
    if request.method == 'GET':
        prefs = current_user.preferences
        if prefs:
            form.items_per_page.data = prefs.items_per_page or 50
            form.default_sort.data = prefs.default_sort or 'name'
            form.default_sort_order.data = prefs.default_sort_order or 'asc'
            form.theme.data = prefs.theme or 'default'
            form.icon_pack.data = getattr(prefs, 'icon_pack', None) or 'outline'
            form.font.data = getattr(prefs, 'font', None) or 'system-ui'
            form.tile_size.data = _normalize_tile_percent(getattr(prefs, 'tile_size', None))
            form.show_tile_titles.data = bool(getattr(prefs, 'show_tile_titles', True))
            form.browser_player_engine.data = (
                getattr(prefs, 'browser_player_engine', None) or ''
            )
            form.preferred_game_locale.data = (
                getattr(prefs, 'preferred_game_locale', None) or 'en-US'
            )
        return render_template(
            'settings/modal_preferences.html',
            form=form,
            member_engine_choice=_member_engine_choice_open(),
        )
    
    return api_error(
        'Form validation failed',
        code='bad_request',
        errors=form.errors,
    )
