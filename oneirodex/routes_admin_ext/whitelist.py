# /oneirodex/routes_admin_ext/whitelist.py
from flask import redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from oneirodex.models import Whitelist, User
from oneirodex import db
from oneirodex.forms import WhitelistForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from . import admin2_bp
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.auth import admin_required
from oneirodex.schemas.whitelist import AddWhitelistBody
from oneirodex.utils.validation import validate_body
from oneirodex.utils.admin_spa import render_admin_spa

@admin2_bp.route('/admin/api/whitelist', methods=['GET'])
@login_required
@admin_required
def list_whitelist_api():
    entries = db.session.execute(select(Whitelist).order_by(Whitelist.email)).scalars().all()
    emails = [entry.email.lower() for entry in entries]
    registered = set(db.session.execute(
        select(func.lower(User.email)).filter(func.lower(User.email).in_(emails))
    ).scalars().all()) if emails else set()
    return api_ok(entries=[{'id': entry.id, 'email': entry.email,
                           'is_registered': entry.email.lower() in registered} for entry in entries])


@admin2_bp.route('/admin/api/whitelist', methods=['POST'])
@login_required
@admin_required
@validate_body(AddWhitelistBody)
def add_whitelist_api(body: AddWhitelistBody):
    entry = Whitelist(email=body.email)
    try:
        db.session.add(entry)
        db.session.commit()
        log_system_event(f"Admin {current_user.name} added email to whitelist: {body.email}", event_type='audit', event_level='information')
        return api_ok(id=entry.id, email=entry.email, status=201)
    except IntegrityError:
        db.session.rollback()
        log_system_event(f"Admin {current_user.name} attempted to add duplicate email to whitelist: {body.email}", event_type='audit', event_level='warning')
        return api_error('The email is already in the whitelist.', code='conflict')
    except Exception:
        db.session.rollback()
        log_system_event('Error adding email to whitelist', event_type='error', event_level='error')
        return api_error('Unable to add the email to the whitelist.', code='internal')


@admin2_bp.route('/admin/whitelist', methods=['GET', 'POST'])
@login_required
@admin_required
def whitelist():
    form = WhitelistForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        
        # Additional validation
        if len(email) > 120:
            flash('Email address is too long (maximum 120 characters)', 'danger')
            return redirect(url_for('admin2.whitelist'))
        
        # Validate email format more strictly
        if not email or '@' not in email or email.count('@') != 1:
            flash('Invalid email format', 'danger')
            return redirect(url_for('admin2.whitelist'))
        try:
            new_whitelist = Whitelist(email=email)
            db.session.add(new_whitelist)
            db.session.commit()
            log_system_event(f"Admin {current_user.name} added email to whitelist: {email}", event_type='audit', event_level='information')
            flash('The email was successfully added to the whitelist!', 'success')
        except IntegrityError:
            db.session.rollback()
            log_system_event(f"Admin {current_user.name} attempted to add duplicate email to whitelist: {email}", event_type='audit', event_level='warning')
            flash('The email is already in the whitelist!', 'danger')
        except Exception as e:
            db.session.rollback()
            log_system_event(f"Error adding email to whitelist {email}: {str(e)}", event_type='error', event_level='error')
            flash('An error occurred while adding the email to the whitelist', 'danger')
        return redirect(url_for('admin2.whitelist'))

    if request.method == 'POST':
        errors = form.email.errors or ['Please enter a valid email address.']
        for error in errors:
            flash(error, 'danger')
        return redirect(url_for('admin2.whitelist'))

    return render_admin_spa(title='Whitelist · Oneirodex Admin')

@admin2_bp.route('/admin/whitelist/<int:whitelist_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_whitelist(whitelist_id):
    # Validate whitelist_id
    if whitelist_id <= 0:
        return api_error('Invalid whitelist ID', code='bad_request')
    
    whitelist_entry = db.session.get(Whitelist, whitelist_id)
    if not whitelist_entry:
        abort(404)
    
    try:
        db.session.delete(whitelist_entry)
        log_system_event(f"Admin {current_user.name} deleted whitelist entry: {whitelist_entry.email}", event_type='audit', event_level='information')
        db.session.commit()
        return api_ok({'message': 'Entry deleted successfully'})
    except Exception as e:
        db.session.rollback()
        log_system_event(f"Error deleting whitelist entry {whitelist_id}: {str(e)}", event_type='error', event_level='error')
        return api_error('An error occurred while deleting the entry', code='internal')
