import os
from urllib.parse import urlparse
from flask import Blueprint, render_template, flash, redirect, url_for, request, current_app
from oneirodex import db
from sqlalchemy import select
from oneirodex.forms import SetupForm, IGDBSetupForm
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)
from oneirodex.models import User, GlobalSettings, Library, LibraryPlatform
from oneirodex.utils.setup import (
    is_setup_required,
    set_setup_step,
    stage_setup_step as _stage_setup_step,
    mark_setup_complete,
    get_current_setup_step,
)
from oneirodex.utils.admin_invariant import lock_admin_mutation
from uuid import uuid4
from datetime import datetime, timezone
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.oidc import is_secure_oidc_issuer

setup_bp = Blueprint('setup', __name__)


def _require_setup_admin():
    """Steps 2-6 belong to the admin created in step 1, who is signed in by it.

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

        try:
            # The initial anonymous check above is only a fast path. Serialize
            # and recheck inside the write transaction so competing first-run
            # submissions cannot both observe an empty users table.
            lock_admin_mutation(db.session)
            if not is_setup_required():
                db.session.rollback()
                flash('Setup has already been completed.', 'warning')
                return redirect(url_for('login.login'))

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

    # IGDB is useful for matching, but installs without Twitch credentials must
    # still be able to continue. API choices and the first library are next.
    if request.method == 'POST' and 'skip_igdb' in request.form:
        try:
            set_setup_step(5)
            flash('IGDB skipped. Choose any additional API connections, or continue without them.', 'info')
            return redirect(url_for('setup.setup_integrations'))
        except Exception as e:
            _setup_failed('Setup', e)
            return redirect(url_for('setup.setup_igdb'))

    form = IGDBSetupForm()
    if form.validate_on_submit():
        settings = global_settings_row_or_create()
        
        settings.igdb_client_id = form.igdb_client_id.data
        settings.igdb_client_secret = form.igdb_client_secret.data
        
        try:
            set_setup_step(5)
            log_system_event("IGDB settings saved during setup", event_type='setup', event_level='information')
            flash('IGDB settings saved. Choose any additional API connections, or continue without them.', 'success')
            return redirect(url_for('setup.setup_integrations'))
        except Exception as e:
            _setup_failed('IGDB settings', e)

    return render_template('setup/setup_igdb.html', form=form, is_setup_mode=True)


@setup_bp.route('/setup/integrations', methods=['GET', 'POST'])
def setup_integrations():
    """Collect optional API credentials that are stored in app settings."""
    if get_current_setup_step() != 5:
        return redirect(url_for('setup.setup'))
    refusal = _require_setup_admin()
    if refusal is not None:
        return refusal

    settings = global_settings_row_or_create()
    if request.method == 'POST':
        if request.form.get('skip_integrations') == '1':
            set_setup_step(6)
            flash('Optional API setup skipped. You can continue without API credentials.', 'info')
            return redirect(url_for('setup.setup_library'))

        # These keys are the app-managed provider credentials. Blank values are
        # deliberately ignored so resuming setup never clears a saved secret.
        credential_fields = {
            'steam_web_api_key': 'steam_web_api_key',
            'steamgriddb_api_key': 'steamgriddb_api_key',
            'giantbomb_api_key': 'giantbomb_api_key',
            'mobygames_api_key': 'mobygames_api_key',
            'thegamesdb_api_key': 'thegamesdb_api_key',
        }
        try:
            for field, setting_name in credential_fields.items():
                if request.form.get(f'configure_{field}') == 'on':
                    value = (request.form.get(field) or '').strip()
                    if value:
                        setattr(settings, setting_name, value[:512])

            if request.form.get('configure_oidc') == 'on':
                for field, max_length in (
                    ('oidc_issuer_url', 512),
                    ('oidc_client_id', 255),
                    ('oidc_redirect_uri', 512),
                    ('oidc_scopes', 255),
                    ('oidc_role_claim', 64),
                ):
                    value = (request.form.get(field) or '').strip()
                    if value:
                        if field.endswith('_url') or field == 'oidc_redirect_uri':
                            parsed = urlparse(value)
                            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                                raise ValueError(f'{field} must be an HTTP or HTTPS URL')
                        if field == 'oidc_issuer_url' and not is_secure_oidc_issuer(value):
                            raise ValueError('OIDC issuer URL must use HTTPS')
                        setattr(settings, field, value[:max_length])
                oidc_secret = (request.form.get('oidc_client_secret') or '').strip()
                if oidc_secret:
                    settings.oidc_client_secret = oidc_secret[:512]

            settings.enable_hltb_integration = request.form.get('enable_hltb_integration') == 'on'
            settings.oidc_enabled = False  # Auth provider activation remains an explicit post-setup action.
            db.session.commit()
            set_setup_step(6)
            log_system_event("Optional API preferences saved during setup", event_type='setup', event_level='information')
            flash('API choices saved. Add your first library next, or skip it for now.', 'success')
            return redirect(url_for('setup.setup_library'))
        except ValueError:
            db.session.rollback()
            flash('OIDC issuer must use HTTPS; redirect URI must use a valid HTTP or HTTPS URL.', 'error')
            return render_template(
                'setup/setup_integrations.html',
                is_setup_mode=True,
                settings=global_settings_row_or_create(),
            )
        except Exception as exc:
            _setup_failed('API settings', exc)

    return render_template(
        'setup/setup_integrations.html',
        is_setup_mode=True,
        settings=settings,
    )


def _finish_setup(*, library_created=False, scan_status=None):
    """Initialize first-run defaults and close the wizard after optional library setup."""
    from oneirodex.init_data import (
        initialize_library_folders,
        insert_default_scanning_filters,
        initialize_default_settings,
        initialize_allowed_file_types,
        initialize_discovery_sections,
    )

    try:
        initialize_library_folders()
        initialize_discovery_sections()
        insert_default_scanning_filters()
        initialize_default_settings()
        initialize_allowed_file_types()
        mark_setup_complete()
    except Exception as exc:
        _setup_failed('Setup', exc)
        return redirect(url_for('setup.setup_library'))
    log_system_event("Setup completed", event_type='setup', event_level='information')
    if library_created:
        if scan_status in ('started', 'queued'):
            flash('Your first library is ready and its initial scan has started or queued.', 'success')
        else:
            flash('Your first library is ready. Start its first scan from Libraries & scans.', 'warning')
    else:
        flash('Setup is ready. You can add a library at any time from Libraries & scans.', 'success')
    return redirect(url_for('library.libraries'))


@setup_bp.route('/setup/library', methods=['GET', 'POST'])
def setup_library():
    """Optional first library step with the same guarded scan queue as admin setup."""
    if get_current_setup_step() != 6:
        return redirect(url_for('setup.setup'))
    refusal = _require_setup_admin()
    if refusal is not None:
        return refusal

    if request.method == 'POST' and request.form.get('skip_library') == 'on':
        return _finish_setup()

    platforms = [(platform.name, platform.value) for platform in LibraryPlatform]
    errors = []
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        platform_key = (request.form.get('platform') or '').strip()
        folder = os.path.normpath((request.form.get('folder_path') or '').strip())
        scan_mode = (request.form.get('scan_mode') or 'folders').strip()
        try:
            scan_depth = int(request.form.get('scan_depth') or '1')
        except (TypeError, ValueError):
            scan_depth = 0

        if not name or len(name) > 255:
            errors.append('Enter a library name up to 255 characters.')
        if platform_key not in dict(platforms):
            errors.append('Choose a valid platform.')
        if scan_mode not in ('folders', 'files'):
            errors.append('Choose folders or files for the folder layout.')
        if scan_depth not in (1, 2):
            errors.append('Choose a scan depth of one or two folders.')
        if not folder or len(folder) > 2048:
            errors.append('Enter a server-visible folder path.')
        else:
            from oneirodex.utils.security import get_allowed_base_directories, is_safe_path

            safe, _reason = is_safe_path(folder, get_allowed_base_directories(current_app))
            if not safe:
                errors.append('That folder is outside the configured library locations.')
            elif not os.path.isdir(folder):
                errors.append('That folder is not available as a directory on the server.')

        if not errors:
            platform = LibraryPlatform[platform_key]
            library = db.session.execute(
                select(Library).filter_by(name=name, platform=platform, last_scan_folder=folder)
            ).scalars().first()
            if library is None:
                library = Library(
                    name=name,
                    platform=platform,
                    scan_depth=scan_depth,
                    last_scan_folder=folder,
                )
                db.session.add(library)
                try:
                    db.session.commit()
                except Exception as exc:
                    _setup_failed('The first library', exc)
                    return render_template(
                        'setup/setup_library.html', is_setup_mode=True,
                        platforms=platforms, errors=[],
                    )

            scan_status = None
            try:
                from oneirodex.utils.scan_queue import start_or_queue_scan

                queued = start_or_queue_scan(
                    folder_path=folder,
                    library_uuid=library.uuid,
                    scan_mode=scan_mode,
                    queue_policy='queue',
                    force_parallel=False,
                    allow_force=False,
                    app=current_app._get_current_object(),
                )
                scan_status = queued.get('status')
            except Exception as exc:
                current_app.logger.warning('First library scan could not be queued (%s)', type(exc).__name__)
            return _finish_setup(library_created=True, scan_status=scan_status)

    return render_template(
        'setup/setup_library.html',
        is_setup_mode=True,
        platforms=platforms,
        errors=errors,
    )
