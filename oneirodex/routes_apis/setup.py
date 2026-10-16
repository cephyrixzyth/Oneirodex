"""First-run wizard state and transitions for the member React shell."""

import os
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

from flask import current_app, request
from flask_login import current_user, login_required, login_user
from sqlalchemy import select

from oneirodex import db
from oneirodex.forms import IGDBSetupForm, SetupForm
from oneirodex.models import Library, LibraryPlatform, User
from oneirodex.schemas.setup import SetupTransitionBody
from oneirodex.utils.admin_invariant import lock_admin_mutation
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.global_settings import global_settings_row, global_settings_row_or_create
from oneirodex.utils.oidc import is_secure_oidc_issuer
from oneirodex.utils.setup import (
    get_current_setup_step,
    is_setup_required,
    mark_setup_complete,
    stage_setup_step,
)
from oneirodex.utils.setup_projections import state_settings as _state_settings_shared
from oneirodex.utils.validation import validate_body

from . import apis_bp


@apis_bp.after_request
def setup_no_store(response):
    if request.path.startswith('/api/setup/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


def _is_setup_admin() -> bool:
    from oneirodex.utils.rbac import normalize_role

    return bool(current_user.is_authenticated and normalize_role(getattr(current_user, 'role', None)) == 'admin')


def _state_settings():
    return _state_settings_shared()


@apis_bp.route('/setup/state', methods=['GET'])
def setup_state():
    """Expose the current wizard step and safe, non-secret form values."""
    required = is_setup_required()
    step = 1 if required else get_current_setup_step()
    if step is None:
        return api_ok({'complete': True, 'required': False, 'step': None})
    if step > 1 and not _is_setup_admin():
        return api_error('Sign in with the administrator account created during setup.', code='unauthorized')
    return api_ok({
        'complete': False,
        'required': required,
        'step': step,
        'platforms': [{'key': item.name, 'label': item.value} for item in LibraryPlatform],
        'settings': _state_settings() if step > 1 else {},
    })


def _finish_setup_api(library_created=False, scan_status=None):
    from oneirodex.init_data import (
        initialize_allowed_file_types,
        initialize_default_settings,
        initialize_discovery_sections,
        initialize_library_folders,
        insert_default_scanning_filters,
    )

    try:
        initialize_library_folders()
        initialize_discovery_sections()
        insert_default_scanning_filters()
        initialize_default_settings()
        initialize_allowed_file_types()
        mark_setup_complete()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error('Setup finalization failed: %s', type(exc).__name__)
        return api_error('Setup could not be completed. Try again or check the server log.', code='internal')
    log_system_event('Setup completed', event_type='setup', event_level='information')
    message = 'Setup is ready. You can add a library at any time from Libraries & scans.'
    if library_created:
        message = (
            'Your first library is ready and its initial scan has started or queued.'
            if scan_status in ('started', 'queued')
            else 'Your first library is ready. Start its first scan from Libraries & scans.'
        )
    return api_ok({'complete': True, 'message': message, 'next_url': '/libraries'})


@apis_bp.route('/setup/step', methods=['POST'])
@validate_body(SetupTransitionBody)
def submit_setup_step(body: SetupTransitionBody):
    """Validate and commit exactly the current first-run transition."""
    step = 1 if is_setup_required() else get_current_setup_step()
    if step is None:
        return api_error('Setup has already been completed.', code='conflict')
    if body.step != step:
        return api_error('This setup step is no longer current. Reload setup to continue.', code='conflict')
    if step > 1 and not _is_setup_admin():
        return api_error('Sign in with the administrator account created during setup.', code='unauthorized')

    if step == 1:
        form = SetupForm(data={
            'username': body.username, 'email': body.email,
            'password': body.password, 'confirm_password': body.confirm_password,
        }, meta={'csrf': False})
        if not form.validate():
            return api_error('Check the administrator account details.', code='unprocessable', detail=form.errors)
        try:
            lock_admin_mutation(db.session)
            if not is_setup_required():
                db.session.rollback()
                return api_error('Setup has already been started by another administrator.', code='conflict')
            user = User(
                name=form.username.data, email=form.email.data.lower(), role='admin',
                is_email_verified=True, user_id=str(uuid4()), invite_quota=10,
                created=datetime.now(timezone.utc),
            )
            user.set_password(form.password.data)
            db.session.add(user)
            stage_setup_step(2)
            db.session.commit()
            login_user(user)
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error('Setup administrator creation failed: %s', type(exc).__name__)
            return api_error('The administrator account could not be created.', code='internal')
        log_system_event('Admin account created during setup', event_type='setup', event_level='information')
        return api_ok({'step': 2, 'next_url': '/setup/smtp', 'message': 'Administrator account created.'})

    if step == 2:
        if body.skip:
            from oneirodex.utils.setup import set_setup_step
            set_setup_step(3)
        else:
            settings = global_settings_row_or_create()
            settings.smtp_server = body.smtp_server or None
            settings.smtp_port = body.smtp_port
            settings.smtp_username = body.smtp_username or None
            if body.smtp_password:
                settings.smtp_password = body.smtp_password
            settings.smtp_use_tls = body.smtp_use_tls
            settings.smtp_default_sender = body.smtp_default_sender or None
            settings.smtp_enabled = body.smtp_enabled
            try:
                db.session.commit()
                from oneirodex.utils.setup import set_setup_step
                set_setup_step(3)
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error('Setup SMTP transition failed: %s', type(exc).__name__)
                return api_error('SMTP settings could not be saved.', code='internal')
        return api_ok({'step': 3, 'next_url': '/setup/features'})

    if step == 3:
        settings = global_settings_row_or_create()
        for key in (
            'enable_game_updates', 'enable_game_extras', 'attract_mode_enabled',
            'enable_arr_module', 'enable_ai_assist', 'enable_malware_scan',
        ):
            setattr(settings, key, getattr(body, key))
        settings.oidc_enabled = False
        try:
            db.session.commit()
            from oneirodex.utils.setup import set_setup_step
            set_setup_step(4)
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error('Setup feature transition failed: %s', type(exc).__name__)
            return api_error('Feature preferences could not be saved.', code='internal')
        return api_ok({'step': 4, 'next_url': '/setup/igdb'})

    if step == 4:
        if not body.skip:
            form = IGDBSetupForm(data={
                'igdb_client_id': body.igdb_client_id,
                'igdb_client_secret': body.igdb_client_secret,
            }, meta={'csrf': False})
            if not form.validate():
                return api_error('Check the IGDB credentials or continue without them.', code='unprocessable', detail=form.errors)
            settings = global_settings_row_or_create()
            settings.igdb_client_id = form.igdb_client_id.data
            if form.igdb_client_secret.data:
                settings.igdb_client_secret = form.igdb_client_secret.data
            try:
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error('Setup IGDB transition failed: %s', type(exc).__name__)
                return api_error('IGDB settings could not be saved.', code='internal')
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(5)
        return api_ok({'step': 5, 'next_url': '/setup/integrations'})

    if step == 5:
        if not body.skip:
            settings = global_settings_row_or_create()
            for key in (
                'steam_web_api_key', 'steamgriddb_api_key', 'giantbomb_api_key',
                'mobygames_api_key', 'thegamesdb_api_key',
            ):
                value = getattr(body, key).strip()
                if value:
                    setattr(settings, key, value)
            if body.configure_oidc:
                for field, max_length in (
                    ('oidc_issuer_url', 512), ('oidc_client_id', 255),
                    ('oidc_redirect_uri', 512), ('oidc_scopes', 255),
                    ('oidc_role_claim', 64),
                ):
                    value = getattr(body, field).strip()
                    if value:
                        if field in ('oidc_issuer_url', 'oidc_redirect_uri'):
                            parsed = urlparse(value)
                            if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                                return api_error(f'{field} must be an HTTP or HTTPS URL.', code='unprocessable')
                        if field == 'oidc_issuer_url' and not is_secure_oidc_issuer(value):
                            return api_error('OIDC issuer URL must use HTTPS.', code='unprocessable')
                        setattr(settings, field, value[:max_length])
                if body.oidc_client_secret:
                    settings.oidc_client_secret = body.oidc_client_secret
            settings.enable_hltb_integration = body.enable_hltb_integration
            settings.oidc_enabled = False
            try:
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error('Setup integration transition failed: %s', type(exc).__name__)
                return api_error('Optional API settings could not be saved.', code='internal')
        from oneirodex.utils.setup import set_setup_step
        set_setup_step(6)
        return api_ok({'step': 6, 'next_url': '/setup/library'})

    if step == 6:
        if body.skip:
            return _finish_setup_api()
        platform = next((item for item in LibraryPlatform if item.name == body.platform), None)
        folder = os.path.normpath(body.folder_path.strip())
        errors = {}
        if not body.library_name.strip():
            errors['library_name'] = ['Enter a library name.']
        if platform is None:
            errors['platform'] = ['Choose a valid platform.']
        if not folder:
            errors['folder_path'] = ['Enter a server-visible folder path.']
        else:
            from oneirodex.utils.security import get_allowed_base_directories, is_safe_path
            safe, _reason = is_safe_path(folder, get_allowed_base_directories(current_app))
            if not safe or not os.path.isdir(folder):
                errors['folder_path'] = ['Choose an existing folder inside an allowed library location.']
        if errors:
            return api_error('Check the first library details.', code='unprocessable', detail=errors)
        library = db.session.execute(select(Library).filter_by(
            name=body.library_name.strip(), platform=platform, last_scan_folder=folder,
        )).scalars().first()
        if library is None:
            library = Library(
                name=body.library_name.strip(), platform=platform,
                scan_depth=body.scan_depth, last_scan_folder=folder,
            )
            db.session.add(library)
            try:
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error('First setup library could not be saved: %s', type(exc).__name__)
                return api_error('The first library could not be saved.', code='internal')
        scan_status = None
        try:
            from oneirodex.utils.scan_queue import start_or_queue_scan
            result = start_or_queue_scan(
                folder_path=folder, library_uuid=library.uuid, scan_mode=body.scan_mode,
                queue_policy='queue', force_parallel=False, allow_force=False,
                app=current_app._get_current_object(),
            )
            scan_status = result.get('status')
        except Exception as exc:
            current_app.logger.warning('First library scan could not be queued (%s)', type(exc).__name__)
        return _finish_setup_api(library_created=True, scan_status=scan_status)

    return api_error('Unknown setup step.', code='bad_request')
