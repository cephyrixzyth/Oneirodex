from flask import Blueprint, render_template, flash, redirect, url_for, request
from oneirodex import db
from sqlalchemy import select
from oneirodex.forms import SetupForm, IGDBSetupForm
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)
from oneirodex.models import User, GlobalSettings
from oneirodex.utils.setup import (
    is_setup_required,
    set_setup_step,
    stage_setup_step as _stage_setup_step,
    mark_setup_complete,
    get_current_setup_step,
)
from uuid import uuid4
from datetime import datetime, timezone
from oneirodex.utils.event_logging import log_system_event

setup_bp = Blueprint('setup', __name__)


def _require_setup_admin():
    """Steps 2-4 belong to the admin created in step 1, who is signed in by it.

    They used to be open to anyone while the wizard was in progress, so any
    visitor could point the install's mail at their own SMTP server (and so
    receive the admin's password-reset links) before the admin got there.
    """
    from flask_login import current_user
    from oneirodex.utils.rbac import normalize_role

    if current_user.is_authenticated and normalize_role(getattr(current_user, 'role', None)) == 'admin':
        return None
    flash('Sign in with the admin account you just created to finish setup.', 'warning')
    return redirect(url_for('login.login', next=request.path))


def _setup_failed(what: str, exc: Exception):
    """Log the detail; show the visitor a fixed message (no exception text)."""
    from flask import current_app

    db.session.rollback()
    # The app log, not the database: the database is usually what just failed.
    current_app.logger.error('%s failed during setup: %s', what, type(exc).__name__)
    flash(f'{what} could not be saved. Check the server log for details.', 'error')

@setup_bp.route('/setup', methods=['GET'])
def setup():
    from oneirodex.utils.setup import is_setup_in_progress, get_setup_redirect_url

    # Mid-wizard: bounce to the real current step (do not claim "already completed").
    if not is_setup_required() and is_setup_in_progress():
        return redirect(get_setup_redirect_url())

    if not is_setup_required():
        flash('Setup has already been completed.', 'warning')
        return redirect(url_for('login.login'))

    # Set setup step to 1 (admin account creation)
    set_setup_step(1)

    form = SetupForm()
    return render_template('setup/setup.html', form=form, is_setup_mode=True)

@setup_bp.route('/setup/submit', methods=['POST'])
def setup_submit():
    if not is_setup_required():
        flash('Setup has already been completed.', 'warning')
        return redirect(url_for('login.login'))

    form = SetupForm()
    if form.validate_on_submit():
        # Never log the CSRF token — anything with log access could replay it.
        print("Setup form validation succeeded")
        
        user = User(
            name=form.username.data,
            email=form.email.data.lower(),
            role='admin',
            is_email_verified=True,
            user_id=str(uuid4()),
            invite_quota=10,
            created=datetime.now(timezone.utc)
        )
        user.set_password(form.password.data)
        
        try:
            # The admin row and the step advance must land in ONE transaction.
            #
            # These used to be two commits: user first, then set_setup_step(2).
            # Anything failing in that window — a crash, a restart, a dropped
            # connection — left "a user exists" and "still on step 1", and that
            # state is an unrecoverable redirect loop: the before_request hook
            # sends every request to get_setup_redirect_url(), which returns
            # /setup for step 1, and /setup redirects straight back to it. The
            # install is unreachable with no way out through the UI.
            db.session.add(user)
            _stage_setup_step(2)  # same session, no intermediate commit
            db.session.commit()
            # The rest of the wizard requires this admin (_require_setup_admin).
            from flask_login import login_user
            login_user(user)
            log_system_event("Admin account created during setup", event_type='setup', event_level='information')
            flash('Admin account created successfully! Please configure your SMTP settings.', 'success')
            return redirect(url_for('setup.setup_smtp'))
        except Exception as e:
            _setup_failed('The admin account', e)
            return redirect(url_for('setup.setup'))
    else:
        # Field names only: form.data holds the password and the CSRF token.
        print(f"Setup form validation failed for: {sorted(form.errors)}")
        return render_template('setup/setup.html', form=form, is_setup_mode=True)

@setup_bp.route('/setup/smtp', methods=['GET', 'POST'])
def setup_smtp():
    # Ensure we're in the correct setup step
    current_step = get_current_setup_step()
    
    if current_step is None:
        flash('Setup already completed.', 'warning')
        return redirect(url_for('login.login'))
    
    if current_step != 2:
        flash('Please complete the admin account setup first.', 'warning')
        return redirect(url_for('setup.setup'))
    refusal = _require_setup_admin()
    if refusal is not None:
        return refusal

    if request.method == 'POST':
        # Check if skip button was clicked
        if 'skip_smtp' in request.form:
            set_setup_step(3)  # Features
            flash('SMTP setup skipped. Choose which features to keep enabled.', 'info')
            return redirect(url_for('setup.setup_features'))

        settings = global_settings_row_or_create()

        settings.smtp_server = request.form.get('smtp_server')
        settings.smtp_port = int(request.form.get('smtp_port', 587))
        settings.smtp_username = request.form.get('smtp_username')
        settings.smtp_password = request.form.get('smtp_password')
        settings.smtp_use_tls = request.form.get('smtp_use_tls') == 'true'
        settings.smtp_default_sender = request.form.get('smtp_default_sender')
        settings.smtp_enabled = request.form.get('smtp_enabled') == 'true'

        try:
            db.session.commit()
            set_setup_step(3)
            log_system_event("SMTP settings configured during setup", event_type='setup', event_level='information')
            flash('SMTP settings saved. Choose which features to keep enabled.', 'success')
            return redirect(url_for('setup.setup_features'))
        except Exception as e:
            _setup_failed('SMTP settings', e)

    return render_template('setup/setup_smtp.html', is_setup_mode=True)


@setup_bp.route('/setup/features', methods=['GET', 'POST'])
def setup_features():
    current_step = get_current_setup_step()
    if current_step is None:
        flash('Setup already completed.', 'warning')
        return redirect(url_for('login.login'))
    if current_step != 3:
        flash('Please complete the previous setup steps first.', 'warning')
        return redirect(url_for('setup.setup'))
    refusal = _require_setup_admin()
    if refusal is not None:
        return refusal

    defaults = {
        'enable_game_updates': True,
        'enable_game_extras': True,
        'attract_mode_enabled': True,
        'enable_arr_module': True,
        'enable_ai_assist': True,
        'enable_malware_scan': True,
    }

    if request.method == 'POST':
        settings = global_settings_row_or_create()
        settings.enable_game_updates = 'enable_game_updates' in request.form
        settings.enable_game_extras = 'enable_game_extras' in request.form
        settings.attract_mode_enabled = 'attract_mode_enabled' in request.form
        settings.enable_arr_module = 'enable_arr_module' in request.form
        settings.enable_ai_assist = 'enable_ai_assist' in request.form
        settings.enable_malware_scan = 'enable_malware_scan' in request.form
        # Auth stays off — never enable OIDC from setup features.
        settings.oidc_enabled = False
        try:
            db.session.commit()
            set_setup_step(4)
            log_system_event("Feature preferences saved during setup", event_type='setup', event_level='information')
            flash('Feature preferences saved. Configure IGDB next.', 'success')
            return redirect(url_for('setup.setup_igdb'))
        except Exception as e:
            _setup_failed('Feature preferences', e)

    return render_template(
        'setup/setup_features.html',
        is_setup_mode=True,
        defaults=defaults,
    )


@setup_bp.route('/setup/igdb', methods=['GET', 'POST'])
def setup_igdb():
    current_step = get_current_setup_step()
    
    if current_step != 4:
        flash('Please complete the previous setup steps first.', 'warning')
        return redirect(url_for('setup.setup'))
    refusal = _require_setup_admin()
    if refusal is not None:
        return refusal

    form = IGDBSetupForm()
    if form.validate_on_submit():
        settings = global_settings_row_or_create()
        
        settings.igdb_client_id = form.igdb_client_id.data
        settings.igdb_client_secret = form.igdb_client_secret.data
        
        try:
            db.session.commit()
            mark_setup_complete()  # Mark setup as fully completed
            log_system_event("IGDB settings configured - Setup completed", event_type='setup', event_level='information')
            flash('Setup completed successfully! Please create your first game library.', 'success')
            from oneirodex.init_data import initialize_library_folders, insert_default_scanning_filters, initialize_default_settings, initialize_allowed_file_types, initialize_discovery_sections

            initialize_library_folders()
            initialize_discovery_sections()
            insert_default_scanning_filters()
            initialize_default_settings()
            initialize_allowed_file_types()
            return redirect(url_for('library.libraries'))
        except Exception as e:
            _setup_failed('IGDB settings', e)

    return render_template('setup/setup_igdb.html', form=form, is_setup_mode=True)
