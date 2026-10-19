"""Native download request and orphan-version actions with adapter boundaries."""
from __future__ import annotations

from contextlib import nullcontext
import os
import re
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context
from .query_compat import first_query_value
from .response_compat import flask_redirect_response

_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


class DownloadMutationData:
    def game(self, game_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

    def legacy_download_request(self, user, game):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        return db.session.execute(select(DownloadRequest).filter_by(
            user_id=user.id, file_location=game.full_disk_path,
        )).scalars().first()

    def other_download_request(self, user, path):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        return db.session.execute(select(DownloadRequest).filter_by(
            user_id=user.id, file_location=path,
        )).scalars().first()

    def other_file(self, file_type, game_uuid, file_token):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import GameExtra, GameUpdate
        model = GameUpdate if file_type == 'update' else GameExtra
        if _UUID_RE.fullmatch(file_token):
            statement = select(model).filter_by(uuid=file_token, game_uuid=game_uuid)
        else:
            try:
                file_id = int(file_token)
            except ValueError:
                return None
            statement = select(model).filter_by(id=file_id, game_uuid=game_uuid)
        return db.session.execute(statement).scalars().first()

    def path_size(self, path):
        from oneirodex.utils.functions import get_path_size
        return get_path_size(path)

    def create_other_download_request(self, game_uuid, user, file_record, path):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        from oneirodex.utils.event_logging import log_system_event
        row = DownloadRequest(
            user_id=user.id, game_uuid=game_uuid, status='available',
            download_size=self.path_size(path), file_location=path,
            zip_file_path=path,
        )
        db.session.add(row)
        file_record.times_downloaded = int(file_record.times_downloaded or 0) + 1
        db.session.commit()
        log_system_event(
            f'Download request created for file (streaming enabled): {os.path.basename(path)}',
            event_type='game', event_level='information', audit_user=user.id,
        )
        return row

    def legacy_zip_path(self, game):
        if not os.path.isdir(game.full_disk_path):
            return game.full_disk_path
        from oneirodex.utils.global_settings import global_settings_row
        settings = global_settings_row()
        files = []
        for entry in os.listdir(game.full_disk_path):
            full = os.path.join(game.full_disk_path, entry)
            if os.path.isdir(full) and settings and (
                entry.lower() == settings.update_folder_name.lower()
                or entry.lower() == settings.extras_folder_name.lower()
            ):
                continue
            if os.path.isfile(full):
                files.append(entry)
        significant = [entry for entry in files if not entry.lower().endswith(('.nfo', '.sfv'))
                       and entry.lower() not in ('file_id.diz', 'oneirodex.json')]
        return os.path.join(game.full_disk_path, significant[0]) if len(significant) == 1 else game.full_disk_path

    def create_legacy_download_request(self, game, user, zip_file_path):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        from oneirodex.utils.event_bus import publish_download_event
        from oneirodex.utils.event_logging import log_system_event
        row = DownloadRequest(
            user_id=user.id, game_uuid=game.uuid, status='available',
            download_size=game.size, file_location=game.full_disk_path,
            zip_file_path=zip_file_path,
        )
        db.session.add(row)
        game.times_downloaded = int(game.times_downloaded or 0) + 1
        db.session.commit()
        try:
            publish_download_event(row.id, row.status, game_uuid=game.uuid,
                                   game_name=game.name, user_id=user.id)
        except Exception:
            pass
        log_system_event(f'Download request created for game: {game.name} (instant streaming)',
                         event_type='game', event_level='information')
        return row

    def log_legacy_event(self, message, *, event_type, event_level):
        from oneirodex.utils.event_logging import log_system_event
        log_system_event(message, event_type=event_type, event_level=event_level)

    def can_access(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game
        return bool(user_can_access_game(user, game))

    def cleanup_orphans(self, game):
        from oneirodex.utils.game_versions import cleanup_orphan_versions
        return cleanup_orphan_versions(game)

    def log_cleanup(self, game, result, *, error=False):
        from oneirodex.utils.event_logging import log_system_event
        level = 'error' if error else 'information'
        message = (f'Error cleaning orphan versions for {game.uuid}' if error else
                   f'Orphan version cleanup for {game.name}: removed={len(result["removed"])} kept={len(result["kept"])}')
        log_system_event(message, event_type='game', event_level=level)

    def resolve_version(self, game, *, kind, version_uuid):
        from oneirodex.utils.game_versions import resolve_version_file
        return resolve_version_file(game, kind=kind, version_uuid=version_uuid)

    def exists(self, path):
        return os.path.isfile(path) or os.path.isdir(path)

    def allowed_bases(self, app):
        from oneirodex.utils.security import get_allowed_base_directories
        return get_allowed_base_directories(app)

    def safe_path(self, path, allowed_bases):
        from oneirodex.utils.security import is_safe_path
        return is_safe_path(path, allowed_bases)

    def zip_path(self, game, file_location, *, kind, zip_hint):
        if not os.path.isdir(file_location):
            return file_location
        # Version selections are already scoped to the requested update or
        # extra. Preserve the whole directory even when the base is absent.
        if kind != 'base':
            return file_location
        # A base game can have no library path yet. Only inspect the base
        # directory when one is present.
        if game.full_disk_path and os.path.normpath(file_location) != os.path.normpath(game.full_disk_path):
            return file_location
        from oneirodex.utils.global_settings import global_settings_row
        settings = global_settings_row()
        files = []
        for entry in os.listdir(file_location):
            full = os.path.join(file_location, entry)
            if os.path.isdir(full) and settings and (
                entry.lower() == settings.update_folder_name.lower()
                or entry.lower() == settings.extras_folder_name.lower()
            ):
                continue
            if os.path.isfile(full):
                files.append(entry)
        significant = [entry for entry in files if not entry.lower().endswith(('.nfo', '.sfv'))
                       and entry.lower() not in ('file_id.diz', 'oneirodex.json')]
        return os.path.join(file_location, significant[0]) if len(significant) == 1 else file_location

    def create_request(self, game, user, *, file_location, zip_file_path, kind='base', version_uuid=None):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        from oneirodex.utils.event_bus import publish_download_event
        from oneirodex.utils.event_logging import log_system_event

        existing = db.session.execute(select(DownloadRequest).filter_by(
            user_id=user.id, file_location=file_location,
        )).scalars().first()
        if existing:
            return existing
        download_size = game.size if kind == 'base' else self.path_size(file_location)
        row = DownloadRequest(
            user_id=user.id, game_uuid=game.uuid, status='available',
            download_size=download_size,
            file_location=file_location, zip_file_path=zip_file_path,
        )
        db.session.add(row)
        if kind == 'base' and file_location == game.full_disk_path:
            game.times_downloaded += 1
        elif kind in ('update', 'extra') and version_uuid:
            from oneirodex.models import GameExtra, GameUpdate
            model = GameUpdate if kind == 'update' else GameExtra
            version = db.session.execute(
                select(model).filter_by(uuid=version_uuid, game_uuid=game.uuid)
            ).scalars().first()
            if version is not None:
                version.times_downloaded = int(version.times_downloaded or 0) + 1
        db.session.commit()
        try:
            publish_download_event(row.id, 'available', game_uuid=game.uuid,
                                   game_name=game.name, user_id=row.user_id)
        except Exception:
            pass
        log_system_event(f'API download request created for game: {game.name}',
                         event_type='game', event_level='information')
        return row


def create_download_mutation_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    opts = dict(flask_app=flask_app, data=data_access or DownloadMutationData(),
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager, database_scope=database_scope)

    @router.post('/api/games/{game_uuid}/versions/cleanup_orphans')
    def cleanup_orphans(game_uuid: str, request: Request):
        return _run(request, **opts, game_uuid=game_uuid, operation='cleanup')

    @router.post('/api/downloads/games/{game_uuid}')
    async def create_download(game_uuid: str, request: Request):
        return await _run_download(request, **opts, game_uuid=game_uuid)

    @router.api_route('/download_game/{game_uuid}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    def legacy_download_game(game_uuid: str, request: Request):
        return _run_legacy_download_game(request, **opts, game_uuid=game_uuid)

    @router.api_route('/download_other/{file_type}/{game_uuid}/{file_id}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    def legacy_download_other(file_type: str, game_uuid: str, file_id: str, request: Request):
        return _run_legacy_download_other(
            request, **opts, file_type=file_type, game_uuid=game_uuid, file_id=file_id,
        )

    return router


def mount_download_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_download_mutation_router(flask_app, **kwargs))
    return app


def _auth_and_csrf(request, flask_app, find_user, find_token, commit_token_touch,
                   load_user_id, login_manager, *, check_csrf=True):
    from .csrf_compat import csrf_error_response
    auth = request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )
    # A verified bearer credential is explicit and is not ambient browser
    # authority. Cookie and remember-cookie writes still require CSRF.
    csrf = None if not check_csrf or auth.source == 'bearer' else csrf_error_response(
        request, auth.session_data, flask_app.config,
    )
    if csrf is not None:
        return None, csrf
    return auth, None


def _run(request, *, flask_app, data, find_user, find_token, commit_token_touch,
         load_user_id, login_manager, database_scope, game_uuid, operation):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth, csrf = _auth_and_csrf(request, flask_app, find_user, find_token,
                                     commit_token_touch, load_user_id, login_manager)
        if csrf is not None:
            response = csrf
        else:
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role, role_at_least
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'), include_next=True)
            elif normalize_role(getattr(auth.user, 'role', None)) == 'child' or not role_at_least(auth.user.role, 'librarian') or (auth.token is not None and not auth.has_scope('admin')):
                payload, status = api_error_payload('Librarian or admin required', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif not _UUID_RE.fullmatch(game_uuid):
                payload, status = api_error_payload('Invalid game UUID', code='bad_request')
                response = JSONResponse(payload, status_code=status)
            else:
                game = data.game(game_uuid)
                if game is None:
                    payload, status = api_error_payload('Game not found', code='not_found')
                    response = JSONResponse(payload, status_code=status)
                elif not data.can_access(auth.user, game):
                    payload, status = api_error_payload('Access denied', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        result = data.cleanup_orphans(game)
                        data.log_cleanup(game, result)
                        response = JSONResponse(api_ok_payload(result))
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        db.session.rollback()
                        data.log_cleanup(game, {}, error=True)
                        payload, status = api_error_payload('Failed to clean orphan versions', code='internal')
                        response = JSONResponse(payload, status_code=status)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
    return _finish(response, request, flask_app)


async def _run_download(request, *, flask_app, data, find_user, find_token,
                        commit_token_touch, load_user_id, login_manager,
                        database_scope, game_uuid):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth, csrf = _auth_and_csrf(request, flask_app, find_user, find_token,
                                     commit_token_touch, load_user_id, login_manager)
        if csrf is not None:
            response = csrf
        else:
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'), include_next=True)
            elif not auth.has_scope('write:download'):
                payload, status = api_error_payload('Missing scope: write:download', code='forbidden', detail={'required_scope': 'write:download'})
                response = JSONResponse(payload, status_code=status)
            elif not _UUID_RE.fullmatch(game_uuid):
                payload, status = api_error_payload('Invalid game UUID', code='bad_request')
                response = JSONResponse(payload, status_code=status)
            else:
                game = data.game(game_uuid)
                if game is None:
                    payload, status = api_error_payload('Game not found', code='not_found')
                    response = JSONResponse(payload, status_code=status)
                elif not data.can_access(auth.user, game):
                    payload, status = api_error_payload('Access denied', code='forbidden')
                    response = JSONResponse(payload, status_code=status)
                else:
                    body = await _read_json(request)
                    kind = (body.get('kind') or first_query_value(request.query_params, 'kind') or 'base') if body else (first_query_value(request.query_params, 'kind') or 'base')
                    kind = kind.strip().lower() if isinstance(kind, str) else 'base'
                    version_uuid = ((body.get('version_uuid') or body.get('version_id')) if body else None) or first_query_value(request.query_params, 'version_uuid') or first_query_value(request.query_params, 'version_id')
                    try:
                        file_location, zip_hint, resolved = data.resolve_version(game, kind=kind, version_uuid=version_uuid)
                    except ValueError as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    except LookupError as exc:
                        payload, status = api_error_payload(str(exc), code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        if file_location is None or not str(file_location).strip() or not data.exists(file_location):
                            payload, status = api_error_payload(
                                'Version file is missing on disk', code='not_found', status=410,
                                body_code='path_missing', hint=('This install path is gone. Use game details → Remove missing versions (librarian+) or re-scan after restoring files.'),
                                path_missing=True, downloadable=False,
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            bases = data.allowed_bases(flask_app)
                            if not bases:
                                payload, status = api_error_payload('Server configuration error', code='internal')
                                response = JSONResponse(payload, status_code=status)
                            elif not data.safe_path(file_location, bases)[0]:
                                payload, status = api_error_payload('Access denied', code='forbidden')
                                response = JSONResponse(payload, status_code=status)
                            else:
                                zip_target = file_location if kind == 'base' else zip_hint
                                zip_path = data.zip_path(game, zip_target, kind=kind,
                                                         zip_hint=zip_target)
                                try:
                                    row = data.create_request(game, auth.user,
                                        file_location=file_location, zip_file_path=zip_path,
                                        kind=kind, version_uuid=resolved)
                                    response = JSONResponse(api_ok_payload({
                                        'download_id': row.id, 'status': row.status,
                                        'stream_url': f'/download_zip/{row.id}',
                                        'kind': kind if kind in ('base', 'update', 'extra') else 'base',
                                        'version_uuid': resolved,
                                    }))
                                except Exception:
                                    from oneirodex.runtime_native.db_session import native_db as db
                                    db.session.rollback()
                                    payload, status = api_error_payload('Failed to create download request', code='internal')
                                    response = JSONResponse(payload, status_code=status)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
    return _finish(response, request, flask_app)


async def _read_json(request):
    import json
    try:
        if int(request.headers.get('content-length') or '0') > 16 * 1024:
            return None
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16 * 1024:
                return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def _finish(response, request, flask_app):
    from oneirodex.utils.security_headers import security_header_values
    response.headers.setdefault('Cache-Control', 'no-store')
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response


def _legacy_post_only_method_response(request):
    from starlette.responses import Response

    if request.method == 'OPTIONS':
        return Response(
            status_code=200,
            headers={'Allow': 'POST, OPTIONS', 'Content-Type': 'text/html; charset=utf-8'},
        )
    from werkzeug.exceptions import MethodNotAllowed
    legacy_response = MethodNotAllowed(valid_methods=['POST', 'OPTIONS']).get_response()
    response = Response(
        content=legacy_response.get_data(),
        status_code=legacy_response.status_code,
        headers={key: value for key, value in legacy_response.headers.items()},
        media_type=None,
    )
    if request.method == 'HEAD':
        response.body = b''
    return response


def _legacy_werkzeug_error(error_type):
    """Render the same HTML error response Flask's ``abort`` produced."""
    from starlette.responses import Response

    legacy_response = error_type().get_response()
    return Response(
        content=legacy_response.get_data(),
        status_code=legacy_response.status_code,
        headers={key: value for key, value in legacy_response.headers.items()},
        media_type=None,
    )


def _legacy_other_get_preflight(request, *, flask_app, data, find_user, find_token,
                                commit_token_touch, load_user_id, login_manager,
                                file_type, game_uuid, file_id):
    """Keep safe legacy GET failures useful without restoring GET writes."""
    from starlette.responses import Response
    from .oidc_status import _login_redirect, _set_session_cookie
    from .response_compat import flask_redirect_response
    from werkzeug.exceptions import BadRequest, Forbidden, NotFound

    auth, csrf = _auth_and_csrf(
        request, flask_app, find_user, find_token, commit_token_touch,
        load_user_id, login_manager, check_csrf=False,
    )
    response = csrf
    detail_url = f'/game_details/{game_uuid}'
    if response is None and auth.user is None:
        response = _login_redirect(flask_app, request, login_manager, auth)
    elif response is None and not auth.has_scope('write:download'):
        response = Response(status_code=403)
    elif response is None and file_type not in ('update', 'extra'):
        data.log_legacy_event('Invalid download file type', event_type='security', event_level='warning')
        _flash(auth.session_data, 'error', 'Invalid file type')
        response = flask_redirect_response(detail_url)
    elif response is None and not _UUID_RE.fullmatch(game_uuid):
        response = _legacy_werkzeug_error(BadRequest)
    elif response is None:
        game = data.game(game_uuid)
        if game is None:
            response = _legacy_werkzeug_error(NotFound)
        elif not data.can_access(auth.user, game):
            response = _legacy_werkzeug_error(Forbidden)
        else:
            token = str(file_id or '').strip()
            if not _UUID_RE.fullmatch(token) and not _is_integer_token(token):
                response = _legacy_werkzeug_error(BadRequest)
            else:
                record = data.other_file(file_type, game_uuid, token)
                if record is None:
                    data.log_legacy_event(
                        f'Failed to download {file_type} file for game {game_uuid[:8]}',
                        event_type='game', event_level='error',
                    )
                    _flash(auth.session_data, 'error', f'{file_type.capitalize()} file not found')
                    response = flask_redirect_response(detail_url)
                else:
                    path = record.file_path
                    bases = data.allowed_bases(flask_app)
                    if not bases:
                        _flash(auth.session_data, 'error', 'System configuration error. Please contact administrator.')
                        response = flask_redirect_response(detail_url)
                    elif not data.safe_path(path, bases)[0]:
                        _flash(auth.session_data, 'error', 'Access denied.')
                        response = flask_redirect_response(detail_url)
                    elif not data.exists(path):
                        data.log_legacy_event(
                            f'{file_type.capitalize()} file not found on disk: {path}',
                            event_type='system', event_level='error',
                        )
                        _flash(auth.session_data, 'error', 'File not found on disk')
                        response = flask_redirect_response(detail_url)
                    elif data.other_download_request(auth.user, path):
                        _flash(auth.session_data, 'info', 'You already have a download request for this file')
                        response = flask_redirect_response('/downloads')
                    else:
                        # A valid GET would create a DownloadRequest in v1.1.8.
                        # Keep the current POST-only security boundary intact.
                        return None

    if auth is not None and (
        auth.should_set_session_cookie or auth.session_data.get('_flashes')
    ):
        _set_session_cookie(response, flask_app, auth)
    return response


def _run_legacy_download_game(request, *, flask_app, data, find_user, find_token,
                              commit_token_touch, load_user_id, login_manager,
                              database_scope, game_uuid):
    from starlette.responses import Response
    from .oidc_status import _login_redirect, _set_session_cookie
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.utils.security_headers import security_header_values

    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        if request.method != 'POST':
            response = _legacy_post_only_method_response(request)
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            response.headers.setdefault('Cache-Control', 'no-store')
            return response
        auth, csrf = _auth_and_csrf(
            request, flask_app, find_user, find_token, commit_token_touch,
            load_user_id, login_manager,
        )
        response = None
        if csrf is not None:
            response = csrf
        elif auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        elif not auth.has_scope('write:download'):
            response = Response(status_code=403)
        elif not _UUID_RE.fullmatch(game_uuid):
            from werkzeug.exceptions import BadRequest
            response = _legacy_werkzeug_error(BadRequest)
        else:
            game = data.game(game_uuid)
            if game is None:
                from werkzeug.exceptions import NotFound
                response = _legacy_werkzeug_error(NotFound)
            elif not data.can_access(auth.user, game):
                from werkzeug.exceptions import Forbidden
                response = _legacy_werkzeug_error(Forbidden)
            else:
                data.log_legacy_event(
                    f'User initiated download for game: {game.name}',
                    event_type='game', event_level='information',
                )
                bases = data.allowed_bases(flask_app)
                if not bases:
                    _flash(auth.session_data, 'error', 'System configuration error. Please contact administrator.')
                    response = flask_redirect_response('/downloads', status_code=302)
                elif not data.safe_path(game.full_disk_path, bases)[0]:
                    _flash(auth.session_data, 'error', 'Access denied.')
                    response = flask_redirect_response('/downloads', status_code=302)
                elif data.legacy_download_request(auth.user, game):
                    _flash(auth.session_data, 'info', 'You already have a download request for this game in your basket. Please check your downloads page.')
                    response = flask_redirect_response('/downloads', status_code=302)
                else:
                    try:
                        data.create_legacy_download_request(
                            game, auth.user, data.legacy_zip_path(game),
                        )
                        response = flask_redirect_response('/downloads', status_code=302)
                    except Exception:
                        db.session.rollback()
                        data.log_legacy_event(
                            f'Error creating download request for game {game_uuid}',
                            event_type='game', event_level='error',
                        )
                        _flash(auth.session_data, 'error', 'An error occurred processing your request.')
                        response = flask_redirect_response('/downloads', status_code=302)
        if auth is not None and (
            auth.should_set_session_cookie or auth.session_data.get('_flashes')
        ):
            _set_session_cookie(response, flask_app, auth)
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    response.headers.setdefault('Cache-Control', 'no-store')
    if request.method == 'HEAD':
        response.body = b''
    return response


def _flash(session_data, category, message):
    flashes = list(session_data.get('_flashes') or [])
    flashes.append((category, message))
    session_data['_flashes'] = flashes


def _is_integer_token(value):
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _run_legacy_download_other(request, *, flask_app, data, find_user, find_token,
                               commit_token_touch, load_user_id, login_manager,
                               database_scope, file_type, game_uuid, file_id):
    from starlette.responses import Response
    from .oidc_status import _login_redirect, _set_session_cookie
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.utils.security_headers import security_header_values

    detail_url = f'/game_details/{game_uuid}'
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        if request.method == 'GET':
            response = _legacy_other_get_preflight(
                request, flask_app=flask_app, data=data,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager, file_type=file_type,
                game_uuid=game_uuid, file_id=file_id,
            )
            if response is not None:
                for key, value in security_header_values(flask_app.config).items():
                    response.headers.setdefault(key, value)
                response.headers.setdefault('Cache-Control', 'no-store')
                return response
        if request.method != 'POST':
            response = _legacy_post_only_method_response(request)
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            response.headers.setdefault('Cache-Control', 'no-store')
            return response
        auth, csrf = _auth_and_csrf(
            request, flask_app, find_user, find_token, commit_token_touch,
            load_user_id, login_manager,
        )
        if csrf is not None:
            response = csrf
        elif auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        elif not auth.has_scope('write:download'):
            response = Response(status_code=403)
        elif file_type not in ('update', 'extra'):
            data.log_legacy_event('Invalid download file type', event_type='security', event_level='warning')
            _flash(auth.session_data, 'error', 'Invalid file type')
            response = flask_redirect_response(detail_url, status_code=302)
        elif not _UUID_RE.fullmatch(game_uuid):
            from werkzeug.exceptions import BadRequest
            response = _legacy_werkzeug_error(BadRequest)
        else:
            game = data.game(game_uuid)
            if game is None:
                from werkzeug.exceptions import NotFound
                response = _legacy_werkzeug_error(NotFound)
            elif not data.can_access(auth.user, game):
                from werkzeug.exceptions import Forbidden
                response = _legacy_werkzeug_error(Forbidden)
            else:
                token = str(file_id or '').strip()
                if not _UUID_RE.fullmatch(token) and not _is_integer_token(token):
                    data.log_legacy_event('Invalid download file ID', event_type='security', event_level='warning')
                    from werkzeug.exceptions import BadRequest
                    response = _legacy_werkzeug_error(BadRequest)
                else:
                    record = data.other_file(file_type, game_uuid, token)
                    if record is None:
                        data.log_legacy_event(
                            f'Failed to download {file_type} file for game {game_uuid[:8]}',
                            event_type='game', event_level='error',
                        )
                        _flash(auth.session_data, 'error', f'{file_type.capitalize()} file not found')
                        response = flask_redirect_response(detail_url, status_code=302)
                    else:
                        path = record.file_path
                        bases = data.allowed_bases(flask_app)
                        if not bases:
                            _flash(auth.session_data, 'error', 'System configuration error. Please contact administrator.')
                            response = flask_redirect_response(detail_url, status_code=302)
                        elif not data.safe_path(path, bases)[0]:
                            _flash(auth.session_data, 'error', 'Access denied.')
                            response = flask_redirect_response(detail_url, status_code=302)
                        elif not data.exists(path):
                            _flash(auth.session_data, 'error', 'File not found on disk')
                            response = flask_redirect_response(detail_url, status_code=302)
                        elif data.other_download_request(auth.user, path):
                            _flash(auth.session_data, 'info', 'You already have a download request for this file')
                            response = flask_redirect_response('/downloads', status_code=302)
                        else:
                            try:
                                data.create_other_download_request(game_uuid, auth.user, record, path)
                                response = flask_redirect_response('/downloads', status_code=302)
                            except Exception as exc:
                                db.session.rollback()
                                from sqlalchemy.exc import SQLAlchemyError
                                if isinstance(exc, SQLAlchemyError):
                                    data.log_legacy_event(
                                        f'Database error creating {file_type} download request: {exc}',
                                        event_type='system', event_level='error',
                                    )
                                    message = 'Database error occurred'
                                else:
                                    data.log_legacy_event(
                                        f'Error creating {file_type} download request: {exc}',
                                        event_type='system', event_level='error',
                                    )
                                    message = 'An error occurred processing your request.'
                                _flash(auth.session_data, 'error', message)
                                response = flask_redirect_response(detail_url, status_code=302)
        if auth is not None and (
            auth.should_set_session_cookie or auth.session_data.get('_flashes')
        ):
            _set_session_cookie(response, flask_app, auth)
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    response.headers.setdefault('Cache-Control', 'no-store')
    if request.method == 'HEAD':
        response.body = b''
    return response
