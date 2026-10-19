"""Native, adapter-backed subset of library-tools write/preview APIs.

Every filesystem/database operation is delegated to ``LibraryToolsMutationData``
so the router can be exercised using fake-only tests.
"""
from __future__ import annotations

from .form_compat import first_form_value
from typing import Any, Callable
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, Request

from .library_tools import _admin_redirect, _error, _finish, _login_redirect, _ok
from .request_auth import request_auth_context


class LibraryToolsMutationData:
    """Side-effect boundary for the migrated subset."""

    def allowed_bases(self, app):
        from oneirodex.utils.security import get_allowed_base_directories
        return get_allowed_base_directories(app)

    def safe_path(self, app, path):
        from oneirodex.utils.security import is_safe_path
        return is_safe_path(path, self.allowed_bases(app))

    def game(self, app, game_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        return db.session.execute(
            select(Game).filter_by(uuid=game_uuid)
        ).scalars().first()

    def build_rename_preview(self, root, *, title, year, template, rename_root,
                             rename_media, move_bucket):
        from oneirodex.utils.disk_rename import build_rename_plan
        return build_rename_plan(root, title=title, year=year, template=template,
                                 rename_root=rename_root,
                                 rename_top_level_media=rename_media,
                                 move_letter_bucket=move_bucket)

    def remove_proposal(self, path):
        from oneirodex.utils.match_proposal import remove_proposal_files
        return remove_proposal_files(path)

    def write_proposals(self, rows):
        from oneirodex.utils.library_doctor import doctor_write_proposals
        return doctor_write_proposals(rows)

    def directory_readable(self, path):
        import os
        return os.path.isdir(path) and os.access(path, os.R_OK)

    def link_existing_game(self, app, game_uuid, path, actor_name, actor_id):
        from sqlalchemy import select
        from sqlalchemy.exc import SQLAlchemyError
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, UnmatchedFolder
        from oneirodex.utils.event_logging import log_system_event
        game = db.session.execute(
            select(Game).filter_by(uuid=game_uuid)
        ).scalars().first()
        if not game:
            return None, 'not_found'
        try:
            game.full_disk_path = path
            from oneirodex.utils.library_health import mark_game_path_ok
            mark_game_path_ok(game)
            try:
                from oneirodex.utils.rom_language import apply_rom_language_fields
                apply_rom_language_fields(game, path)
            except Exception:
                pass
            unmatched = db.session.execute(
                select(UnmatchedFolder).filter_by(folder_path=path)
            ).scalars().first()
            if unmatched:
                db.session.delete(unmatched)
            db.session.commit()
            log_system_event(
                f"Admin {actor_name} linked existing game '{game.name}' (UUID: {game.uuid}) to folder" +
                (' (removed from unmatched list)' if unmatched else ''),
                event_type='game', event_level='information', audit_user=actor_id)
            return {'game_uuid': game.uuid, 'game_name': game.name,
                    'full_disk_path': game.full_disk_path,
                    'removed_from_unmatched': bool(unmatched)}, None
        except SQLAlchemyError:
            db.session.rollback()
            return None, 'internal'

    def validate_rename_plan(self, plan, root):
        from oneirodex.utils.disk_rename import validate_plan_for_game
        return validate_plan_for_game(plan, root)

    def apply_rename(self, app, game_uuid, plan, allowed_bases):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.disk_rename import apply_rename_plan
        from oneirodex.utils.path_repoint import _moved as path_moved, repoint_paths
        results = apply_rename_plan(plan, allowed_bases)
        roots = [row for row in results if row.get('ok') and row.get('kind') == 'root_folder']
        game = db.session.execute(
            select(Game).filter_by(uuid=game_uuid)
        ).scalars().first()
        if not game:
            return results, '', True
        if roots:
            for row in roots:
                repoint_paths(row['from_path'], row['to_path'])
                moved = path_moved(game.full_disk_path, row['from_path'], row['to_path'])
                if moved is not None:
                    game.full_disk_path = moved
            try:
                try:
                    from oneirodex.utils.rom_language import apply_rom_language_fields
                    apply_rom_language_fields(game, game.full_disk_path)
                except Exception:
                    pass
                db.session.commit()
            except Exception:
                db.session.rollback()
                return results, game.full_disk_path, True
        return results, game.full_disk_path, False

    def doctor_apply_renames(self, app, rows, allowed_bases, template):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.library_doctor import doctor_apply_renames
        from oneirodex.utils.path_repoint import repoint_paths
        results = doctor_apply_renames(rows, allowed_bases, template=template)
        moved = 0
        for row in results:
            for item in row.get('results') or []:
                if item.get('ok') and item.get('kind') == 'root_folder':
                    moved += repoint_paths(item['from_path'], item['to_path'])
        if moved:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                return results, moved, True
        return results, moved, False

    def backfill_steam_metadata(self, app, *, library_uuid, limit, only_incomplete, cascade):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.steam_metadata import hydrate_game_from_steam
        query = select(Game)
        if not cascade:
            query = query.filter(Game.steam_app_id.isnot(None))
        if library_uuid:
            query = query.filter(Game.library_uuid == library_uuid)
        candidates = db.session.execute(query).scalars().all()
        updated, skipped, errors = [], 0, []
        for game in candidates:
            if len(updated) >= limit:
                break
            if only_incomplete and (game.summary or '').strip() and (game.genres or []):
                skipped += 1
                continue
            try:
                report = hydrate_game_from_steam(game) if game.steam_app_id else {}
                if cascade and not ((game.summary or '').strip() and (game.genres or [])):
                    from oneirodex.utils.metadata_cascade import hydrate_game_from_cascade
                    cascade_result = hydrate_game_from_cascade(
                        game, skip=('steam',) if game.steam_app_id else ())
                    for key, value in (cascade_result.get('applied') or {}).items():
                        if value and not report.get(key):
                            report[key] = value
            except Exception as exc:
                errors.append({'uuid': game.uuid, 'name': game.name, 'error': str(exc)})
                continue
            if any(bool(value) for value in report.values()) if report else False:
                updated.append({'uuid': game.uuid, 'name': game.name,
                                'filled': {key: value for key, value in report.items() if value}})
            else:
                skipped += 1
        if updated:
            db.session.commit()
        return {'scanned': len(candidates), 'updated': len(updated), 'skipped': skipped,
                'errors': errors, 'games': updated[:50]}

    def library(self, app, library_uuid):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library
        return db.session.get(Library, library_uuid)

    def check_freshness(self, app, library_uuid, *, limit, only_missing):
        from oneirodex.utils.freshness.service import check_library_freshness
        return check_library_freshness(
            library_uuid, limit=limit, only_missing=only_missing, app=app,
        )


def create_library_tools_mutations_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None, login_manager=None,
    data_access=None, database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    opts = dict(flask_app=flask_app, data=data_access or LibraryToolsMutationData(),
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager, database_scope=database_scope)

    @router.post('/api/library_tools/rename/preview')
    async def rename_preview(request: Request):
        return await _run(request, **opts, handler=_rename_preview)

    @router.post('/api/library_tools/proposals/approve')
    async def approve_proposal(request: Request):
        return await _run(request, **opts, handler=_approve_proposal)

    @router.post('/api/library_tools/doctor/write_proposals')
    async def doctor_write_proposals(request: Request):
        return await _run(request, **opts, handler=_doctor_write_proposals)

    @router.post('/api/library_tools/link_existing_game')
    async def link_existing_game(request: Request):
        return await _run(request, **opts, handler=_link_existing_game)

    @router.post('/link_existing_game')
    async def legacy_link_existing_game(request: Request):
        return await _legacy_link_existing_game(request, **opts)

    @router.post('/api/library_tools/rename/apply')
    async def rename_apply(request: Request):
        return await _run(request, **opts, handler=_rename_apply)

    @router.post('/api/library_tools/doctor/apply_renames')
    async def doctor_apply_renames(request: Request):
        return await _run(request, **opts, handler=_doctor_apply_renames)

    @router.post('/api/library_tools/backfill_steam_metadata')
    async def backfill_steam_metadata(request: Request):
        return await _run(request, **opts, handler=_backfill_steam_metadata)

    @router.post('/api/library_tools/check_freshness')
    async def check_freshness(request: Request):
        return await _run(request, **opts, handler=_check_freshness)

    return router


def mount_library_tools_mutations_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_library_tools_mutations_router(flask_app, **kwargs))
    return app


async def _legacy_link_existing_game(request, *, flask_app, data, find_user,
                                     find_token, commit_token_touch, load_user_id,
                                     login_manager, database_scope):
    from contextlib import nullcontext

    from starlette.responses import Response
    from werkzeug.utils import redirect as werkzeug_redirect

    from .csrf_compat import csrf_error_response
    from .oidc_status import _login_redirect, _set_session_cookie
    from .request_auth import _lifetime_seconds
    from .session_compat import load_session_cookie
    from oneirodex.utils.role_catalog import normalize_role

    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        form = await request.form(max_files=0, max_fields=12, max_part_size=16 * 1024)
        try:
            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(
                    flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                ),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            response = csrf_error_response(
                request, session_data, flask_app.config,
                token=str(first_form_value(form, 'csrf_token') or ''),
            )
            if response is not None:
                response = _csrf_html_response(response)
            auth = None
            if response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
                if auth.user is None:
                    response = _login_redirect(flask_app, request, login_manager, auth)
                elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    from .library_tools import _error
                    response = _error(403, 'forbidden', 'Admin required')

            if response is None:
                game_uuid = str(first_form_value(form, 'game_uuid') or '').strip()
                full_disk_path = str(first_form_value(form, 'full_disk_path') or '').strip()
                library_uuid = str(first_form_value(form, 'library_uuid') or '').strip()
                from_unmatched = str(first_form_value(form, 'from_unmatched') or 'false') == 'true'
                if not game_uuid or not full_disk_path:
                    message, category = 'Select a game and a folder path before linking.', 'error'
                else:
                    try:
                        allowed = data.allowed_bases(flask_app)
                        if not allowed:
                            message, category = 'Service configuration error: No allowed base directories configured.', 'error'
                        else:
                            safe, reason = data.safe_path(flask_app, full_disk_path)
                            if not safe:
                                message, category = f'Access denied: {reason}', 'error'
                            elif not data.directory_readable(full_disk_path):
                                message, category = 'The selected folder does not exist or cannot be read.', 'error'
                            else:
                                result, error_code = data.link_existing_game(
                                    flask_app, game_uuid, full_disk_path,
                                    getattr(auth.user, 'name', 'administrator'),
                                    getattr(auth.user, 'id', None),
                                )
                                if error_code == 'not_found':
                                    message, category = 'Selected game could not be found.', 'error'
                                elif error_code:
                                    message, category = 'Unable to link this folder to the selected game.', 'error'
                                else:
                                    message = f"Linked existing game '{result['game_name']}' to this folder."
                                    category = 'success'
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db

                        db.session.rollback()
                        message, category = 'Unable to link this folder to the selected game.', 'error'

                flashes = list(auth.session_data.get('_flashes') or [])
                flashes.append((category, message))
                auth.session_data['_flashes'] = flashes
                if category == 'success':
                    # The legacy blueprint's url_for destination is rooted at
                    # /scan_management, without the current admin-shell prefix.
                    location = '/scan_management?active_tab=unmatched'
                else:
                    # Match Flask's legacy url_for behavior: omit empty/None
                    # query values and sort the remaining keys.
                    query = urlencode(sorted((key, value) for key, value in {
                        'full_disk_path': full_disk_path or None,
                        'library_uuid': library_uuid or None,
                        'from_unmatched': 'true' if from_unmatched else 'false',
                    }.items() if value is not None))
                    location = '/add_game_manual?' + query
                legacy_redirect = werkzeug_redirect(location, code=302)
                response = Response(
                    content=legacy_redirect.get_data(),
                    status_code=legacy_redirect.status_code,
                    headers={
                        'content-type': legacy_redirect.headers['content-type'],
                        'location': legacy_redirect.headers['location'],
                    },
                )
                _set_session_cookie(response, flask_app, auth)
            return response
        finally:
            await form.close()


def _csrf_html_response(csrf):
    import json

    from starlette.responses import Response
    from werkzeug.exceptions import BadRequest

    try:
        error_payload = json.loads(csrf.body or b'{}')
    except (TypeError, ValueError, UnicodeDecodeError):
        error_payload = {}
    bad_request = BadRequest(
        description=error_payload.get('message') or 'The CSRF token is invalid.',
    ).get_response()
    return Response(
        content=bad_request.get_data(),
        status_code=bad_request.status_code,
        media_type='text/html',
    )


async def _run(request, *, flask_app, data, find_user, find_token,
               commit_token_touch, load_user_id, login_manager, database_scope, handler):
    from contextlib import nullcontext
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(request, flask_app.config, find_user=find_user,
                                    find_token=find_token,
                                    commit_token_touch=commit_token_touch,
                                    load_user_id=load_user_id,
                                    login_manager=login_manager)
        request.state.auth_user = auth.user
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
                    response = await handler(request, flask_app, data)
                except Exception:
                    response = _error(500, 'internal', 'An error occurred while processing your request')
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie
            _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _json_body(request):
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


async def _rename_preview(request, app, data):
    body = await _json_body(request)
    if body is None:
        body = {}
    game_uuid = body.get('game_uuid')
    game = data.game(app, game_uuid) if game_uuid else None
    if game is None:
        return _error(404, 'not_found', 'Game not found')
    root = getattr(game, 'full_disk_path', None) or ''
    safe, error = data.safe_path(app, root)
    if not safe:
        return _error(403, 'forbidden', error or 'Unsafe path')
    plan = data.build_rename_preview(
        root, title=body.get('title') or game.name, year=body.get('year'),
        template=body.get('template') or '{title}',
        rename_root=bool(body.get('rename_root', True)),
        rename_media=bool(body.get('rename_top_level_media', False)),
        move_bucket=bool(body.get('move_letter_bucket', False)))
    return _ok({'plan': plan, 'game_uuid': game.uuid})


async def _approve_proposal(request, app, data):
    body = await _json_body(request)
    if body is None or not isinstance(body.get('path'), str) or not body['path'].strip() \
            or 'igdb_id' not in body:
        return _error(400, 'bad_request', 'path and igdb_id required')
    path, igdb_id = body['path'], body['igdb_id']
    if (igdb_id in (None, '') or isinstance(igdb_id, bool)
            or not isinstance(igdb_id, (int, str))):
        return _error(400, 'bad_request', 'path and igdb_id required')
    path = path.strip()
    if not path:
        return _error(400, 'bad_request', 'path and igdb_id required')
    safe, error = data.safe_path(app, path)
    if not safe:
        return _error(403, 'forbidden', error or 'Unsafe path')
    try:
        data.remove_proposal(path)
    except OSError:
        return _error(500, 'internal', 'Could not clear the proposal')
    return _ok({'message': 'Proposal cleared. Complete import via Add Game / Identify with this IGDB ID.',
                'path': path, 'igdb_id': igdb_id,
                'identify_hint': f"/add_game_manual?full_disk_path={path}&igdb_id={igdb_id}"})


async def _doctor_write_proposals(request, app, data):
    body = await _json_body(request)
    rows = body.get('rows', []) if body is not None else None
    if not isinstance(rows, list):
        return _error(400, 'bad_request', 'rows must be a list')
    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = row.get('path')
        if isinstance(path, str) and path and data.safe_path(app, path)[0]:
            filtered.append(row)
    return _ok({'results': data.write_proposals(filtered)})


async def _validated_body(request, model):
    from pydantic import ValidationError
    from oneirodex.utils.validation import format_validation_errors
    body = await _json_body(request)
    try:
        return model.model_validate(body or {}), None
    except ValidationError as exc:
        return None, _error(422, 'unprocessable', 'Invalid request.',
                            detail=format_validation_errors(exc))


async def _link_existing_game(request, app, data):
    from oneirodex.schemas.library_tools import LinkExistingGameBody
    body, error_response = await _validated_body(request, LinkExistingGameBody)
    if error_response:
        return error_response
    safe, error = data.safe_path(app, body.full_disk_path)
    if not safe:
        return _error(403, 'forbidden', error or 'Unsafe path')
    if not data.directory_readable(body.full_disk_path):
        return _error(400, 'bad_request', 'The selected folder does not exist or cannot be read')
    result, error_code = data.link_existing_game(
        app, body.game_uuid, body.full_disk_path,
        getattr(getattr(request.state, 'auth_user', None), 'name', 'administrator'),
        getattr(getattr(request.state, 'auth_user', None), 'id', None))
    if error_code == 'not_found':
        return _error(404, 'not_found', 'Selected game could not be found')
    if error_code:
        return _error(500, 'internal', 'Unable to link this folder to the selected game')
    return _ok({'game_uuid': result['game_uuid'], 'game_name': result['game_name'],
                'full_disk_path': result['full_disk_path'], 'library_uuid': body.library_uuid,
                'from_unmatched': body.from_unmatched,
                'removed_from_unmatched': result['removed_from_unmatched']})


async def _rename_apply(request, app, data):
    body = await _json_body(request) or {}
    plan = body.get('plan') or []
    if not isinstance(plan, list) or not plan:
        return _error(400, 'bad_request', 'No rename operations selected')
    game_uuid = body.get('game_uuid')
    game = data.game(app, game_uuid) if game_uuid else None
    if game is None:
        return _error(404, 'not_found', 'Game not found')
    problems = data.validate_rename_plan(plan, getattr(game, 'full_disk_path', None) or '')
    if problems:
        return _error(400, 'bad_request',
                      'That rename plan does not match this game. Preview it again and retry.',
                      problems=problems)
    results, path, db_error = data.apply_rename(app, game.uuid, plan, data.allowed_bases(app))
    if db_error:
        return _error(500, 'internal', 'Disk renamed but DB update failed', results=results)
    return _ok({'results': results, 'full_disk_path': path})


async def _doctor_apply_renames(request, app, data):
    from oneirodex.schemas.library_tools import ApplyRenamesBody
    body, error_response = await _validated_body(request, ApplyRenamesBody)
    if error_response:
        return error_response
    filtered = []
    for row in body.rows:
        if isinstance(row, dict):
            path = row.get('path')
            if isinstance(path, str) and path and data.safe_path(app, path)[0]:
                filtered.append(row)
    results, records_updated, db_error = data.doctor_apply_renames(
        app, filtered, data.allowed_bases(app), body.template or '{title}')
    if db_error:
        return _error(500, 'internal', 'Folders renamed but DB update failed', results=results)
    return _ok({'results': results, 'records_updated': records_updated})


async def _backfill_steam_metadata(request, app, data):
    body = await _json_body(request) or {}
    try:
        limit = min(max(int(body.get('limit') or 100), 1), 500)
    except (TypeError, ValueError):
        return _error(400, 'bad_request', 'limit must be a number')
    result = data.backfill_steam_metadata(
        app, library_uuid=body.get('library_uuid'), limit=limit,
        only_incomplete=bool(body.get('only_incomplete', True)),
        cascade=bool(body.get('cascade', True)))
    return _ok(result)


async def _check_freshness(request, app, data):
    from oneirodex.schemas.library_tools import CheckFreshnessBody
    body, error_response = await _validated_body(request, CheckFreshnessBody)
    if error_response:
        return error_response
    if not data.library(app, body.library_uuid):
        return _error(404, 'not_found', 'Library not found')
    try:
        limit = min(max(int(body.limit or 50), 1), 500)
    except (TypeError, ValueError):
        return _error(400, 'bad_request', 'limit must be a number')
    result = data.check_freshness(app, body.library_uuid, limit=limit,
                                  only_missing=bool(body.only_missing))
    return _ok(result)

