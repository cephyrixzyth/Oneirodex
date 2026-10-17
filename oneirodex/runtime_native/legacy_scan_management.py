"""FastAPI compatibility endpoint for the old scan-management form actions."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import RedirectResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class LegacyScanManagementData:
    """Native adapter for the legacy scan-management form actions."""

    def library(self, library_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library

        return db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()

    def add_filter(self, pattern, case_sensitive):
        from oneirodex.runtime_native.admin_scan_filters import AdminScanFiltersData

        return AdminScanFiltersData().add(pattern, case_sensitive)

    def delete_filter(self, filter_id):
        from oneirodex.runtime_native.admin_scan_filters import AdminScanFiltersData

        return AdminScanFiltersData().delete(filter_id)

    def delete_unmatched(self, *, only_unmatched):
        from sqlalchemy import delete, func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder

        statement = delete(UnmatchedFolder)
        if only_unmatched:
            criterion = UnmatchedFolder.status == 'Unmatched'
            count = db.session.execute(select(func.count(UnmatchedFolder.id)).where(criterion)).scalar() or 0
            statement = statement.where(criterion)
        else:
            count = db.session.execute(select(func.count(UnmatchedFolder.id))).scalar() or 0
        result = db.session.execute(statement)
        from oneirodex.utils.event_logging import log_system_event
        log_system_event(
            event_text=(
                f'Deleted {count} unmatched folders with status Unmatched'
                if only_unmatched else f'Deleted all {count} unmatched folders'
            ),
            event_type='delete_operation',
            event_level='information' if only_unmatched else 'warning',
        )
        db.session.commit()
        return int(result.rowcount or 0)

    def resolve_path(self, app, folder, library_root):
        from oneirodex.utils.library_roots import resolve_scan_path

        return resolve_scan_path(folder, library_root, app)

    def allowed_bases(self, app):
        from oneirodex.utils.security import get_allowed_base_directories

        return get_allowed_base_directories(app)

    def safe_path(self, path, bases):
        from oneirodex.utils.security import is_safe_path

        return is_safe_path(path, bases)

    def readable(self, path):
        import os

        return os.path.exists(path) and os.access(path, os.R_OK)

    def scan_mode(self, path, requested):
        from oneirodex.utils.services.scan_orchestration import resolve_scan_mode_for_path

        return resolve_scan_mode_for_path(path, requested)

    def busy(self):
        from oneirodex.utils.scan_queue import is_scan_busy

        return is_scan_busy()

    def start_scan(self, *, library, folder, options, app, database_scope=None):
        from oneirodex.utils.scan_queue import start_or_queue_scan

        return start_or_queue_scan(
            folder_path=folder, library_uuid=library.uuid,
            scan_mode=options['scan_mode'], remove_missing=options['remove_missing'],
            download_missing_images=options['download_missing_images'],
            force_updates_extras_scan=options['force_updates_extras'],
            fetch_hltb=options['fetch_hltb'], force_hltb_refetch=options['force_hltb_refetch'],
            schedule=options.get('schedule'), schedule_fields=options.get('schedule_fields'),
            queue_policy=options['queue_policy'], allow_force=options['allow_force'], app=app,
            database_scope=database_scope,
        )

    def scan_patterns(self):
        from oneirodex.utils.functions import load_scanning_filter_patterns

        return load_scanning_filter_patterns()

    def list_folders(self, path, insensitive, sensitive, library):
        from oneirodex.utils.gamenames import get_game_names_from_folder
        from oneirodex.utils.functions import load_skip_dir_patterns, load_skip_dir_regex_patterns

        return get_game_names_from_folder(
            path, insensitive, sensitive,
            scan_depth=getattr(library, 'scan_depth', 1) or 1,
            skip_dir_patterns=load_skip_dir_patterns(),
            skip_dir_regexes=load_skip_dir_regex_patterns(),
        )

    def list_files(self, path, insensitive, sensitive):
        from oneirodex.utils.gamenames import get_game_names_from_files
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import AllowedFileType

        extensions = [row.value for row in db.session.execute(select(AllowedFileType)).scalars().all()]
        return (get_game_names_from_files(path, extensions, insensitive, sensitive), bool(extensions))

    def metadata_write_permissions(self, path):
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.local_metadata import check_library_write_permissions

        settings = global_settings_row()
        if settings and settings.write_local_metadata:
            return check_library_write_permissions(path)
        return True, []


def create_legacy_scan_management_router(
    app, *, find_user: Callable[[int], Any | None], find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None], load_user_id=None, login_manager=None,
    data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or LegacyScanManagementData()

    @router.post('/scan_management')
    async def scan_management(request: Request):
        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        from oneirodex.utils.role_catalog import normalize_role

        scope = database_scope(app) if database_scope else nullcontext()
        with scope:
            limit = min(int(app.config.get('MAX_CONTENT_LENGTH') or 128 * 1024), 128 * 1024)
            content_length = request.headers.get('content-length')
            try:
                too_large = content_length is not None and int(content_length) > limit
            except (TypeError, ValueError):
                too_large = True
            chunks = []
            size = 0
            if not too_large:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        too_large = True
                        chunks = []
                        break
                    chunks.append(chunk)
            if too_large:
                from starlette.responses import Response

                return Response(status_code=413)
            replay = Request(request.scope, receive=_body_receive(b''.join(chunks)))
            form = await replay.form(max_files=0, max_fields=48, max_part_size=32 * 1024)
            try:
                cookie_name = str(app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name), app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                response = csrf_error_response(
                    request, session_data, app.config,
                    token=str(form.get(str(app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')) or ''),
                )
                auth = None
                if response is None:
                    auth = request_auth_context(
                        request, app.config, find_user=find_user, find_token=find_token,
                        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                        login_manager=login_manager,
                    )
                    if auth.user is None:
                        response = _login_redirect(app, request, login_manager, auth)
                    elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                        response = _login_redirect(
                            app, request, login_manager, auth,
                            message='You must be an admin to access this page.',
                            category='danger', include_next=False,
                        )
                    elif auth.token is not None and not auth.has_scope('admin'):
                        from oneirodex.utils.api_contract import api_error_payload
                        from starlette.responses import JSONResponse

                        payload, status = api_error_payload(
                            'This token does not have the admin scope', code='forbidden',
                        )
                        response = JSONResponse(payload, status_code=status)

                if response is None:
                    response = await _apply_action(
                        request, form, app, data, auth,
                        database_scope=database_scope,
                    )
                if auth is not None and auth.should_set_session_cookie:
                    _set_session_cookie(response, app, auth)
                from oneirodex.utils.security_headers import security_header_values
                for key, value in security_header_values(app.config).items():
                    response.headers.setdefault(key, value)
                return response
            finally:
                await form.close()

    return router


async def _apply_action(request, form, app, data, auth, *, database_scope=None):
    from starlette.responses import JSONResponse

    action = str(form.get('submit') or '')
    flashes = auth.session_data.setdefault('_flashes', [])
    library_uuid = str(form.get('library_uuid') or '').strip()
    if action == 'AddReleaseGroup':
        pattern = str(form.get('filter_pattern') or '').strip()
        case_sensitive = str(form.get('case_sensitive') or 'no')
        if not pattern or len(pattern) > 200 or case_sensitive not in {'yes', 'no'}:
            flashes.append(('danger', 'Enter a valid scanning filter and case-sensitivity option.'))
        else:
            try:
                data.add_filter(pattern, case_sensitive == 'yes')
                flashes.append(('success', 'New scanning filter added.'))
            except Exception:
                flashes.append(('danger', 'Could not add scanning filter.'))
        location = '/scan_management?active_tab=scan_filters'
    elif action == 'DeleteReleaseGroup':
        raw_id = str(form.get('filter_id') or '')
        try:
            deleted = data.delete_filter(int(raw_id)) if raw_id.isdigit() else False
        except Exception:
            from oneirodex.runtime_native.db_session import native_db as db
            db.session.rollback()
            deleted = False
        flashes.append(('success' if deleted else 'error',
                        'Scanning filter removed.' if deleted else 'Filter not found or could not be removed.'))
        location = '/scan_management?active_tab=scan_filters'
    elif action in {'DeleteAllUnmatched', 'DeleteOnlyUnmatched'}:
        try:
            count = data.delete_unmatched(only_unmatched=action == 'DeleteOnlyUnmatched')
            message = ('All unmatched folders cleared successfully.' if action == 'DeleteAllUnmatched'
                       else 'Unmatched folders with status "Unmatched" cleared successfully.')
            flashes.append(('success', message))
        except Exception:
            from oneirodex.runtime_native.db_session import native_db as db
            db.session.rollback()
            flashes.append(('error', 'Database error occurred while clearing folders. Please try again.'))
        auth.session_data['active_tab'] = 'unmatched'
        location = '/scan_management?active_tab=unmatched'
    elif action in {'AutoScan', 'ManualScan'}:
        location = await _scan_action(
            form, app, data, auth, action, library_uuid,
            database_scope=database_scope,
        )
    else:
        flashes.append(('error', 'Unrecognized action.'))
        location = '/scan_management'
    response = RedirectResponse(location, status_code=302)
    _set_session_cookie(response, app, auth)
    return response


async def _scan_action(form, app, data, auth, action, library_uuid, *, database_scope=None):
    from oneirodex.utils.scan_queue import parse_force_parallel, parse_queue_policy

    manual = action == 'ManualScan'
    tab = 'manual' if manual else 'auto'
    redirect = f'/scan_management?active_tab={tab}'
    flashes = auth.session_data.setdefault('_flashes', [])
    library = data.library(library_uuid) if library_uuid else None
    if library is None:
        flashes.append(('danger', 'Please select a valid library.'))
        return redirect
    folder = str(form.get('folder_path') or '').strip()
    root = str(form.get('library_root') or '').strip() or None
    resolved, root_error = data.resolve_path(app, folder, root)
    if root_error:
        flashes.append(('danger', f'Service configuration error: {root_error}'))
        return redirect
    bases = data.allowed_bases(app)
    if not bases:
        flashes.append(('danger', 'Service configuration error: No allowed base directories configured.'))
        return redirect
    safe, reason = data.safe_path(resolved, bases)
    if not safe:
        flashes.append(('danger', f'Access denied: {reason}'))
        return redirect
    if not data.readable(resolved):
        flashes.append(('danger', 'Folder does not exist or cannot be accessed.'))
        return f'{redirect}&library_uuid={library_uuid}'
    requested_mode = str(form.get('scan_mode') or 'auto')
    scan_mode = data.scan_mode(resolved, requested_mode)
    options = {
        'scan_mode': scan_mode,
        'remove_missing': not manual and _flag(form.get('remove_missing')),
        'download_missing_images': not manual and _flag(form.get('download_missing_images')),
        'force_updates_extras': _flag(form.get('force_updates_extras_scan')),
        'fetch_hltb': _flag(form.get('fetch_hltb')),
        'force_hltb_refetch': _flag(form.get('force_hltb_refetch')),
        'schedule': str(form.get('schedule') or '').strip() or None,
        'queue_policy': parse_queue_policy(
            form.get('queue_policy'), force_parallel=form.get('force_parallel'),
        ),
        'allow_force': getattr(auth.user, 'role', None) == 'admin',
    }
    if not manual:
        from oneirodex.utils.scan_queue import normalize_schedule_fields

        options['schedule_fields'] = normalize_schedule_fields(
            options['schedule'],
            interval_value=form.get('schedule_interval_value'),
            interval_unit=form.get('schedule_interval_unit'),
            cron_expr=form.get('schedule_cron'),
        )
        if options['schedule_fields'].get('error'):
            flashes.append(('danger', options['schedule_fields']['error']))
            return redirect
    if not manual or data.busy():
        try:
            result = data.start_scan(
                library=library, folder=resolved, options=options, app=app,
                database_scope=database_scope,
            )
        except Exception:
            result = {'status': 'rejected', 'message': 'Scan request could not be queued.'}
        category = 'info' if result.get('status') in {'started', 'queued'} else 'danger'
        if result.get('status') == 'started' and parse_force_parallel(form.get('force_parallel')):
            category = 'warning'
        flashes.append((category, result.get('message') or 'Scan request was rejected.'))
        auth.session_data['active_tab'] = tab
        return f'{redirect}&library_uuid={library_uuid}'

    if auth.session_data.get('game_paths') is not None:
        auth.session_data.pop('game_paths', None)
    permission_ok, permission_errors = data.metadata_write_permissions(resolved)
    if not permission_ok:
        auth.session_data['permission_check_failed'] = True
        auth.session_data['permission_errors'] = permission_errors
        auth.session_data['permission_check_path'] = resolved
        flashes.append(('danger', 'Write permission check failed. Please review the permission errors.'))
        return '/scan_management?active_tab=manual&show_permissions_modal=true'
    insensitive, sensitive = data.scan_patterns()
    if scan_mode == 'folders':
        games = data.list_folders(resolved, insensitive, sensitive, library)
    else:
        games, has_extensions = data.list_files(resolved, insensitive, sensitive)
        if not has_extensions:
            flashes.append(('danger', 'No allowed file types defined in the database.'))
            return redirect
    auth.session_data['selected_library_uuid'] = library_uuid
    auth.session_data['game_paths'] = {row['name']: row['full_path'] for row in games}
    auth.session_data['force_updates_extras_scan'] = options['force_updates_extras']
    auth.session_data['fetch_hltb'] = options['fetch_hltb']
    auth.session_data['force_hltb_refetch'] = options['force_hltb_refetch']
    flashes.append(('info', 'Manual scan processed for folder: ' + resolved))
    auth.session_data['active_tab'] = 'manual'
    return f'{redirect}&library_uuid={library_uuid}'


def _flag(value):
    # WTForms BooleanField treats only False, 'false', and '' as unchecked.
    # In particular its default checked value is 'y'; retain that meaning for
    # direct compatibility posts from the v1.1.8 form.
    return value not in (None, False, 'false', '')


def _body_receive(raw):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        sent = True
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    return receive


def mount_legacy_scan_management_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_legacy_scan_management_router(flask_app, **kwargs))
    return app
