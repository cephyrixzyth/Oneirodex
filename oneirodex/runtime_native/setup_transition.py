"""FastAPI transition API for the ordered first-run setup wizard."""
from __future__ import annotations

import os
import re
from contextlib import nullcontext
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse

from .request_auth import request_auth_context


class SetupTransitionData:
    def current_step(self):
        from oneirodex.utils.setup import get_current_setup_step

        return get_current_setup_step()

    def transition(self, body, flask_app, *, database_scope=None):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library, LibraryPlatform, User
        from oneirodex.utils.admin_invariant import lock_admin_mutation
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.global_settings import global_settings_row_or_create
        from oneirodex.utils.setup import (
            get_current_setup_step, is_setup_required, mark_setup_complete,
            set_setup_step, stage_setup_step,
        )

        step = 1 if is_setup_required() else get_current_setup_step()
        if step is None:
            return None, ('conflict', 'Setup has already been completed.', 409, None), None
        if body['step'] != step:
            return None, (
                'conflict', 'This setup step is no longer current. Reload setup to continue.',
                409, None,
            ), None

        if step == 1:
            errors = _setup_account_errors(body)
            if errors:
                return None, ('unprocessable', 'Check the administrator account details.', 422, errors), None
            try:
                lock_admin_mutation(db.session)
                if not is_setup_required():
                    db.session.rollback()
                    return None, (
                        'conflict', 'Setup has already been started by another administrator.',
                        409, None,
                    ), None
                now = datetime.now(timezone.utc)
                user = User(
                    name=body['username'], email=body['email'].lower(), role='admin',
                    is_email_verified=True, user_id=str(uuid4()), invite_quota=10, created=now,
                )
                user.set_password(body['password'])
                db.session.add(user)
                stage_setup_step(2)
                db.session.commit()
            except Exception as exc:  # noqa: BLE001 — keep setup storage details private
                db.session.rollback()
                flask_app.logger.error('Setup administrator creation failed: %s', type(exc).__name__)
                return None, ('internal', 'The administrator account could not be created.', 500, None), None
            log_system_event(
                'Admin account created during setup', event_type='setup',
                event_level='information', audit_user='system',
            )
            return {
                'step': 2, 'next_url': '/setup/smtp', 'message': 'Administrator account created.',
            }, None, user

        if step == 2:
            if body['skip']:
                set_setup_step(3)
            else:
                settings = global_settings_row_or_create()
                settings.smtp_server = body['smtp_server'] or None
                settings.smtp_port = body['smtp_port']
                settings.smtp_username = body['smtp_username'] or None
                if body['smtp_password']:
                    settings.smtp_password = body['smtp_password']
                settings.smtp_use_tls = body['smtp_use_tls']
                settings.smtp_default_sender = body['smtp_default_sender'] or None
                settings.smtp_enabled = body['smtp_enabled']
                if not _commit_step(db, set_setup_step, 3, flask_app, 'Setup SMTP transition'):
                    return None, ('internal', 'SMTP settings could not be saved.', 500, None), None
            return {'step': 3, 'next_url': '/setup/features'}, None, None

        if step == 3:
            settings = global_settings_row_or_create()
            for key in (
                'enable_game_updates', 'enable_game_extras', 'attract_mode_enabled',
                'enable_arr_module', 'enable_ai_assist', 'enable_malware_scan',
            ):
                setattr(settings, key, body[key])
            settings.oidc_enabled = False
            if not _commit_step(db, set_setup_step, 4, flask_app, 'Setup feature transition'):
                return None, ('internal', 'Feature preferences could not be saved.', 500, None), None
            return {'step': 4, 'next_url': '/setup/igdb'}, None, None

        if step == 4:
            if not body['skip']:
                errors = _igdb_setup_errors(body)
                if errors:
                    return None, (
                        'unprocessable', 'Check the IGDB credentials or continue without them.',
                        422, errors,
                    ), None
                settings = global_settings_row_or_create()
                settings.igdb_client_id = body['igdb_client_id']
                if body['igdb_client_secret']:
                    settings.igdb_client_secret = body['igdb_client_secret']
                try:
                    db.session.commit()
                except Exception as exc:  # noqa: BLE001
                    db.session.rollback()
                    flask_app.logger.error('Setup IGDB transition failed: %s', type(exc).__name__)
                    return None, ('internal', 'IGDB settings could not be saved.', 500, None), None
            set_setup_step(5)
            return {'step': 5, 'next_url': '/setup/integrations'}, None, None

        if step == 5:
            if not body['skip']:
                settings = global_settings_row_or_create()
                for key in (
                    'steam_web_api_key', 'steamgriddb_api_key', 'giantbomb_api_key',
                    'mobygames_api_key', 'thegamesdb_api_key',
                ):
                    value = body[key].strip()
                    if value:
                        setattr(settings, key, value)
                if body['configure_oidc']:
                    for field, max_length in (
                        ('oidc_issuer_url', 512), ('oidc_client_id', 255),
                        ('oidc_redirect_uri', 512), ('oidc_scopes', 255),
                        ('oidc_role_claim', 64),
                    ):
                        value = body[field].strip()
                        if value:
                            if field in ('oidc_issuer_url', 'oidc_redirect_uri'):
                                parsed = urlparse(value)
                                if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                                    return None, (
                                        'unprocessable', f'{field} must be an HTTP or HTTPS URL.',
                                        422, None,
                                    ), None
                            if field == 'oidc_issuer_url':
                                from oneirodex.utils.oidc import is_secure_oidc_issuer

                                if not is_secure_oidc_issuer(value):
                                    return None, (
                                        'unprocessable', 'OIDC issuer URL must use HTTPS.', 422, None,
                                    ), None
                            setattr(settings, field, value[:max_length])
                    if body['oidc_client_secret']:
                        settings.oidc_client_secret = body['oidc_client_secret']
                settings.enable_hltb_integration = body['enable_hltb_integration']
                settings.oidc_enabled = False
                if not _commit_step(db, set_setup_step, 6, flask_app, 'Setup integration transition'):
                    return None, ('internal', 'Optional API settings could not be saved.', 500, None), None
            else:
                set_setup_step(6)
            return {'step': 6, 'next_url': '/setup/library'}, None, None

        if step == 6:
            if body['skip']:
                return self._finish_setup(db, mark_setup_complete, flask_app), None, None
            platform = next((item for item in LibraryPlatform if item.name == body['platform']), None)
            folder = os.path.normpath(body['folder_path'].strip())
            errors = {}
            if not body['library_name'].strip():
                errors['library_name'] = ['Enter a library name.']
            if platform is None:
                errors['platform'] = ['Choose a valid platform.']
            if not folder:
                errors['folder_path'] = ['Enter a server-visible folder path.']
            else:
                from oneirodex.utils.security import get_allowed_base_directories, is_safe_path

                safe, _reason = is_safe_path(
                    folder, get_allowed_base_directories(flask_app), logger=flask_app.logger,
                )
                if not safe or not os.path.isdir(folder):
                    errors['folder_path'] = [
                        'Choose an existing folder inside an allowed library location.'
                    ]
            if errors:
                return None, ('unprocessable', 'Check the first library details.', 422, errors), None
            library = db.session.execute(select(Library).filter_by(
                name=body['library_name'].strip(), platform=platform, last_scan_folder=folder,
            )).scalars().first()
            if library is None:
                library = Library(
                    name=body['library_name'].strip(), platform=platform,
                    scan_depth=body['scan_depth'], last_scan_folder=folder,
                )
                db.session.add(library)
                try:
                    db.session.commit()
                except Exception as exc:  # noqa: BLE001
                    db.session.rollback()
                    flask_app.logger.error('First setup library could not be saved: %s', type(exc).__name__)
                    return None, ('internal', 'The first library could not be saved.', 500, None), None
            scan_status = None
            try:
                from oneirodex.utils.scan_queue import start_or_queue_scan

                result = start_or_queue_scan(
                    folder_path=folder, library_uuid=library.uuid, scan_mode=body['scan_mode'],
                    queue_policy='queue', force_parallel=False, allow_force=False, app=flask_app,
                    database_scope=database_scope,
                )
                scan_status = result.get('status')
            except Exception as exc:  # noqa: BLE001 — library remains usable without a queued scan
                flask_app.logger.warning('First library scan could not be queued (%s)', type(exc).__name__)
            return self._finish_setup(
                db, mark_setup_complete, flask_app,
                library_created=True, scan_status=scan_status,
            ), None, None

        return None, ('bad_request', 'Unknown setup step.', 400, None), None

    @staticmethod
    def _finish_setup(db, mark_setup_complete, flask_app, *, library_created=False, scan_status=None):
        from oneirodex.utils.event_logging import log_system_event

        try:
            from oneirodex.init_data import (
                initialize_allowed_file_types, initialize_default_settings,
                initialize_discovery_sections, initialize_library_folders,
                insert_default_scanning_filters,
            )

            # Supply the config and task owner directly. The seed helpers keep
            # their Flask-context defaults for legacy callers, but native setup
            # stays in FastAPI with request-local DB state only.
            initialize_library_folders(config=flask_app.config, app=flask_app)
            initialize_discovery_sections()
            insert_default_scanning_filters()
            initialize_default_settings()
            initialize_allowed_file_types()
            mark_setup_complete()
        except Exception as exc:  # noqa: BLE001 — no private exception details in response
            db.session.rollback()
            flask_app.logger.error('Setup finalization failed: %s', type(exc).__name__)
            return {
                '_error': ('internal', 'Setup could not be completed. Try again or check the server log.', 500, None)
            }
        log_system_event(
            'Setup completed', event_type='setup', event_level='information', audit_user='system',
        )
        message = 'Setup is ready. You can add a library at any time from Libraries & scans.'
        if library_created:
            message = (
                'Your first library is ready and its initial scan has started or queued.'
                if scan_status in ('started', 'queued')
                else 'Your first library is ready. Start its first scan from Libraries & scans.'
            )
        return {'complete': True, 'message': message, 'next_url': '/libraries'}


def create_setup_transition_router(
    flask_app,
    *,
    find_user,
    find_token,
    commit_token_touch,
    load_user_id=None,
    login_manager=None,
    data_access=None,
    database_scope=None,
):
    router = APIRouter()
    data = data_access or SetupTransitionData()

    async def submit_setup_form(request: Request, path: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            session_data = _session_data(request, flask_app.config)
            try:
                form = await request.form()
            except Exception:  # noqa: BLE001 — malformed forms are safe client errors
                response = PlainTextResponse('Invalid setup form.', status_code=400)
                _setup_form_headers(response, flask_app)
                return response

            if flask_app.config.get('WTF_CSRF_ENABLED', True):
                from oneirodex.runtime_native.session_compat import (
                    CsrfTokenError, validate_csrf_token,
                )

                field_name = str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
                token = (
                    request.headers.get('X-CSRFToken')
                    or request.headers.get('X-CSRF-Token')
                    or form.get(field_name)
                )
                try:
                    validate_csrf_token(
                        token,
                        session_data,
                        flask_app.config.get('WTF_CSRF_SECRET_KEY')
                        or flask_app.config.get('SECRET_KEY'),
                        field_name=field_name,
                        time_limit=flask_app.config.get('WTF_CSRF_TIME_LIMIT', 3600),
                    )
                except CsrfTokenError as exc:
                    from oneirodex.runtime_native.csrf_compat import csrf_html_error_response

                    response = csrf_html_error_response(str(exc))
                    _setup_form_headers(response, flask_app)
                    return response

            auth = request_auth_context(
                request, flask_app.config, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
                allow_bearer=False,
            )
            body, return_to, parse_error = _setup_form_payload(path, form)
            if parse_error:
                _setup_form_flash(auth.session_data, 'error', parse_error)
                response = RedirectResponse(return_to, status_code=302)
                _setup_form_session_cookie(response, flask_app, auth)
                _setup_form_headers(response, flask_app)
                return response

            step = body['step']
            current_step = data.current_step()
            if current_step != step:
                _setup_form_flash(
                    auth.session_data, 'warning',
                    'This setup step is no longer current. Reload setup to continue.',
                )
                response = RedirectResponse('/setup', status_code=302)
            elif step > 1 and (auth.user is None or _role(auth.user) != 'admin'):
                _setup_form_flash(
                    auth.session_data, 'warning',
                    'Sign in with the administrator account you just created to finish setup.',
                )
                from urllib.parse import urlencode

                response = RedirectResponse(
                    '/login?' + urlencode({'next': request.url.path}), status_code=302,
                )
            else:
                try:
                    result, failure, new_admin = data.transition(
                        body, flask_app, database_scope=database_scope,
                    )
                except Exception as exc:  # noqa: BLE001 — do not expose transition details
                    flask_app.logger.error('Setup form transition failed: %s', type(exc).__name__)
                    result, failure, new_admin = None, (
                        'internal', 'Setup could not be completed.', 500, None,
                    ), None

                if new_admin is not None:
                    from oneirodex.runtime_native.auth_resolver import session_identifier
                    from oneirodex.utils.trusted_proxy import trusted_forwarded_for

                    auth.session_data['_user_id'] = str(new_admin.get_id())
                    auth.session_data['_fresh'] = True
                    auth.session_data['_id'] = session_identifier(
                        request.client.host if request.client else None,
                        request.headers.get('user-agent'),
                        trusted_forwarded_for(request, flask_app.config),
                    )

                if failure:
                    _setup_form_flash(auth.session_data, 'error', failure[1])
                    detail = failure[3]
                    if isinstance(detail, dict):
                        for errors in detail.values():
                            for message in errors:
                                _setup_form_flash(auth.session_data, 'error', str(message))
                    response = RedirectResponse(return_to, status_code=302)
                elif result and '_error' in result:
                    _setup_form_flash(auth.session_data, 'error', result['_error'][1])
                    response = RedirectResponse(return_to, status_code=302)
                else:
                    category, message = _setup_form_success(step, body, result or {})
                    _setup_form_flash(auth.session_data, category, message)
                    target = (result or {}).get('next_url') or return_to
                    response = RedirectResponse(target, status_code=302)

            _setup_form_session_cookie(response, flask_app, auth)
            _setup_form_headers(response, flask_app)
            return response

    def form_handler(path):
        async def submit(request: Request):
            return await submit_setup_form(request, path)

        return submit

    for path in (
        '/setup/submit', '/setup/smtp', '/setup/features', '/setup/igdb',
        '/setup/integrations', '/setup/library',
    ):
        router.add_api_route(
            path, form_handler(path), methods=['POST'], include_in_schema=False,
        )

    @router.post('/api/setup/step')
    async def submit_setup_step(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from oneirodex.runtime_native.csrf_compat import csrf_error_response

            session_data = _session_data(request, flask_app.config)
            response = csrf_error_response(request, session_data, flask_app.config)
            auth = None
            if response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user,
                    find_token=find_token, commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                    allow_bearer=False,
                )
                body, error = await _validated_body(request)
                if error:
                    response = error
                else:
                    current_step = data.current_step()
                    if body['step'] != current_step:
                        response = _error(
                            'This setup step is no longer current. Reload setup to continue.',
                            'conflict', 409,
                        )
                    elif body['step'] > 1 and (
                        auth.user is None or _role(auth.user) != 'admin'
                    ):
                        response = _error(
                            'Sign in with the administrator account created during setup.',
                            'unauthorized', 401,
                        )
                    else:
                        try:
                            result, failure, new_admin = data.transition(
                                body, flask_app, database_scope=database_scope,
                            )
                        except Exception as exc:  # noqa: BLE001
                            flask_app.logger.error('Setup transition failed: %s', type(exc).__name__)
                            result, failure, new_admin = None, (
                                'internal', 'Setup could not be completed.', 500, None,
                            ), None
                        if failure:
                            code, message, status, detail = failure
                            response = _error(message, code, status, detail=detail)
                        else:
                            if new_admin is not None:
                                from oneirodex.runtime_native.auth_resolver import session_identifier
                                from oneirodex.utils.trusted_proxy import trusted_forwarded_for

                                auth.session_data['_user_id'] = str(new_admin.get_id())
                                auth.session_data['_fresh'] = True
                                auth.session_data['_id'] = session_identifier(
                                    request.client.host if request.client else None,
                                    request.headers.get('user-agent'),
                                    trusted_forwarded_for(request, flask_app.config),
                                )
                            if result and '_error' in result:
                                code, message, status, detail = result['_error']
                                response = _error(message, code, status, detail=detail)
                            else:
                                response = _ok(result)
            if auth is not None and auth.should_set_session_cookie:
                from oneirodex.runtime_native.oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            response.headers['Cache-Control'] = 'no-store'
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def _setup_form_payload(path, form):
    """Translate legacy HTML form names into the shared validated step body."""
    from oneirodex.schemas.setup import SetupTransitionBody

    step_by_path = {
        '/setup/submit': 1, '/setup/smtp': 2, '/setup/features': 3,
        '/setup/igdb': 4, '/setup/integrations': 5, '/setup/library': 6,
    }
    step = step_by_path[path]
    body = {'step': step}
    truthy = lambda value: str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if step == 1:
        body.update(
            username=form.get('username', ''), email=form.get('email', ''),
            password=form.get('password', ''),
            confirm_password=form.get('confirm_password', ''),
        )
    elif step == 2:
        body.update(
            skip='skip_smtp' in form,
            smtp_server=form.get('smtp_server', ''),
            smtp_port=form.get('smtp_port', '587'),
            smtp_username=form.get('smtp_username', ''),
            smtp_password=form.get('smtp_password', ''),
            smtp_use_tls=truthy(form.get('smtp_use_tls')),
            smtp_default_sender=form.get('smtp_default_sender', ''),
            smtp_enabled=truthy(form.get('smtp_enabled')),
        )
    elif step == 3:
        for key in (
            'enable_game_updates', 'enable_game_extras', 'attract_mode_enabled',
            'enable_arr_module', 'enable_ai_assist', 'enable_malware_scan',
        ):
            body[key] = key in form
    elif step == 4:
        body.update(
            skip='skip_igdb' in form,
            igdb_client_id=form.get('igdb_client_id', ''),
            igdb_client_secret=form.get('igdb_client_secret', ''),
        )
    elif step == 5:
        body.update(
            skip=form.get('skip_integrations') == '1',
            configure_oidc=form.get('configure_oidc') == 'on',
            enable_hltb_integration=form.get('enable_hltb_integration') == 'on',
        )
        for key in (
            'steam_web_api_key', 'steamgriddb_api_key', 'giantbomb_api_key',
            'mobygames_api_key', 'thegamesdb_api_key', 'oidc_issuer_url',
            'oidc_client_id', 'oidc_client_secret', 'oidc_redirect_uri',
            'oidc_scopes', 'oidc_role_claim',
        ):
            body[key] = form.get(key, '')
        for key in (
            'steam_web_api_key', 'steamgriddb_api_key', 'giantbomb_api_key',
            'mobygames_api_key', 'thegamesdb_api_key',
        ):
            if form.get('configure_' + key) != 'on':
                body[key] = ''
    else:
        body.update(
            skip=form.get('skip_library') == 'on',
            library_name=form.get('name', ''),
            platform=form.get('platform', ''),
            folder_path=form.get('folder_path', ''),
            scan_mode=form.get('scan_mode') or 'folders',
            scan_depth=form.get('scan_depth') or '1',
        )

    try:
        validated = SetupTransitionBody.model_validate(body).model_dump()
    except ValidationError:
        target = '/setup' if path == '/setup/submit' else path
        return None, target, 'Please check the setup form and try again.'
    target = path if path != '/setup/submit' else '/setup'
    return validated, target, None


def _setup_form_success(step, body, result):
    if step == 1:
        return 'success', 'Admin account created successfully! Please configure your SMTP settings.'
    if step == 2:
        return (
            ('info', 'SMTP setup skipped. Choose which features to keep enabled.')
            if body['skip'] else
            ('success', 'SMTP settings saved. Choose which features to keep enabled.')
        )
    if step == 3:
        return 'success', 'Feature preferences saved. Configure IGDB next.'
    if step == 4:
        return (
            ('info', 'IGDB skipped. Choose any additional API connections, or continue without them.')
            if body['skip'] else
            ('success', 'IGDB settings saved. Choose any additional API connections, or continue without them.')
        )
    if step == 5:
        return (
            ('info', 'Optional API setup skipped. You can continue without API credentials.')
            if body['skip'] else
            ('success', 'API choices saved. Add your first library next, or skip it for now.')
        )
    if result.get('complete') and result.get('next_url') == '/libraries':
        message = result.get('message') or 'Setup is ready.'
        return ('success', message) if body['skip'] else (
            ('success', message) if 'started or queued' in message else ('warning', message)
        )
    return 'success', result.get('message') or 'Setup step saved.'


def _setup_form_flash(session_data, category, message):
    flashes = list(session_data.get('_flashes') or [])
    flashes.append((category, message))
    session_data['_flashes'] = flashes


def _setup_form_session_cookie(response, flask_app, auth):
    from oneirodex.runtime_native.oidc_status import _set_session_cookie

    _set_session_cookie(response, flask_app, auth)


def _setup_form_headers(response, flask_app):
    from oneirodex.utils.security_headers import security_header_values

    response.headers['Cache-Control'] = 'no-store'
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)


def mount_setup_transition_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_setup_transition_router(flask_app, **kwargs))
    return app


def _commit_step(db, set_step, next_step, flask_app, label):
    try:
        db.session.commit()
        set_step(next_step)
        return True
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        flask_app.logger.error('%s failed: %s', label, type(exc).__name__)
        return False


def _setup_account_errors(body):
    errors = {}
    username = body['username']
    if not username.strip():
        errors['username'] = ['This field is required.']
    elif not re.match(r'^[\w.]+$', username):
        errors['username'] = ['Username can only contain letters, numbers, dots and underscores']
    elif len(username) < 3 or len(username) > 64:
        errors['username'] = ['Field must be between 3 and 64 characters long.']
    try:
        from email_validator import EmailNotValidError, validate_email

        validate_email(body['email'], check_deliverability=False)
    except EmailNotValidError:
        errors['email'] = ['Invalid email address.']
    if not body['password'].strip():
        errors['password'] = ['This field is required.']
    elif len(body['password']) < 8:
        errors['password'] = ['Field must be at least 8 characters long.']
    if body['password'] != body['confirm_password']:
        errors['confirm_password'] = ['Passwords must match.']
    return errors


def _igdb_setup_errors(body):
    errors = {}
    for key, label in (('igdb_client_id', 'Client ID'), ('igdb_client_secret', 'Client Secret')):
        value = body[key]
        if not value:
            errors[key] = ['This field is required.']
        elif len(value) < 20 or len(value) > 50:
            errors[key] = [f'{label} must be between 20 and 50 characters']
    return errors


async def _validated_body(request):
    from oneirodex.schemas.setup import SetupTransitionBody

    try:
        body = SetupTransitionBody.model_validate_json(await request.body())
        return body.model_dump(), None
    except ValidationError as exc:
        from oneirodex.utils.validation import format_validation_errors

        return None, _error(
            'Invalid setup transition.', 'unprocessable', 422,
            detail=format_validation_errors(exc),
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        return None, _error('Invalid JSON body.', 'bad_request', 400)


def _session_data(request, config):
    from oneirodex.runtime_native.password_reset_confirm import _session_data as load_session

    return load_session(request, config)


def _role(user):
    from oneirodex.utils.role_catalog import normalize_role

    return normalize_role(getattr(user, 'role', None) or '')


def _ok(payload):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload))


def _error(message, code, status, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, detail=detail)
    return JSONResponse(payload, status_code=resolved)
