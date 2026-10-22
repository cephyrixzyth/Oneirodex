"""Native mutation API for unmatched-folder triage and update placement."""
from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import HTMLResponse, JSONResponse

from .request_auth import request_auth_context

UNMATCHED_BATCH_ID_CAP = 100
VALID_DUPLICATE_FIX_ACTIONS = {'merge', 'keep', 'ignore'}
_ITEM_KIND_ALIASES = {'app', 'utility', 'utilities', 'software', 'emu', 'experiences'}


class MutationProblem(Exception):
    def __init__(self, message, *, code='bad_request', status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class ScanUnmatchedMutationData:
    """Adapter that owns all persistence, path validation, scan and audit effects."""

    def amend_name(self, folder_id, payload):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            raise MutationProblem('Unmatched folder not found', code='not_found', status=404)
        try:
            changed = _apply_soft_amend(folder, payload)
            if not changed:
                raise MutationProblem(
                    'Provide search_name and/or display_name (name aliases search_name)',
                )
            db.session.commit()
        except MutationProblem:
            raise
        except Exception as exc:
            db.session.rollback()
            raise MutationProblem('An error occurred while processing your request', code='internal', status=500) from exc
        from oneirodex.utils.duplicate_check import folder_basename
        from oneirodex.utils import scan_unmatched_rows as rows
        return {
            'id': folder.id,
            'folder_path': folder.folder_path,
            'folder_name': folder_basename(folder.folder_path) or None,
            'search_name': rows._soft_name(folder.search_name),
            'display_name': rows._soft_name(folder.display_name),
            'effective_search_name': rows._effective_search_name(folder),
            'changed': changed,
            'disk_rename': False,
            'note': 'Soft naming only; disk folder_path unchanged.',
        }

    def clear_one(self, folder_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            return {'id': folder_id, 'ok': False, 'error': 'not_found'}
        try:
            db.session.delete(folder)
            db.session.commit()
            return {'id': folder_id, 'ok': True, 'result': 'cleared'}
        except Exception:
            db.session.rollback()
            return {'id': folder_id, 'ok': False, 'error': 'internal'}

    def clear_all_compat(self):
        from sqlalchemy import delete

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder

        result = db.session.execute(delete(UnmatchedFolder))
        db.session.commit()
        return int(result.rowcount or 0)

    def toggle_status_compat(self, folder_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            return None
        folder.status = 'Unmatched' if folder.status == 'Ignore' else 'Ignore'
        db.session.commit()
        return folder.status

    def mark_kind_one(self, flask_app, folder_id, kind, name, summary):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder
        from oneirodex.utils.software_identify import mark_unmatched_as_kind

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            return {'id': folder_id, 'ok': False, 'error': 'not_found'}
        try:
            game = mark_unmatched_as_kind(
                folder, item_kind=kind, name=name, steam_app_id=None, summary=summary,
            )
            db.session.commit()
            return {
                'id': folder_id, 'ok': True, 'game_uuid': game.uuid,
                'name': game.name, 'item_kind': game.item_kind,
            }
        except ValueError as exc:
            db.session.rollback()
            return {'id': folder_id, 'ok': False, 'error': str(exc)}
        except Exception:
            db.session.rollback()
            return {'id': folder_id, 'ok': False, 'error': 'internal'}

    def fix_one(self, folder_id, action, notes, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DuplicateFixLog, UnmatchedFolder

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            return {'id': folder_id, 'ok': False, 'error': 'not_found'}
        matched_uuid = getattr(folder, 'matched_game_uuid', None)
        match_reason = getattr(folder, 'match_reason', None)
        match_score = getattr(folder, 'match_score', None)
        folder_path = folder.folder_path
        if action == 'merge':
            db.session.delete(folder)
            result_status = 'cleared'
        elif action == 'keep':
            folder.status = 'Unmatched'
            result_status = 'Unmatched'
        else:
            folder.status = 'Ignore'
            result_status = 'Ignore'
        db.session.add(DuplicateFixLog(
            unmatched_folder_id=folder.id, folder_path=folder_path or '',
            matched_game_uuid=matched_uuid, match_reason=match_reason,
            match_score=match_score, action=action, actor_user_id=actor_id, notes=notes,
        ))
        return {
            'ok': True, 'id': folder.id, 'action': action, 'folder_id': folder.id,
            'folder_path': folder_path, 'result_status': result_status,
            'matched_game_uuid': matched_uuid, 'match_reason': match_reason,
            'match_score': match_score,
        }

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def audit_batch_fix(self, flask_app, action, actor_name, fixed, total, actor_id):
        from oneirodex.utils.event_logging import log_system_event

        log_system_event(
            f'Batch duplicate fix {action} by {actor_name}: {fixed}/{total}',
            event_type='duplicate_fix', event_level='information', audit_user=actor_id,
        )

    def amend_one(self, folder_id, payload):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder
        from oneirodex.utils import scan_unmatched_rows

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            return {'id': folder_id, 'ok': False, 'error': 'not_found'}
        if not any(key in payload for key in ('search_name', 'display_name', 'name')):
            return {'id': folder_id, 'ok': False, 'error': 'search_name_or_display_name_required'}
        try:
            changed = _apply_soft_amend(folder, payload)
            db.session.commit()
            helper = scan_unmatched_rows
            return {
                'id': folder_id, 'ok': True,
                'search_name': helper._soft_name(folder.search_name),
                'display_name': helper._soft_name(folder.display_name), 'changed': changed,
            }
        except Exception:
            db.session.rollback()
            return {'id': folder_id, 'ok': False, 'error': 'internal'}

    def audit_single_fix(self, flask_app, folder_path, action, actor_name, actor_id):
        from oneirodex.utils.event_logging import log_system_event

        log_system_event(
            f'Duplicate fix {action} by {actor_name}: {folder_path}',
            event_type='duplicate_fix', event_level='information', audit_user=actor_id,
        )

    def latest_fix_log_id(self, folder_id, action):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DuplicateFixLog

        row = db.session.execute(
            select(DuplicateFixLog).filter_by(unmatched_folder_id=folder_id, action=action)
            .order_by(DuplicateFixLog.created_at.desc())
        ).scalars().first()
        return row.id if row else None

    def mark_kind(self, flask_app, folder_id, kind, name, steam_app_id, summary, *, actor_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder
        from oneirodex.utils.software_identify import mark_unmatched_as_kind

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            raise MutationProblem('Unmatched folder not found', code='not_found', status=404)
        try:
            game = mark_unmatched_as_kind(
                folder, item_kind=kind, name=name, steam_app_id=steam_app_id,
                summary=summary,
            )
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            raise MutationProblem(str(exc)) from exc
        except Exception as exc:
            db.session.rollback()
            flask_app.logger.warning('scan match update failed: %s', type(exc).__name__)
            raise MutationProblem('Could not update the match', code='internal', status=500) from exc
        from oneirodex.utils.event_logging import log_system_event

        log_system_event(
            f'Marked unmatched as {kind}: {game.name} ({game.uuid})',
            event_type='identify', event_level='information', audit_user=actor_id,
        )
        return {
            'game_uuid': game.uuid, 'name': game.name,
            'item_kind': game.item_kind, 'content_kind': game.item_kind,
            'igdb_id': game.igdb_id, 'steam_app_id': game.steam_app_id,
            'full_disk_path': game.full_disk_path,
        }

    def retry_match(self, flask_app, folder_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Library, UnmatchedFolder
        from oneirodex.utils.security import get_allowed_base_directories, is_safe_path

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            raise MutationProblem('Unmatched folder not found', code='not_found', status=404)
        if folder.status != 'Unmatched':
            raise MutationProblem('Only Unmatched folders can be retried')
        library = db.session.get(Library, folder.library_uuid) if folder.library_uuid else None
        raw_path = (folder.folder_path or '').strip()
        path = Path(raw_path)
        if not library or not raw_path or not path.is_dir() or path.is_symlink():
            raise MutationProblem('The folder or its library is unavailable')
        safe, _ = is_safe_path(raw_path, get_allowed_base_directories(flask_app), logger=flask_app.logger)
        if not safe:
            raise MutationProblem('The folder is outside the configured library paths')
        from oneirodex.utils.game_name_parse import looks_like_patch_package, parse_game_label

        parsed = parse_game_label(path.name)
        if looks_like_patch_package(path.name) or parsed.get('is_bare_update_package'):
            raise MutationProblem('This folder is an update package; use Place update instead')
        from oneirodex.utils import scan_unmatched_rows as row_helper
        search_name = row_helper._soft_name(folder.search_name) or parsed.get('cleaned_name') or path.name
        search_name = parse_game_label(search_name).get('cleaned_name') or search_name
        try:
            from oneirodex.utils.services.scan_identify import retrieve_and_save_game

            game = retrieve_and_save_game(
                search_name, raw_path, library_uuid=library.uuid, defer_enrichment=True,
            )
            if isinstance(game, Game):
                db.session.delete(folder)
                db.session.commit()
                return {'matched': True, 'game_uuid': game.uuid, 'name': game.name,
                        'search_name': search_name}
            db.session.commit()
            return {'matched': False, 'search_name': search_name}
        except Exception as exc:
            db.session.rollback()
            flask_app.logger.warning('unmatched retry failed for row %s: %s', folder_id, type(exc).__name__)
            raise MutationProblem('Could not retry metadata matching', code='internal', status=500) from exc

    def place_update(self, flask_app, folder_id, game_root_name):
        """Exact guarded source->Updates move; callers never supply a filesystem path."""
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Library, UnmatchedFolder
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.security import (
            get_allowed_base_directories, is_safe_path, is_safe_path_strict,
        )

        folder = db.session.get(UnmatchedFolder, folder_id)
        if folder is None:
            raise MutationProblem('Unmatched folder not found', code='not_found', status=404)
        if folder.status != 'Unmatched':
            raise MutationProblem('Only Unmatched folders can be placed as updates')
        library = db.session.get(Library, folder.library_uuid) if folder.library_uuid else None
        root_value = (getattr(library, 'last_scan_folder', None) or '').strip() if library else ''
        library_root = Path(root_value) if root_value else None
        source = Path((folder.folder_path or '').strip())
        if library_root is None or not source.is_dir() or source.is_symlink():
            raise MutationProblem('The folder or its scan root is unavailable')
        allowed = get_allowed_base_directories(flask_app)
        source_safe, _ = is_safe_path_strict(str(source), allowed, logger=flask_app.logger)
        root_safe, _ = is_safe_path(str(library_root), allowed, logger=flask_app.logger)
        if not source_safe or not root_safe:
            raise MutationProblem('The folder is outside the configured library paths')
        try:
            source.resolve(strict=True).relative_to(library_root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise MutationProblem('The folder is outside this library scan root') from exc
        from oneirodex.utils.disk_rename import sanitize_fs_name
        from oneirodex.utils.game_name_parse import looks_like_patch_package, parse_game_label

        parsed = parse_game_label(source.name)
        if not (looks_like_patch_package(source.name) or parsed.get('is_bare_update_package')):
            raise MutationProblem('This folder is not recognized as a standalone update package')
        requested_name = str(game_root_name or parsed.get('cleaned_name') or '').strip()
        if not requested_name:
            raise MutationProblem('A game folder name is required')
        safe_name = sanitize_fs_name(requested_name)
        if safe_name in {'.', '..'}:
            raise MutationProblem('Invalid game folder name')
        existing = db.session.execute(
            select(Game).filter_by(library_uuid=library.uuid, name=safe_name).order_by(Game.uuid)
        ).scalars().first()
        if existing and existing.full_disk_path:
            game_root = Path(existing.full_disk_path)
            safe, _ = is_safe_path(str(game_root), allowed, logger=flask_app.logger)
            if not safe or not game_root.is_dir() or game_root.is_symlink():
                raise MutationProblem('The matching game folder is unavailable')
            try:
                game_root.resolve(strict=True).relative_to(library_root.resolve(strict=True))
            except (OSError, ValueError) as exc:
                raise MutationProblem('The matching game folder is outside this library scan root') from exc
            created_game_root = False
        else:
            game_root = library_root / safe_name
            safe, _ = is_safe_path_strict(str(game_root), allowed, logger=flask_app.logger)
            if not safe:
                raise MutationProblem('The destination is outside the configured library paths')
            if game_root.is_symlink() or (game_root.exists() and not game_root.is_dir()):
                raise MutationProblem('The destination game folder is not a usable directory', code='conflict', status=409)
            created_game_root = not game_root.exists()
        settings = global_settings_row()
        update_name = sanitize_fs_name(getattr(settings, 'update_folder_name', None) or 'updates')
        updates_root = game_root / update_name
        destination = updates_root / source.name
        if destination.exists():
            raise MutationProblem('An update with that folder name already exists', code='conflict', status=409)
        for candidate in (updates_root, destination):
            safe, _ = is_safe_path_strict(str(candidate), allowed, logger=flask_app.logger)
            if not safe:
                raise MutationProblem('The destination is outside the configured library paths')
        moved = False
        try:
            game_root.mkdir(parents=True, exist_ok=True)
            updates_root.mkdir(parents=True, exist_ok=True)
            os.rename(source, destination)
            moved = True
            if existing:
                from oneirodex.utils.scanning import process_game_updates

                process_game_updates(
                    existing.name, str(game_root), str(updates_root), library.uuid, update_name,
                )
            db.session.delete(folder)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            if moved and destination.exists() and not source.exists():
                try:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(destination, source)
                except OSError:
                    flask_app.logger.exception('Could not restore update folder after failed placement')
            flask_app.logger.warning('update placement failed for row %s: %s', folder_id, type(exc).__name__)
            raise MutationProblem('Could not place the update folder', code='internal', status=500) from exc
        return {
            'placed': True, 'game_root_name': safe_name,
            'created_game_root': created_game_root,
            'matched_game_uuid': existing.uuid if existing else None,
        }


def _apply_soft_amend(folder, payload):
    changed = {}
    if 'search_name' in payload or 'name' in payload:
        raw = payload['search_name'] if 'search_name' in payload else payload.get('name')
        folder.search_name = None if raw is None or (isinstance(raw, str) and not raw.strip()) else str(raw).strip()[:255]
        changed['search_name'] = folder.search_name
    if 'display_name' in payload:
        raw = payload.get('display_name')
        folder.display_name = None if raw is None or (isinstance(raw, str) and not raw.strip()) else str(raw).strip()[:255]
        changed['display_name'] = folder.display_name
    return changed


def create_scan_unmatched_mutations_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access if data_access is not None else ScanUnmatchedMutationData()
    options = dict(
        flask_app=flask_app, data=data, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager, database_scope=database_scope,
    )

    @router.api_route('/api/unmatched_folders/{folder_id:str}/name', methods=['PATCH', 'POST'])
    async def amend_name(folder_id: str, request: Request):
        return await _run(request, **options, handler=_amend_name, folder_id=folder_id, privilege='librarian')

    @router.options('/api/unmatched_folders/{folder_id:str}/name')
    async def amend_name_options(folder_id: str):
        # Flask generated this unauthenticated OPTIONS response automatically.
        # Keep its empty HTML response and Allow header for compatibility.
        return HTMLResponse('', status_code=200, headers={'Allow': 'OPTIONS, PATCH, POST'})

    @router.api_route('/api/unmatched_folders/batch/clear', methods=['POST'])
    async def batch_clear(request: Request):
        return await _run(request, **options, handler=_batch_clear, privilege='librarian')

    @router.api_route('/api/unmatched_folders/batch/mark_kind', methods=['POST'])
    async def batch_mark_kind(request: Request):
        return await _run(request, **options, handler=_batch_mark_kind, privilege='librarian')

    @router.api_route('/api/unmatched_folders/batch/fix', methods=['POST'])
    async def batch_fix(request: Request):
        return await _run(request, **options, handler=_batch_fix, privilege='librarian')

    @router.api_route('/api/unmatched_folders/batch/amend', methods=['POST'])
    async def batch_amend(request: Request):
        return await _run(request, **options, handler=_batch_amend, privilege='librarian')

    @router.api_route('/api/unmatched_folders/{folder_id:str}/fix', methods=['POST'])
    async def fix_one(folder_id: str, request: Request):
        return await _run(request, **options, handler=_fix_one, folder_id=folder_id, privilege='admin')

    @router.api_route('/api/unmatched_folders/{folder_id:str}/mark_kind', methods=['POST'])
    async def mark_kind(folder_id: str, request: Request):
        return await _run(request, **options, handler=_mark_kind, folder_id=folder_id, privilege='admin')

    @router.api_route('/api/unmatched_folders/{folder_id:str}/retry_match', methods=['POST'])
    async def retry_match(folder_id: str, request: Request):
        return await _run(request, **options, handler=_retry_match, folder_id=folder_id, privilege='librarian')

    @router.api_route('/api/unmatched_folders/{folder_id:str}/place_update', methods=['POST'])
    async def place_update(folder_id: str, request: Request):
        return await _run(
            request, **options, handler=_place_update, folder_id=folder_id,
            privilege='librarian', schema='PlaceUnmatchedUpdateBody',
        )

    @router.post('/delete_all_unmatched_folders')
    async def clear_all_legacy(request: Request):
        return await _run(
            request, **options, handler=_compat_clear_all, privilege='admin',
            csrf_html_for_form=True,
        )

    @router.post('/clear_unmatched_entry/{folder_id:str}')
    async def clear_one_legacy(folder_id: str, request: Request):
        return await _run(
            request, **options, handler=_compat_clear_one,
            folder_id=folder_id, privilege='admin', csrf_html_for_form=True,
        )

    @router.post('/toggle_ignore_status/{folder_id:str}')
    async def toggle_ignore_legacy(folder_id: str, request: Request):
        return await _run(
            request, **options, handler=_compat_toggle_ignore,
            folder_id=folder_id, privilege='admin', csrf_html_for_form=True,
        )

    @router.post('/update_unmatched_folder_status')
    async def update_status_legacy(request: Request):
        return await _run(
            request, **options, handler=_compat_update_status, privilege='admin',
            csrf_html_for_form=True,
        )

    return router


def mount_scan_unmatched_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_scan_unmatched_mutations_router(flask_app, **kwargs))
    return app


async def _run(
    request, *, flask_app, data, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, database_scope, handler, privilege,
    folder_id=None, schema=None, csrf_html_for_form=False,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        from .csrf_compat import csrf_error_response

        csrf_token = None
        if auth.token is None and request.headers.get('X-CSRFToken') is None:
            try:
                form = await request.form(max_files=0, max_fields=20, max_part_size=16 * 1024)
                csrf_token = form.get(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'))
            except Exception:
                pass
        response = csrf_error_response(
            request, auth.session_data, flask_app.config, token=csrf_token,
        )
        if response is not None and csrf_html_for_form:
            content_type = (request.headers.get('content-type') or '').split(';', 1)[0].strip().lower()
            if not (content_type.endswith('/json') or content_type.endswith('+json')):
                from .csrf_compat import csrf_html_error_response

                response = csrf_html_error_response(response)
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        if response is None and privilege == 'admin':
            response = _admin_gate(flask_app, request, login_manager, auth)
        elif response is None and privilege == 'librarian':
            response = _librarian_gate(auth)
        body = None
        if response is None and schema:
            body, response = await _validated_body(request, schema)
        if response is None:
            try:
                response = await handler(
                    request, flask_app, data, auth,
                    folder_id=folder_id, body=body,
                )
            except MutationProblem as exc:
                response = _error(exc.status, exc.code, exc.message)
            except Exception:
                rollback = getattr(data, 'rollback', None)
                if callable(rollback):
                    try:
                        rollback()
                    except Exception:
                        pass
                response = _error(500, 'internal', 'An error occurred while processing your request')
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _amend_name(request, _app, data, _auth, *, folder_id, **_):
    payload = await _json_dict(request)
    if not any(key in payload for key in ('search_name', 'display_name', 'name')):
        return _error(
            400, 'bad_request',
            'Provide search_name and/or display_name (name aliases search_name)',
            disk_rename=False,
        )
    try:
        return _ok(data.amend_name(folder_id, payload))
    except MutationProblem as exc:
        return _error(exc.status, exc.code, exc.message,
                      **({'disk_rename': False} if exc.code == 'bad_request' else {}))


def _compat_flash_redirect(auth, message, category):
    flashes = list(auth.session_data.get('_flashes') or [])
    flashes.append((category, message))
    auth.session_data['_flashes'] = flashes
    from starlette.responses import RedirectResponse

    return RedirectResponse('/scan_management?active_tab=unmatched', status_code=303)


def _compat_is_ajax(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


async def _compat_clear_all(_request, _app, data, auth, **_):
    try:
        data.clear_all_compat()
        message, category = 'All unmatched folders deleted successfully.', 'success'
    except Exception:
        rollback = getattr(data, 'rollback', None)
        if callable(rollback):
            rollback()
        message, category = 'Could not delete all unmatched folders.', 'error'
    return _compat_flash_redirect(auth, message, category)


async def _compat_clear_one(request, _app, data, auth, *, folder_id, **_):
    result = data.clear_one(folder_id)
    if result.get('ok'):
        if _compat_is_ajax(request):
            return _ok({'status': 'success', 'message': 'Entry cleared successfully'})
        return _compat_flash_redirect(auth, 'Unmatched folder entry cleared successfully.', 'success')
    if _compat_is_ajax(request):
        return _error(500, 'internal', 'Could not clear the entry', body_status='error')
    return _compat_flash_redirect(auth, 'Error clearing unmatched folder entry.', 'error')


async def _compat_toggle_ignore(request, _app, data, auth, *, folder_id, **_):
    try:
        status = data.toggle_status_compat(folder_id)
    except Exception:
        rollback = getattr(data, 'rollback', None)
        if callable(rollback):
            rollback()
        status = None
        failed = True
    else:
        failed = False
    if status is not None:
        message = f'Status changed to {status}'
        if _compat_is_ajax(request):
            return _ok({'status': 'success', 'new_status': status, 'message': message})
        return _compat_flash_redirect(auth, f'Folder status changed to {status}.', 'success')
    if _compat_is_ajax(request):
        return _error(
            500 if failed else 404,
            'internal' if failed else 'not_found',
            'Could not change the folder status' if failed else 'Folder not found.',
            body_status='error',
        )
    return _compat_flash_redirect(
        auth,
        'Error toggling ignore status.' if failed else 'Folder not found.',
        'error',
    )


async def _compat_update_status(request, _app, data, auth, **_):
    form = await request.form(max_files=0, max_fields=20, max_part_size=16 * 1024)
    folder_id = form.get('folder_id')
    auth.session_data['active_tab'] = 'unmatched'
    try:
        status = data.toggle_status_compat(folder_id) if folder_id else None
    except Exception:
        rollback = getattr(data, 'rollback', None)
        if callable(rollback):
            rollback()
        status = None
        failed = True
    else:
        failed = False
    if status is not None:
        message = f'Folder status updated to {status}'
        if _compat_is_ajax(request):
            return _ok({'status': 'success', 'new_status': status, 'message': message})
        return _compat_flash_redirect(auth, message, 'success')
    if _compat_is_ajax(request):
        return _error(
            500 if failed else 404,
            'internal' if failed else 'not_found',
            'Could not update the folder status' if failed else 'Folder not found.',
        )
    return _compat_flash_redirect(
        auth,
        'Error updating folder status.' if failed else 'Folder not found.',
        'error',
    )


def _parse_ids(payload):
    raw = payload.get('ids')
    if raw is None and isinstance(payload.get('items'), list):
        raw = [item.get('id') for item in payload['items'] if isinstance(item, dict)]
    if not isinstance(raw, list) or not raw:
        return None, _error(400, 'bad_request', 'ids required (non-empty array)')
    ids = [str(value or '').strip() for value in raw]
    ids = [value for value in ids if value]
    if not ids:
        return None, _error(400, 'bad_request', 'ids required (non-empty array)')
    if len(ids) > UNMATCHED_BATCH_ID_CAP:
        return None, _error(
            400, 'bad_request', f'ids cap is {UNMATCHED_BATCH_ID_CAP}',
            cap=UNMATCHED_BATCH_ID_CAP, requested=len(ids),
        )
    return list(dict.fromkeys(ids)), None


async def _batch_clear(request, _app, data, _auth, **_):
    ids, error = _parse_ids(await _json_dict(request))
    if error:
        return error
    results = [data.clear_one(folder_id) for folder_id in ids]
    cleared = sum(bool(row.get('ok')) for row in results)
    return _ok({
        'cleared': cleared, 'failed': sum(not row.get('ok') for row in results),
        'results': results, 'disk_io': False,
    })


def _kind_value(raw):
    from oneirodex.utils.item_kind import ITEM_KINDS, normalize_item_kind

    allowed = sorted(ITEM_KINDS)
    if not raw or not str(raw).strip():
        return None, _error(400, 'bad_request', f'item_kind required. Choose one of: {allowed}', item_kinds=allowed)
    folded = str(raw).strip().lower()
    if folded not in ITEM_KINDS and folded not in _ITEM_KIND_ALIASES:
        return None, _error(400, 'bad_request', f'Invalid item_kind. Choose one of: {allowed}', item_kinds=allowed)
    return normalize_item_kind(raw), None


async def _batch_mark_kind(request, app, data, _auth, **_):
    payload = await _json_dict(request)
    ids, error = _parse_ids(payload)
    if error:
        return error
    kind, error = _kind_value(payload.get('item_kind') or payload.get('content_kind') or payload.get('kind'))
    if error:
        return error
    results = [data.mark_kind_one(app, folder_id, kind, payload.get('name') or None,
                                  payload.get('summary') or None) for folder_id in ids]
    marked = sum(bool(row.get('ok')) for row in results)
    return _ok({
        'item_kind': kind, 'marked': marked,
        'failed': sum(not row.get('ok') for row in results),
        'results': results, 'disk_io': False,
    })


async def _batch_fix(request, _app, data, auth, **_):
    payload = await _json_dict(request)
    ids, error = _parse_ids(payload)
    if error:
        return error
    action = (payload.get('action') or '').strip().lower()
    if action not in VALID_DUPLICATE_FIX_ACTIONS:
        return _error(400, 'bad_request', f'Invalid action. Choose one of: {sorted(VALID_DUPLICATE_FIX_ACTIONS)}')
    notes_raw = payload.get('notes') or ''
    notes = (notes_raw[:512] if isinstance(notes_raw, str) else str(notes_raw)[:512]) or None
    results = []
    fixed = 0
    for folder_id in ids:
        try:
            result = data.fix_one(folder_id, action, notes, getattr(auth.user, 'id', None))
            if result.get('error') == 'not_found':
                results.append(result)
                continue
            data.commit()
            results.append(result)
            fixed += int(bool(result.get('ok')))
        except Exception:
            data.rollback()
            results.append({'id': folder_id, 'ok': False, 'error': 'internal'})
    data.audit_batch_fix(_app, action, getattr(auth.user, 'name', 'admin'), fixed, len(ids),
                         getattr(auth.user, 'id', None))
    return _ok({
        'action': action, 'fixed': fixed,
        'failed': sum(not row.get('ok') for row in results),
        'results': results, 'disk_io': False,
    })


async def _batch_amend(request, _app, data, _auth, **_):
    payload = await _json_dict(request)
    items = payload.get('items')
    results = []
    amended = 0
    if isinstance(items, list) and items:
        if len(items) > UNMATCHED_BATCH_ID_CAP:
            return _error(400, 'bad_request', f'ids cap is {UNMATCHED_BATCH_ID_CAP}',
                          cap=UNMATCHED_BATCH_ID_CAP, requested=len(items))
        for item in items:
            if not isinstance(item, dict):
                results.append({'id': None, 'ok': False, 'error': 'invalid_item'})
                continue
            folder_id = str(item.get('id') or '').strip()
            if not folder_id:
                results.append({'id': None, 'ok': False, 'error': 'id_required'})
                continue
            results.append(data.amend_one(folder_id, item))
    else:
        ids, error = _parse_ids(payload)
        if error:
            return error
        if not any(key in payload for key in ('search_name', 'display_name', 'name')):
            return _error(
                400, 'bad_request',
                'Provide search_name and/or display_name (or items[] with per-id fields)',
                disk_rename=False,
            )
        results = [data.amend_one(folder_id, payload) for folder_id in ids]
    amended = sum(bool(row.get('ok')) for row in results)
    return _ok({
        'amended': amended, 'failed': sum(not row.get('ok') for row in results),
        'results': results, 'disk_rename': False, 'disk_io': False,
    })


async def _fix_one(request, app, data, auth, *, folder_id, **_):
    payload = await _json_dict(request)
    action = (payload.get('action') or '').strip().lower()
    if action not in VALID_DUPLICATE_FIX_ACTIONS:
        return _error(400, 'bad_request', f'Invalid action. Choose one of: {sorted(VALID_DUPLICATE_FIX_ACTIONS)}')
    raw_notes = payload.get('notes') or ''
    notes = (raw_notes[:512] if isinstance(raw_notes, str) else str(raw_notes)[:512]) or None
    try:
        result = data.fix_one(folder_id, action, notes, getattr(auth.user, 'id', None))
    except Exception:
        data.rollback()
        return _error(500, 'internal', 'An error occurred while processing your request')
    if not result:
        return _error(404, 'not_found', 'Unmatched folder not found')
    if not result.get('ok') and result.get('error') == 'not_found':
        return _error(404, 'not_found', 'Unmatched folder not found')
    try:
        data.commit()
        data.audit_single_fix(app, result.get('folder_path'), action,
                              getattr(auth.user, 'name', 'admin'), getattr(auth.user, 'id', None))
        fix_log_id = data.latest_fix_log_id(folder_id, action)
    except Exception:
        data.rollback()
        return _error(500, 'internal', 'An error occurred while processing your request')
    return _ok({
        'action': action, 'folder_id': folder_id,
        'folder_path': result.get('folder_path'),
        'result_status': result.get('result_status'),
        'matched_game_uuid': result.get('matched_game_uuid') or payload.get('matched_game_uuid'),
        'match_reason': result.get('match_reason'), 'match_score': result.get('match_score'),
        'fix_log_id': fix_log_id,
    })


async def _mark_kind(request, app, data, auth, *, folder_id, **_):
    payload = await _json_dict(request)
    kind, error = _kind_value(payload.get('item_kind') or payload.get('content_kind') or payload.get('kind'))
    if error:
        return error
    steam_id = payload.get('steam_app_id')
    try:
        steam_id = int(steam_id) if steam_id is not None else None
    except (TypeError, ValueError, OverflowError):
        return _error(400, 'bad_request', 'steam_app_id must be an integer')
    try:
        result = data.mark_kind(app, folder_id, kind, payload.get('name') or None,
                                steam_id, payload.get('summary') or None,
                                actor_id=getattr(auth.user, 'id', None))
    except MutationProblem as exc:
        return _error(exc.status, exc.code, exc.message)
    return _ok(result)


async def _retry_match(_request, app, data, _auth, *, folder_id, **_):
    try:
        return _ok(data.retry_match(app, folder_id))
    except MutationProblem as exc:
        return _error(exc.status, exc.code, exc.message)


async def _place_update(_request, app, data, _auth, *, folder_id, body, **_):
    try:
        return _ok(data.place_update(app, folder_id, body.game_root_name))
    except MutationProblem as exc:
        return _error(exc.status, exc.code, exc.message)


async def _validated_body(request, schema_name):
    from oneirodex.schemas.scan import PlaceUnmatchedUpdateBody
    from oneirodex.utils.validation import format_validation_errors

    payload = await _json_dict(request)
    try:
        return PlaceUnmatchedUpdateBody.model_validate(payload), None
    except ValidationError as exc:
        return None, _error(422, 'unprocessable', 'Invalid request.', detail=format_validation_errors(exc))


async def _json_dict(request):
    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type != 'application/json' and not (
        content_type.startswith('application/') and content_type.endswith('+json')
    ):
        return {}
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _librarian_gate(auth):
    from oneirodex.utils.role_catalog import normalize_role

    role = normalize_role(getattr(auth.user, 'role', None) or '')
    if role not in ('librarian', 'admin'):
        return _error(403, 'forbidden', 'Librarian or admin required')
    if auth.token is not None and not auth.has_scope('admin'):
        return _error(403, 'forbidden', 'Librarian or admin required')
    return None


def _admin_gate(flask_app, request, login_manager, auth):
    from oneirodex.utils.role_catalog import normalize_role

    role = normalize_role(getattr(auth.user, 'role', None) or '')
    if role == 'admin' and auth.token is not None and not auth.has_scope('admin'):
        return _error(403, 'forbidden', 'This token does not have the admin scope')
    if role != 'admin':
        from .oidc_status import _login_redirect as redirect

        return redirect(
            flask_app, request, login_manager, auth,
            message='You must be an admin to access this page.',
            category='danger', include_next=False,
        )
    return None


def _login_redirect(flask_app, request, login_manager, auth):
    from .oidc_status import _login_redirect as redirect

    return redirect(
        flask_app, request, login_manager, auth,
        message=getattr(login_manager, 'login_message', None),
        category=getattr(login_manager, 'login_message_category', 'message'),
        include_next=True,
    )


def _ok(payload=None, *, status=200):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload), status_code=status)


def _error(status, code, message, **fields):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, **fields)
    return JSONResponse(payload, status_code=resolved)


def _finish(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
