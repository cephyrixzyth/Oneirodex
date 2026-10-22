"""Native read-only subset of the legacy library-tools API.

Disk walks and parsing are exposed through ``LibraryToolsData`` so route tests
can use in-memory fakes and never touch the user's library.
"""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .request_auth import request_auth_context


class LibraryToolsData:
    """Adapters for database reads and filesystem/library inspection."""

    def allowed_bases(self, app):
        from oneirodex.utils.security import get_allowed_base_directories
        return get_allowed_base_directories(app)

    def library(self, app, library_uuid):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library
        return db.session.get(Library, library_uuid)

    def allowed_extensions(self, app):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import AllowedFileType
        return [row.value for row in db.session.execute(
            select(AllowedFileType).order_by(AllowedFileType.value.asc())
        ).scalars().all()]

    def resolve_scan_path(self, app, folder, root):
        from oneirodex.utils.library_roots import resolve_scan_path
        return resolve_scan_path(folder, root, app)

    def safe_path(self, app, path):
        from oneirodex.utils.security import is_safe_path
        return is_safe_path(path, self.allowed_bases(app))

    def readable_directory(self, path):
        import os
        return os.path.isdir(path) and os.access(path, os.R_OK)

    def scan_mode(self, app, path, requested):
        from oneirodex.utils.services.scan_orchestration import resolve_scan_mode_for_path
        return resolve_scan_mode_for_path(path, requested)

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

    def games_in_files(self, app, path, extensions):
        from oneirodex.utils.functions import load_scanning_filter_patterns
        from oneirodex.utils.gamenames import get_game_names_from_files
        insensitive, sensitive = load_scanning_filter_patterns()
        return get_game_names_from_files(path, extensions, insensitive, sensitive)

    def propose_leaf_libraries(self, root):
        from oneirodex.utils.propose_leaf_libraries import propose_leaf_libraries
        return propose_leaf_libraries(root)

    def import_preview(self, text_or_data, *, csv_format, allowed_bases):
        from oneirodex.utils.import_leaf_libraries import preview_from_csv, preview_from_json
        if csv_format:
            return preview_from_csv(text_or_data, allowed_bases=allowed_bases)
        return preview_from_json(text_or_data, allowed_bases=allowed_bases)

    def libraries_and_games(self, app):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Library
        libraries = db.session.execute(select(Library)).scalars().all()
        return [(library, db.session.execute(
            select(Game).filter_by(library_uuid=library.uuid)
        ).scalars().all()) for library in libraries]

    def proposal_path(self, path):
        from oneirodex.utils.match_proposal import resolve_proposal_path
        return resolve_proposal_path(path)

    def read_proposal(self, path):
        import json
        try:
            with open(path, encoding='utf-8') as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return (payload or {}).get('proposal')

    def iter_game_folders(self, root):
        from oneirodex.utils.library_doctor import iter_game_folders
        return iter_game_folders(root)

    def doctor_dry_run(self, roots, *, template, limit):
        from oneirodex.utils.library_doctor import doctor_dry_run
        return doctor_dry_run(roots, template=template, limit=limit)


def create_library_tools_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None, login_manager=None,
    data_access=None, database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    opts = dict(
        flask_app=flask_app, data=data_access or LibraryToolsData(),
        find_user=find_user, find_token=find_token, commit_token_touch=commit_token_touch,
        load_user_id=load_user_id, login_manager=login_manager,
        database_scope=database_scope,
    )

    @router.api_route('/api/library_tools/manual_identify/preview', methods=['GET', 'HEAD'])
    async def manual_identify_preview(request: Request):
        return await _run(request, **opts, handler=_manual_preview)

    @router.api_route('/api/library_tools/propose_leaf_libraries', methods=['GET', 'POST', 'HEAD'])
    async def propose_leaf_libraries(request: Request):
        return await _run(request, **opts, handler=_propose_leaf)

    @router.api_route('/api/library_tools/import_leaf_libraries/preview', methods=['POST'])
    async def import_leaf_libraries_preview(request: Request):
        return await _run(request, **opts, handler=_import_preview)

    @router.api_route('/api/library_tools/proposals', methods=['GET', 'HEAD'])
    async def proposals(request: Request):
        return await _run(request, **opts, handler=_proposals)

    @router.api_route('/api/library_tools/proposals/scan_roots', methods=['POST'])
    async def scan_proposals(request: Request):
        return await _run(request, **opts, handler=_scan_proposals)

    @router.options('/api/library_tools/proposals/scan_roots')
    async def scan_proposals_options():
        # Match Flask's automatically generated, unauthenticated OPTIONS route.
        from starlette.responses import HTMLResponse

        return HTMLResponse('', status_code=200, headers={'Allow': 'OPTIONS, POST'})

    @router.api_route('/api/library_tools/doctor/dry_run', methods=['POST'])
    async def doctor_dry_run(request: Request):
        return await _run(request, **opts, handler=_doctor_dry_run)

    return router


def mount_library_tools_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_library_tools_router(flask_app, **kwargs))
    return app


async def _run(request, *, flask_app, data, find_user, find_token,
               commit_token_touch, load_user_id, login_manager, database_scope, handler):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        response = None
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            from .csrf_compat import csrf_error_response
            response = csrf_error_response(request, auth.session_data, flask_app.config)
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        if response is None:
            from oneirodex.utils.role_catalog import normalize_role
            role = normalize_role(getattr(auth.user, 'role', None))
            if role != 'admin':
                response = _admin_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('admin'):
                response = _error(403, 'forbidden', 'This token does not have the admin scope')
            else:
                try:
                    response = await handler(request, flask_app, data)
                except Exception:
                    response = _error(500, 'internal', 'An error occurred while processing your request')
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie
            _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _manual_preview(request, app, data):
    import os
    library_uuid = (request.query_params.get('library_uuid') or '').strip()
    library = data.library(app, library_uuid) if library_uuid else None
    if not library:
        return _error(400, 'bad_request', 'Choose a valid library')
    folder, error = data.resolve_scan_path(
        app, request.query_params.get('folder') or '', request.query_params.get('root') or '',
    )
    if error:
        return _error(400, 'bad_request', 'The selected scan location is unavailable')
    safe, path_error = data.safe_path(app, folder)
    if not safe:
        return _error(403, 'forbidden', path_error or 'Unsafe path')
    if not data.readable_directory(folder):
        return _error(400, 'bad_request', 'The selected folder does not exist or cannot be read')
    mode = data.scan_mode(app, folder, request.query_params.get('scan_mode') or 'auto')
    if mode == 'folders':
        games = data.games_in_folder(app, folder, library)
    else:
        extensions = data.allowed_extensions(app)
        if not extensions:
            return _error(422, 'unprocessable', 'No supported game file types are configured')
        games = data.games_in_files(app, folder, extensions)
    return _ok({
        'library_uuid': library.uuid, 'library_name': library.name,
        'folder': os.path.normpath(folder), 'scan_mode': mode,
        'games': games, 'count': len(games), 'read_only': True,
    }, headers={'Cache-Control': 'no-store'})


async def _propose_leaf(request, app, data):
    import os
    body = {}
    if request.method == 'POST':
        try:
            body = await request.json()
        except Exception:
            body = {}
    root = str(body.get('root') or body.get('path') or request.query_params.get('root')
               or request.query_params.get('path') or '').strip() if isinstance(body, dict) else ''
    if not root:
        return _error(400, 'bad_request', 'root path required')
    safe, error = data.safe_path(app, root)
    if not safe:
        return _error(403, 'forbidden', error or 'Unsafe path')
    if not data.readable_directory(root):
        return _error(400, 'bad_request', 'root is not a directory')
    candidates = data.propose_leaf_libraries(root)
    return _ok({'root': os.path.normpath(root), 'candidates': candidates,
                'count': len(candidates), 'auto_create': False})


async def _import_preview(request, app, data):
    from starlette.datastructures import UploadFile
    bases = data.allowed_bases(app)
    content_type = request.headers.get('content-type', '')
    if 'multipart/form-data' in content_type:
        form = await request.form()
        upload = form.get('file')
        if isinstance(upload, UploadFile) and upload.filename:
            filename = upload.filename.lower()
            raw = await upload.read()
            if len(raw) > int(app.config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024):
                await form.close()
                return _error(413, 'bad_request', 'Upload is too large', auto_create=False)
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                await form.close()
                return _error(400, 'bad_request', 'File must be UTF-8 text', auto_create=False)
            try:
                result = data.import_preview(
                    text, csv_format=filename.endswith('.csv') or str(form.get('format') or '').lower() == 'csv',
                    allowed_bases=bases,
                )
            finally:
                await form.close()
            return JSONResponse(result)
        csv_text = form.get('csv') or form.get('text')
        if csv_text:
            try:
                result = data.import_preview(csv_text, csv_format=True, allowed_bases=bases)
            finally:
                await form.close()
            return JSONResponse(result)
        await form.close()
        return _error(400, 'bad_request', 'JSON body or file upload required', auto_create=False)
    try:
        payload = await request.json()
    except Exception:
        return _error(400, 'bad_request', 'JSON body or file upload required', auto_create=False)
    return JSONResponse(data.import_preview(payload, csv_format=False, allowed_bases=bases))


async def _proposals(_request, app, data):
    found = []
    for library, games in data.libraries_and_games(app):
        for game in games:
            path = getattr(game, 'full_disk_path', None) or ''
            safe, _ = data.safe_path(app, path)
            if not safe:
                continue
            proposal_path = data.proposal_path(path)
            if proposal_path:
                found.append({
                    'game_uuid': game.uuid, 'game_name': game.name, 'path': path,
                    'proposal': data.read_proposal(proposal_path),
                    'library_uuid': library.uuid, 'library_name': library.name,
                })
    return _ok({'proposals': found})


async def _scan_proposals(request, app, data):
    try:
        body = await request.json()
    except Exception:
        body = {}
    roots = body.get('roots', []) if isinstance(body, dict) else None
    if not isinstance(roots, list):
        return _error(400, 'bad_request', 'roots must be a list')
    found = []
    for root in roots:
        if not isinstance(root, str) or not data.safe_path(app, root)[0]:
            continue
        for folder in data.iter_game_folders(root):
            safe, _ = data.safe_path(app, folder)
            if not safe:
                continue
            proposal_path = data.proposal_path(folder)
            if proposal_path:
                found.append({'path': folder, 'proposal': data.read_proposal(proposal_path)})
    return _ok({'proposals': found})


async def _doctor_dry_run(request, app, data):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict) or not isinstance(body.get('roots'), list) or not body['roots']:
        return _error(400, 'bad_request', 'roots must be a non-empty list')
    roots = [root for root in body['roots']
             if isinstance(root, str) and data.safe_path(app, root)[0]]
    if not roots:
        return _error(403, 'forbidden', 'No safe roots')
    rows = data.doctor_dry_run(roots, template=body.get('template') or '{title}',
                               limit=body.get('limit'))
    return _ok({'rows': rows, 'count': len(rows)})


def _ok(payload=None, *, headers=None):
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload(payload or {}), headers=headers)


def _error(status, code, message, **fields):
    from oneirodex.utils.api_contract import api_error_payload
    payload, resolved = api_error_payload(message, code=code, status=status, **fields)
    return JSONResponse(payload, status_code=resolved)


def _login_redirect(app, request, login_manager, auth):
    from .oidc_status import _login_redirect as redirect
    return redirect(app, request, login_manager, auth, include_next=True)


def _admin_redirect(app, request, login_manager, auth):
    from .oidc_status import _login_redirect as redirect
    return redirect(app, request, login_manager, auth, message='You must be an admin to access this page.',
                    category='danger', include_next=False)


def _finish(response, app, request):
    from oneirodex.utils.security_headers import security_header_values
    for key, value in security_header_values(app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
