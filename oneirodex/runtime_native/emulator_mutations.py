"""Native ASGI routes for emulator save files and cheat catalogues.

The route adapter keeps Flask session and bearer-token semantics while isolating
all database and filesystem work behind ``EmulatorMutationData``.
"""
from __future__ import annotations

from contextlib import nullcontext
from io import BytesIO
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class EmulatorMutationData:
    """Production adapter; tests replace it with an in-memory fake."""

    def game(self, game_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

    def can_access(self, user, game):
        from oneirodex.utils.library_acl import user_can_access_game

        return user_can_access_game(user, game)

    def cheat_surface(self, game):
        from oneirodex.platform import cheat_surface_for_platform
        from oneirodex.utils.play_url import library_platform_key

        return cheat_surface_for_platform(library_platform_key(game))

    def list_cheats(self, game_uuid):
        from oneirodex.utils.emulator_cheats import list_cheat_files

        return list_cheat_files(game_uuid)

    def read_cheat(self, game_uuid, filename):
        from oneirodex.utils.emulator_cheats import read_cheat_file

        return read_cheat_file(game_uuid, filename)

    def store_cheat(self, game_uuid, filename, payload):
        from werkzeug.datastructures import FileStorage
        from oneirodex.utils.emulator_cheats import store_cheat_file

        return store_cheat_file(game_uuid, FileStorage(stream=BytesIO(payload), filename=filename))

    def create_cheat(self, game_uuid, *, name, codes, dialect=None):
        from oneirodex.utils.emulator_cheats import create_cheat_file

        return create_cheat_file(game_uuid, name=name, codes=codes, dialect=dialect)

    def delete_cheat(self, game_uuid, filename):
        from oneirodex.utils.emulator_cheats import delete_cheat_file

        return delete_cheat_file(game_uuid, filename)

    def save_sync_enabled(self):
        from oneirodex.utils.emulator_saves import save_sync_enabled

        return save_sync_enabled()

    def list_saves(self, user_id, game_uuid):
        from oneirodex.utils.emulator_saves import list_saves

        return list_saves(user_id, game_uuid)

    def is_state_slot(self, row):
        from oneirodex.utils.emulator_saves import is_state_slot

        return is_state_slot(row)

    def store_save(self, user_id, game_uuid, slot_name, filename, payload):
        from werkzeug.datastructures import FileStorage
        from oneirodex.utils.emulator_saves import store_save

        return store_save(
            user_id=user_id, game_uuid=game_uuid, slot_name=slot_name,
            file_storage=FileStorage(stream=BytesIO(payload), filename=filename),
        )

    def read_save(self, row):
        from oneirodex.utils.emulator_saves import read_save_bytes

        return read_save_bytes(row)

    def delete_save(self, user_id, game_uuid, slot_name):
        from oneirodex.utils.emulator_saves import delete_save

        return delete_save(user_id, game_uuid, slot_name)

    def pc_cheats(self, game_uuid):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import PcCheat

        return db.session.execute(select(PcCheat).filter_by(game_uuid=game_uuid).order_by(PcCheat.id.asc())).scalars().all()

    def create_pc_cheat(self, **values):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import PcCheat

        row = PcCheat(**values)
        db.session.add(row)
        db.session.commit()
        return row

    def delete_pc_cheat(self, game_uuid, cheat_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import PcCheat

        row = db.session.get(PcCheat, cheat_id)
        if row is None or row.game_uuid != game_uuid:
            return False
        db.session.delete(row)
        db.session.commit()
        return True

    def bios_overview(self, flask_app):
        from oneirodex.utils.emulator_bios import bios_status_for_cores, bios_status_for_platforms, list_bios_files
        from oneirodex.utils.bios_install import volume_missing_markdown

        return {
            'files': list_bios_files(), 'cores': bios_status_for_cores(),
            'platforms': bios_status_for_platforms(),
            'import_source': flask_app.config.get('BIOS_IMPORT_SOURCE') or '',
            'missing_markdown': volume_missing_markdown(),
        }

    def firmware_source_isdir(self, source):
        import os

        return os.path.isdir(source)

    def firmware_source_allowed(self, source, flask_app):
        from oneirodex.utils.bios_install import firmware_import_allowed_bases
        from oneirodex.utils.security import is_safe_path

        return is_safe_path(source, firmware_import_allowed_bases(flask_app), logger=flask_app.logger)[0]

    def scan_firmware(self, source):
        from oneirodex.utils.bios_install import plan_firmware_import

        return plan_firmware_import(source)

    def install_firmware(self, source, *, selections, skipped, overwrite):
        from oneirodex.utils.bios_install import apply_firmware_import

        return apply_firmware_import(source, selections=selections, skipped=skipped, overwrite=overwrite)

    def upload_bios(self, filename, payload):
        from werkzeug.datastructures import FileStorage
        from oneirodex.utils.emulator_bios import store_bios_file

        return store_bios_file(FileStorage(stream=BytesIO(payload), filename=filename))


def create_emulator_mutations_router(
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
    data = data_access or EmulatorMutationData()

    async def run(request: Request, game_uuid: str, operation: str, filename: str | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if request.method in {'POST', 'DELETE'}:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                response = None
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                pc_mutation = operation == 'pc_cheat' or (operation == 'pc_cheats' and request.method == 'POST')
                if pc_mutation:
                    from oneirodex.utils.role_catalog import role_at_least

                    scope_ok = role_at_least(getattr(auth.user, 'role', None), 'librarian') and (
                        auth.token is None or auth.has_scope('admin')
                    )
                else:
                    needed = 'write:library' if request.method in {'POST', 'DELETE'} else 'read:library'
                    scope_ok = auth.has_scope(needed)
                if not scope_ok:
                    message = (
                        'This token does not have the required library scope'
                        if auth.token is not None else 'Librarian or admin required'
                    )
                    response = _error(403, 'forbidden', message)
                else:
                    try:
                        response = await _dispatch(data, auth, request, game_uuid, operation, filename, flask_app)
                    except Exception:
                        flask_app.logger.exception('Emulator API request failed')
                        response = _error(500, 'internal', 'Something went wrong on our end. The error has been logged.')
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            return _finish(response, flask_app, request)

    async def run_bios(request: Request, operation: str):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            # Flask-Login's route wrapper redirects anonymous callers before
            # the admin/handler path runs. Preserve that ordering here; CSRF
            # still runs before authorization for authenticated browser writes.
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif request.method == 'POST':
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                response = None
            if response is None:
                from oneirodex.utils.role_catalog import normalize_role

                is_admin = normalize_role(getattr(auth.user, 'role', None)) == 'admin'
                if not is_admin:
                    from .oidc_status import _login_redirect as admin_redirect

                    response = admin_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    response = _error(403, 'forbidden', 'This token does not have the admin scope')
                else:
                    try:
                        if operation == 'overview' and request.method in {'GET', 'HEAD'}:
                            response = JSONResponse(data.bios_overview(flask_app))
                        elif operation == 'scan':
                            source, error = await _firmware_source(data, flask_app, request)
                            if error:
                                response = error
                            else:
                                try:
                                    response = _ok(data.scan_firmware(source))
                                except OSError:
                                    response = _error(500, 'internal', 'Could not read that firmware collection.')
                        elif operation == 'install':
                            source, error = await _firmware_source(data, flask_app, request)
                            if error:
                                response = error
                            else:
                                body = await _json(request) or {}
                                selections = body.get('selections') or {}
                                skipped = body.get('skipped') or []
                                if not isinstance(selections, dict):
                                    response = _error(400, 'bad_request', 'selections must be a map of filename to dump.')
                                elif not isinstance(skipped, list):
                                    response = _error(400, 'bad_request', 'skipped must be a list of filenames.')
                                else:
                                    try:
                                        result = data.install_firmware(
                                            source,
                                            selections={str(key): str(value) for key, value in selections.items()},
                                            skipped=[str(name) for name in skipped],
                                            overwrite=bool(body.get('overwrite')),
                                        )
                                        response = _ok(result)
                                    except OSError:
                                        response = _error(500, 'internal', 'Could not write to the firmware volume. Check the mount is present and writable.')
                        elif operation == 'overview' and request.method == 'POST':
                            form, response = await _bounded_form(request, flask_app.config)
                            if form is not None:
                                try:
                                    upload = form.get('file')
                                    if upload is None:
                                        response = _error(400, 'bad_request', 'Choose a firmware file to upload.')
                                    else:
                                        payload = await upload.read()
                                        try:
                                            response = _ok(data.upload_bios(upload.filename, payload), status=201)
                                        except ValueError as exc:
                                            response = _error(422, 'unprocessable', str(exc))
                                        except OSError:
                                            response = _error(500, 'internal', 'Could not write to the firmware volume. Check the mount is present and writable.')
                                finally:
                                    await form.close()
                        else:
                            response = _error(405, 'bad_request', 'Method not allowed')
                    except Exception:
                        flask_app.logger.exception('Emulator firmware API request failed')
                        response = _error(500, 'internal', 'An error occurred while processing your request')
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            return _finish(response, flask_app, request)

    @router.api_route('/api/games/{game_uuid}/cheats', methods=['GET', 'POST', 'HEAD'])
    async def cheats(game_uuid: str, request: Request):
        return await run(request, game_uuid, 'cheats')

    @router.api_route('/api/games/{game_uuid}/cheats/{filename:path}', methods=['GET', 'DELETE', 'HEAD'])
    async def cheat_file(game_uuid: str, filename: str, request: Request):
        if not filename:
            from .response_compat import flask_route_not_found_response

            return flask_route_not_found_response(flask_app, request)
        return await run(request, game_uuid, 'cheat_file', filename)

    @router.api_route('/api/games/{game_uuid}/saves', methods=['GET', 'POST', 'HEAD'])
    async def saves(game_uuid: str, request: Request):
        return await run(request, game_uuid, 'saves')

    @router.api_route('/api/games/{game_uuid}/saves/{slot_name}', methods=['GET', 'DELETE', 'HEAD'])
    async def save_file(game_uuid: str, slot_name: str, request: Request):
        return await run(request, game_uuid, 'save_file', slot_name)

    @router.options('/api/games/{game_uuid}/pc_cheats', include_in_schema=False)
    async def pc_cheats_options(game_uuid: str):
        # Flask's automatic OPTIONS response preserves this method order.
        # Starlette's synthesized response sorts the same set differently.
        return Response(
            status_code=200,
            headers={
                'Allow': 'OPTIONS, GET, HEAD, POST',
                'Content-Type': 'text/html; charset=utf-8',
            },
        )

    @router.api_route('/api/games/{game_uuid}/pc_cheats', methods=['GET', 'POST', 'HEAD'])
    async def pc_cheats(game_uuid: str, request: Request):
        return await run(request, game_uuid, 'pc_cheats')

    @router.api_route('/api/games/{game_uuid}/pc_cheats/{cheat_id:int}', methods=['DELETE'])
    async def pc_cheat(game_uuid: str, cheat_id: int, request: Request):
        return await run(request, game_uuid, 'pc_cheat', str(cheat_id))

    @router.api_route('/api/emulator-bios', methods=['GET', 'POST', 'HEAD'])
    async def emulator_bios(request: Request):
        return await run_bios(request, 'overview')

    @router.api_route('/api/emulator-bios/scan', methods=['POST'])
    async def emulator_bios_scan(request: Request):
        return await run_bios(request, 'scan')

    @router.api_route('/api/emulator-bios/install', methods=['POST'])
    async def emulator_bios_install(request: Request):
        return await run_bios(request, 'install')

    return router


async def _dispatch(data, auth, request, game_uuid, operation, filename, flask_app):
    user = auth.user
    method = 'GET' if request.method == 'HEAD' else request.method
    game = data.game(game_uuid)
    if game is None:
        return _error(404, 'not_found', 'Game not found')
    pc_mutation = operation == 'pc_cheat' or (operation == 'pc_cheats' and method == 'POST')
    if not pc_mutation and not data.can_access(user, game):
        return _error(403, 'forbidden', 'You do not have access to that game')

    if operation.startswith('cheat'):
        surface = data.cheat_surface(game)
        if operation == 'cheats' and method == 'GET':
            return JSONResponse({'game_uuid': game_uuid, 'cheat_surface': surface,
                                 'cheats': data.list_cheats(game_uuid) if surface == 'retroarch' else []})
        if surface != 'retroarch':
            return _error(403, 'forbidden', 'RetroArch cheats are not available for this platform',
                          cheat_surface=surface)
        from oneirodex.utils.role_catalog import normalize_role

        if method in {'POST', 'DELETE'} and normalize_role(getattr(user, 'role', None)) == 'child':
            return _error(403, 'forbidden', 'Children cannot modify cheats')
        if operation == 'cheat_file' and method == 'GET':
            try:
                payload = data.read_cheat(game_uuid, filename)
            except (ValueError, FileNotFoundError):
                return _error(404, 'not_found', 'Cheat file not found')
            return _download(payload, filename, 'text/plain')
        if operation == 'cheat_file' and method == 'DELETE':
            try:
                data.delete_cheat(game_uuid, filename)
            except ValueError as exc:
                return _error(400, 'bad_request', str(exc))
            return _ok()
        if operation == 'cheats' and method == 'POST':
            content_type = request.headers.get('content-type', '').lower()
            if content_type.startswith('multipart/form-data'):
                form, error = await _bounded_form(request, flask_app.config)
                if error is not None:
                    return error
                try:
                    upload = form.get('file')
                    if upload is not None and getattr(upload, 'filename', '').strip():
                        try:
                            payload = await upload.read()
                            row = data.store_cheat(game_uuid, upload.filename, payload)
                        except ValueError as exc:
                            return _error(400, 'bad_request', str(exc))
                        except Exception as exc:
                            code = getattr(exc, 'code', 'bad_request')
                            return _error(413 if code == 'payload_too_large' else 400, code, str(exc))
                        return JSONResponse(row, status_code=201)
                finally:
                    await form.close()
            body = await _json(request)
            if isinstance(body, dict):
                try:
                    row = data.create_cheat(game_uuid, name=body.get('name'),
                                            codes=body.get('codes'), dialect=body.get('dialect'))
                except ValueError as exc:
                    code = getattr(exc, 'code', 'bad_request')
                    return _error(413 if code == 'payload_too_large' else 400, code, str(exc))
                return JSONResponse(row, status_code=201)
            return _error(400, 'bad_request', 'Send a .cht file, or a JSON body with name and codes')

    if operation.startswith('save'):
        if operation == 'saves' and method == 'GET':
            rows = data.list_saves(user.id, game_uuid)
            return JSONResponse({
                'enabled': data.save_sync_enabled(), 'game_uuid': game_uuid,
                'csrf_token': _csrf_token(auth.session_data, flask_app.config),
                'saves': [{**row.to_dict(), 'is_state': data.is_state_slot(row)} for row in rows],
            })
        if operation == 'saves' and method == 'POST':
            if not data.save_sync_enabled():
                return _error(403, 'forbidden', 'Emulator save sync is disabled')
            form, error = await _bounded_form(request, flask_app.config)
            if error is not None:
                return error
            try:
                upload = form.get('file') or form.get('save')
                if upload is None:
                    return _error(400, 'bad_request', 'multipart file field "file" is required')
                slot = (str(form.get('slot') or request.query_params.get('slot') or 'slot1')).strip()
                try:
                    payload = await upload.read()
                    row = data.store_save(user.id, game_uuid, slot, getattr(upload, 'filename', None), payload)
                except ValueError as exc:
                    return _error(400, 'bad_request', str(exc))
                except RuntimeError as exc:
                    return _error(403, 'forbidden', str(exc))
                return JSONResponse(row.to_dict(), status_code=201)
            finally:
                await form.close()
        if operation == 'save_file' and method == 'GET':
            row = next((item for item in data.list_saves(user.id, game_uuid)
                        if item.slot_name == filename), None)
            if row is None:
                return _error(404, 'not_found', 'Save not found')
            try:
                payload = data.read_save(row)
            except FileNotFoundError:
                return _error(404, 'not_found', 'Save not found')
            except Exception:
                return _error(500, 'internal', 'Failed to read save')
            return _download(payload, row.filename, 'application/octet-stream')
        if operation == 'save_file' and method == 'DELETE':
            if not data.delete_save(user.id, game_uuid, filename):
                return _error(404, 'not_found', 'Save not found')
            return _ok({'status': 'deleted', 'slot_name': filename})

    if operation.startswith('pc_cheat'):
        from oneirodex.utils.role_catalog import normalize_role, role_at_least

        if data.cheat_surface(game) != 'pc_wand':
            surface = data.cheat_surface(game)
            return _error(400, 'bad_request',
                          'PC cheats apply to PC titles. This platform uses the RetroArch cheat surface.',
                          cheat_surface=surface)
        methods = {
            'console': 'In-game console command', 'config': 'Config / ini file edit',
            'save': 'Save-file field (external editor)', 'launch_flag': 'Launch option / command-line flag',
            'note': 'Note',
        }
        if operation == 'pc_cheats' and method == 'GET':
            rows = data.pc_cheats(game_uuid)
            return _ok({
                'game_uuid': game_uuid,
                'methods': [{'id': key, 'label': label} for key, label in methods.items()],
                'cheats': [row.to_dict() for row in rows],
                'stance': 'Notes only — Oneirodex never modifies game files or injects into a running game. Single-player use.',
            })
        if not role_at_least(normalize_role(getattr(user, 'role', None)), 'librarian'):
            return _error(403, 'forbidden', 'Librarian or admin required')
        if auth.token is not None and not auth.has_scope('admin'):
            return _error(403, 'forbidden', 'This token does not have the admin scope')
        if operation == 'pc_cheats' and method == 'POST':
            body = await _json(request)
            from pydantic import ValidationError
            from oneirodex.schemas.emulator_cheats import CreatePcCheatBody
            from oneirodex.utils.validation import format_validation_errors

            try:
                body = CreatePcCheatBody.model_validate(body or {})
            except ValidationError as exc:
                return _error(422, 'unprocessable', 'Invalid request.', detail=format_validation_errors(exc))
            label = body.label
            method = (body.method or 'note').strip().lower()
            if method not in methods:
                return _error(400, 'bad_request', f"method must be one of: {', '.join(sorted(methods))}")
            row = data.create_pc_cheat(
                game_uuid=game_uuid, method=method, label=label[:160],
                payload=(body.payload or '').strip() or None,
                notes=(body.notes or '').strip()[:1000] or None,
                single_player_only=bool(body.single_player_only),
                created_by_user_id=getattr(user, 'id', None),
            )
            return _ok({'cheat': row.to_dict()}, status=201)
        if operation == 'pc_cheat' and method == 'DELETE':
            try:
                cheat_id = int(filename)
            except (TypeError, ValueError):
                return _error(400, 'bad_request', 'Invalid cheat id')
            if not data.delete_pc_cheat(game_uuid, cheat_id):
                return _error(404, 'not_found', 'Cheat not found')
            return _ok({'removed': cheat_id})
    return _error(405, 'bad_request', 'Method not allowed')


def _csrf_token(session_data, config):
    from oneirodex.runtime_native.session_compat import generate_csrf_token

    secret = config.get('WTF_CSRF_SECRET_KEY') or config.get('SECRET_KEY')
    field = str(config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
    return generate_csrf_token(session_data, secret, field_name=field)


async def _json(request):
    try:
        value = await request.json()
    except Exception:
        return None
    return value if isinstance(value, dict) else None


async def _firmware_source(data, flask_app, request):
    body = await _json(request) or {}
    raw = body.get('source') or ''
    raw = raw.strip() if isinstance(raw, str) else ''
    if not raw:
        configured = flask_app.config.get('BIOS_IMPORT_SOURCE') or ''
        raw = configured.strip() if isinstance(configured, str) else ''
    if not raw:
        return None, _error(400, 'bad_request', 'Set a firmware collection folder, or configure BIOS_IMPORT_SOURCE.')
    if not data.firmware_source_isdir(raw):
        return None, _error(404, 'not_found', 'That folder does not exist on the server.')
    if not data.firmware_source_allowed(raw, flask_app):
        return None, _error(403, 'forbidden',
                            'That folder is outside the allowed directories. Point BIOS_IMPORT_SOURCE at it, or use a path under a library root.')
    return raw, None


def _body_limit(config):
    try:
        value = int(config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024)
    except (TypeError, ValueError, OverflowError):
        value = 32 * 1024 * 1024
    return max(0, value)


def _too_large(config):
    limit_mb = config.get('MAX_UPLOAD_MB', max(1, _body_limit(config) // (1024 * 1024)))
    return _error(
        413, 'payload_too_large',
        f'The file you tried to upload is too large. Maximum size is {limit_mb}MB.',
    )


async def _bounded_form(request, config):
    """Read no more than Flask's total request limit before multipart parsing."""
    limit = _body_limit(config)
    declared = request.headers.get('content-length')
    try:
        if declared is not None and int(declared) > limit:
            return None, _too_large(config)
    except ValueError:
        return None, _error(400, 'bad_request', 'Invalid content length')

    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None, _too_large(config)
        chunks.append(chunk)
    body = b''.join(chunks)
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {'type': 'http.disconnect'}
        delivered = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    from starlette.requests import Request as StarletteRequest

    parsed_request = StarletteRequest(request.scope, receive)
    try:
        return await parsed_request.form(), None
    except Exception:
        return None, _error(400, 'bad_request', 'Invalid multipart form data')


def _ok(payload=None, status=200):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload), status_code=status)


def _error(status, code, message, **extra):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code, status=status, **extra)
    return JSONResponse(payload, status_code=status)


def _download(payload, name, mime):
    from starlette.responses import StreamingResponse
    from werkzeug.utils import secure_filename

    safe_name = secure_filename(str(name or 'download')) or 'download'
    return StreamingResponse(BytesIO(payload), media_type=mime,
                             headers={'Content-Disposition': f'attachment; filename="{safe_name}"'})


def _finish(response: Response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        if hasattr(response, 'body_iterator'):
            response.body_iterator = _empty_body()
        else:
            response.body = b''
    return response


async def _empty_body():
    if False:  # make this an async generator while yielding no response bytes
        yield b''


def mount_emulator_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_emulator_mutations_router(flask_app, **kwargs))
    return app
