"""Native adapter-backed ``manual_identify/list`` library-tools endpoint.

Queue, permission, database, and filesystem behavior is isolated behind
``ManualIdentifyListData`` so tests can exercise the contract without touching
the real library or launching a scan.
"""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from oneirodex.schemas.library_tools import ManualScanListBody
from oneirodex.utils.validation import format_validation_errors

from .library_tools import _admin_redirect, _error, _finish, _login_redirect, _ok
from .request_auth import request_auth_context


class ManualIdentifyListData:
    """Production adapter for effects that the route must not perform itself."""

    def library(self, app, library_uuid):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library
        return db.session.get(Library, library_uuid)

    def resolve_scan_path(self, app, folder, root):
        from oneirodex.utils.library_roots import resolve_scan_path
        return resolve_scan_path(folder, root, app)

    def safe_path(self, app, path):
        from oneirodex.utils.security import get_allowed_base_directories, is_safe_path
        allowed = get_allowed_base_directories(app)
        return is_safe_path(path, allowed)

    def readable_directory(self, path):
        import os
        return os.path.isdir(path) and os.access(path, os.R_OK)

    def scan_mode(self, app, path, requested):
        from oneirodex.utils.services.scan_orchestration import resolve_scan_mode_for_path
        return resolve_scan_mode_for_path(path, requested)

    def is_scan_busy(self):
        from oneirodex.utils.scan_queue import is_scan_busy
        return is_scan_busy()

    def start_or_queue_scan(self, **kwargs):
        from oneirodex.utils.scan_queue import start_or_queue_scan
        return start_or_queue_scan(**kwargs)

    def write_local_metadata_enabled(self):
        from oneirodex.utils.global_settings import global_settings_row
        settings = global_settings_row()
        return bool(settings and settings.write_local_metadata)

    def check_library_write_permissions(self, path):
        from oneirodex.utils.local_metadata import check_library_write_permissions
        return check_library_write_permissions(path)

    def games_in_folder(self, app, path, library):
        from oneirodex.utils.functions import (
            load_scanning_filter_patterns, load_skip_dir_patterns,
            load_skip_dir_regex_patterns,
        )
        from oneirodex.utils.gamenames import get_game_names_from_folder
        insensitive, sensitive = load_scanning_filter_patterns()
        return get_game_names_from_folder(
            path, insensitive, sensitive,
            scan_depth=getattr(library, 'scan_depth', 1) or 1,
            skip_dir_patterns=load_skip_dir_patterns(),
            skip_dir_regexes=load_skip_dir_regex_patterns(),
        )

    def allowed_extensions(self, app):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import AllowedFileType
        return [row.value for row in db.session.execute(
            select(AllowedFileType).order_by(AllowedFileType.value.asc())
        ).scalars().all()]

    def games_in_files(self, app, path, extensions):
        from oneirodex.utils.functions import load_scanning_filter_patterns
        from oneirodex.utils.gamenames import get_game_names_from_files
        insensitive, sensitive = load_scanning_filter_patterns()
        return get_game_names_from_files(path, extensions, insensitive, sensitive)

    def write_preview_session(self, session_data, library, games, body):
        """Apply the legacy preview state to the mutable signed-session data."""
        session_data['selected_library_uuid'] = library.uuid
        session_data['game_paths'] = {row['name']: row['full_path'] for row in games}
        session_data['force_updates_extras_scan'] = body.force_updates_extras_scan
        session_data['fetch_hltb'] = body.fetch_hltb
        session_data['force_hltb_refetch'] = body.force_hltb_refetch


def create_manual_identify_list_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None, login_manager=None,
    data_access=None, database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    options = dict(
        flask_app=flask_app, data=data_access or ManualIdentifyListData(),
        find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager, database_scope=database_scope,
    )

    @router.post('/api/library_tools/manual_identify/list')
    async def manual_identify_list(request: Request):
        return await _run(request, **options)

    return router


def mount_manual_identify_list_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_manual_identify_list_router(flask_app, **kwargs))
    return app


async def _run(request, *, flask_app, data, find_user, find_token,
               commit_token_touch, load_user_id, login_manager, database_scope):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        response = None
        from .csrf_compat import csrf_error_response
        response = csrf_error_response(request, auth.session_data, flask_app.config)
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        if response is None:
            from oneirodex.utils.role_catalog import normalize_role
            if normalize_role(getattr(auth.user, 'role', None)) != 'admin':
                response = _admin_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('admin'):
                response = _error(403, 'forbidden', 'This token does not have the admin scope')
            else:
                try:
                    response = await _manual_identify_list(request, flask_app, data, auth)
                except Exception:
                    response = _error(500, 'internal', 'An error occurred while processing your request')
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie
            _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _manual_identify_list(request, app, data, auth):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        body = ManualScanListBody.model_validate(payload)
    except ValidationError as exc:
        return _error(422, 'unprocessable', 'Invalid request.', detail=format_validation_errors(exc))

    library = data.library(app, body.library_uuid)
    if not library:
        return _error(400, 'bad_request', 'Choose a valid library')
    folder_path, root_error = data.resolve_scan_path(app, body.folder or '', body.root or '')
    if root_error:
        return _error(400, 'bad_request', 'The selected scan location is unavailable')
    safe, _path_error = data.safe_path(app, folder_path)
    if not safe:
        return _error(403, 'forbidden', 'The selected folder is outside configured storage roots')
    if not data.readable_directory(folder_path):
        return _error(400, 'bad_request', 'The selected folder does not exist or cannot be read')

    mode = data.scan_mode(app, folder_path, body.scan_mode)
    if data.is_scan_busy():
        if body.queue_policy == 'inspect':
            return _ok({
                'action': 'conflict', 'message': 'Another scan is already running.',
                'read_only': True,
            }, headers={'Cache-Control': 'no-store'})
        result = data.start_or_queue_scan(
            folder_path=folder_path, library_uuid=library.uuid, scan_mode=mode,
            remove_missing=False, download_missing_images=False,
            force_updates_extras_scan=body.force_updates_extras_scan,
            fetch_hltb=body.fetch_hltb, force_hltb_refetch=body.force_hltb_refetch,
            schedule=None, queue_policy=body.queue_policy, allow_force=True,
            app=app,
        )
        if result.get('status') not in ('started', 'queued'):
            return _error(409, 'conflict', result.get('message') or 'Manual scan could not be queued')
        return _ok({
            'action': result['status'], 'message': result.get('message') or 'Manual scan queued.',
            'job_id': result.get('job_id'), 'position': result.get('position'),
            'read_only': False,
        }, headers={'Cache-Control': 'no-store'})

    if data.write_local_metadata_enabled():
        all_ok, failed_paths = data.check_library_write_permissions(folder_path)
        if not all_ok:
            return _error(
                422, 'unprocessable',
                'Review local metadata write permissions before identifying this folder.',
                detail={'failed_count': len(failed_paths)},
            )

    if mode == 'folders':
        games = data.games_in_folder(app, folder_path, library)
    else:
        extensions = data.allowed_extensions(app)
        if not extensions:
            return _error(422, 'unprocessable', 'No supported game file types are configured')
        games = data.games_in_files(app, folder_path, extensions)

    data.write_preview_session(auth.session_data, library, games, body)
    return _ok({
        'action': 'preview', 'library_uuid': library.uuid,
        'library_name': library.name, 'folder': __import__('os').path.normpath(folder_path),
        'scan_mode': mode, 'games': games, 'count': len(games), 'read_only': True,
    }, headers={'Cache-Control': 'no-store'})
