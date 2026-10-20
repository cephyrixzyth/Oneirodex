"""Native admin route for removing a game from the library."""
from __future__ import annotations

from contextlib import nullcontext
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class GameDeleteMutationData:
    def scan_running(self) -> bool:
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ScanJob

        return db.session.execute(
            select(ScanJob.id).where(ScanJob.status == 'Running').limit(1),
        ).first() is not None

    def delete_game(self, game_uuid: str, *, config) -> None:
        from oneirodex.utils.services.game_delete import delete_game

        delete_game(game_uuid, config=config)

    def game(self, game_uuid):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        return db.session.execute(
            select(Game).filter_by(uuid=game_uuid),
        ).scalars().first()

    def allowed_bases(self, app):
        from oneirodex.utils.security import get_allowed_base_directories

        return get_allowed_base_directories(app)

    def safe_path(self, path, allowed_bases):
        from oneirodex.utils.security import is_safe_path_strict

        return is_safe_path_strict(path, allowed_bases)

    def folder_entry(self, path):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder

        return db.session.execute(
            select(UnmatchedFolder).filter_by(folder_path=path),
        ).scalars().first()

    def remove_folder_entry(self, entry):
        from oneirodex.runtime_native.db_session import native_db as db

        if entry is not None:
            db.session.delete(entry)
            db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def remove_path(self, path):
        if os.path.isfile(path):
            os.remove(path)
        else:
            shutil.rmtree(path)

    def path_exists(self, path):
        return os.path.exists(path)

    def path_is_directory(self, path):
        return os.path.isdir(path)

    def delete_image_record_and_file(self, image_id, *, config):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Image

        image = db.session.get(Image, image_id)
        if image is None:
            return None
        root = Path(config['IMAGE_SAVE_PATH']).resolve()
        relative = Path(str(image.url or ''))
        if not str(image.url or '').strip() or relative.is_absolute() or any(
            part in ('..', '') for part in relative.parts
        ):
            raise ValueError('Invalid image path')
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError('Invalid image path') from exc
        staged = None
        if target.exists():
            if target.is_dir():
                # Preserve the existing failure for directories.
                target.unlink()
            staged = target.with_name(f'.{target.name}.delete-{uuid4().hex}')
            os.replace(target, staged)
        try:
            db.session.delete(image)
            db.session.commit()
        except Exception:
            if staged is not None and staged.exists():
                try:
                    os.replace(staged, target)
                except OSError:
                    logging.getLogger(__name__).error(
                        'Could not restore image after a failed database delete'
                    )
            raise
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                # The record is committed. Leave the unreferenced staged file
                # for operator cleanup rather than report a false DB failure.
                logging.getLogger(__name__).warning(
                    'Image delete committed but staged file cleanup failed'
                )
        return image

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def create_game_delete_mutation_router(
    app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
):
    router = APIRouter()
    data = data_access or GameDeleteMutationData()

    @router.post('/delete_game/{game_uuid}')
    async def delete_game(game_uuid: str, request: Request):
        return await _handle(
            request, app=app, data=data, game_uuid=game_uuid,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    @router.post('/delete_folder')
    async def delete_folder(request: Request):
        return await _handle(
            request, app=app, data=data, game_uuid=None, folder_request=True,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    @router.post('/delete_full_game')
    async def delete_full_game(request: Request):
        return await _handle(
            request, app=app, data=data, game_uuid=None, full_disk=True,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    @router.post('/delete_image')
    async def delete_image(request: Request):
        return await _handle(
            request, app=app, data=data, image_request=True,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    return router


def mount_game_delete_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_game_delete_mutation_router(flask_app, **kwargs))
    return app


async def _handle(
    request, *, app, data, game_uuid=None, folder_request=False, full_disk=False,
    image_request=False, find_user, find_token,
    commit_token_touch, load_user_id, login_manager, database_scope,
):
    scope = database_scope(app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        from .csrf_compat import csrf_error_response

        csrf = None
        full_disk_payload = None
        full_disk_too_large = False
        if full_disk:
            from .library_admin_mutations import _json_object_or_form

            full_disk_payload, full_disk_too_large = await _json_object_or_form(
                request, app.config,
            )
        if auth.token is None:
            csrf_token = None
            if full_disk and request.headers.get('X-CSRFToken') is None:
                csrf_token = full_disk_payload.get('__form__', {}).get(
                    str(app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'),
                )
            csrf = csrf_error_response(
                request, auth.session_data, app.config, token=csrf_token,
            )
        if csrf is not None:
            response = csrf
        elif auth.user is None:
            response = _login_redirect(app, request, login_manager, auth)
        else:
            from oneirodex.utils.role_catalog import normalize_role

            role = normalize_role(getattr(auth.user, 'role', None) or '')
            if role != 'admin':
                response = _error('Admin required', 'forbidden', 403)
            elif auth.token is not None and not auth.has_scope('admin'):
                response = _error('This token does not have the admin scope', 'forbidden', 403)
            elif folder_request:
                response = await _delete_folder(request, app, data)
            elif full_disk:
                response = _delete_full_game(
                    app, data, full_disk_payload, too_large=full_disk_too_large,
                )
            elif image_request:
                response = await _delete_image(request, app, data)
            else:
                response = _delete(app, data, game_uuid)
        if auth.should_set_session_cookie:
            _set_session_cookie(response, app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(app.config).items():
            response.headers.setdefault(key, value)
        return response


def _delete(app, data, game_uuid):
    from werkzeug.exceptions import NotFound

    if data.scan_running():
        return _error(
            'A scan is running. Deleting games is available again as soon as it finishes.',
            'forbidden', 403,
        )
    try:
        data.delete_game(game_uuid, config=app.config)
    except NotFound:
        return _error('Game not found.', 'not_found', 404)
    except Exception:
        return _error("Couldn't remove that game. Nothing was changed.", 'internal', 500)
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload({'message': 'Game removed from library successfully.'}))


def _error(message, code, status, *, body_status=None):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(
        message, code=code, status=status, body_status=body_status,
    )
    return JSONResponse(payload, status_code=status)


async def _delete_folder(request, app, data):
    try:
        body = await request.json()
    except Exception:
        body = {}
    folder_path = body.get('folder_path') if isinstance(body, dict) else None
    if not folder_path:
        return _error('Path is required.', 'bad_request', 400, body_status='error')
    if data.scan_running():
        return _error(
            'A scan is running. Deleting is available again as soon as it finishes.',
            'forbidden', 403, body_status='error',
        )
    allowed_bases = data.allowed_bases(app)
    is_safe, _error_message = data.safe_path(folder_path, allowed_bases)
    if not is_safe:
        return _error('Access denied.', 'forbidden', 403, body_status='error')
    entry = data.folder_entry(folder_path)
    full_path = os.path.abspath(folder_path)
    if not data.path_exists(full_path):
        data.remove_folder_entry(entry)
        return _error(
            'The specified path does not exist. Entry removed if it was in the database.',
            'not_found', 404, body_status='error',
        )
    try:
        data.remove_path(full_path)
        if data.path_exists(full_path):
            return _error('Could not delete the item. Database entry retained.', 'internal', 500, body_status='error')
        data.remove_folder_entry(entry)
        from oneirodex.utils.api_contract import api_ok_payload

        return JSONResponse(api_ok_payload({
            'status': 'success',
            'message': 'Item deleted successfully. Database entry removed.',
        }))
    except PermissionError:
        return _error(
            'Failed to delete the item due to insufficient permissions. Database entry retained.',
            'forbidden', 403, body_status='error',
        )
    except Exception:
        rollback = getattr(data, 'rollback', None)
        if callable(rollback):
            rollback()
        return _error('Could not delete the item. Database entry retained.', 'internal', 500, body_status='error')


def _delete_full_game(app, data, payload, *, too_large=False):
    from pydantic import ValidationError

    from oneirodex.schemas.admin_game_delete import DeleteFullGameBody
    from oneirodex.utils.validation import format_validation_errors

    if too_large:
        return _error('Request body is too large.', 'bad_request', 413)
    form = payload.get('__form__', {}) if isinstance(payload, dict) else {}
    source = payload if isinstance(payload, dict) else {}
    body = dict(form) if form else dict(source)
    body.pop('__form__', None)
    body.pop(str(app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'), None)
    try:
        parsed = DeleteFullGameBody.model_validate(body)
    except ValidationError as exc:
        from oneirodex.utils.api_contract import api_error_payload

        response, status = api_error_payload(
            'Invalid request.', code='unprocessable',
            detail=format_validation_errors(exc),
        )
        return JSONResponse(response, status_code=status)

    if data.scan_running():
        return _error(
            'A scan is running. Deleting games is available again as soon as it finishes.',
            'forbidden', 403,
        )
    game = data.game(parsed.game_uuid)
    if game is None:
        return _error('Game not found.', 'not_found', 404)
    full_path = game.full_disk_path
    on_disk = bool(full_path) and data.path_exists(full_path)
    is_directory = on_disk and data.path_is_directory(full_path)
    try:
        if on_disk:
            allowed_bases = data.allowed_bases(app)
            is_safe, _error_message = data.safe_path(full_path, allowed_bases)
            if not is_safe:
                return _error('Access denied.', 'forbidden', 403)
            data.remove_path(full_path)
            if data.path_exists(full_path):
                raise OSError('Removal did not complete')
        data.delete_game(parsed.game_uuid, config=app.config)
    except Exception:
        rollback = getattr(data, 'rollback', None)
        if callable(rollback):
            rollback()
        return _error('Error deleting game from disk.', 'internal', 500)

    if not on_disk:
        message = 'Game was not present on disk; removed from the library.'
    elif is_directory:
        message = 'Game and its folder have been deleted successfully.'
    else:
        message = 'Game file has been deleted successfully.'
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload({'message': message}))


async def _delete_image(request, app, data):
    from pydantic import ValidationError

    from oneirodex.schemas.admin_game_images import DeleteGameImageBody
    from oneirodex.utils.validation import format_validation_errors

    content_type = (
        request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    )
    is_json = content_type == 'application/json' or (
        content_type.startswith('application/') and content_type.endswith('+json')
    )
    if is_json:
        try:
            body = await request.json()
        except Exception:
            body = {}
    else:
        body = {}
    try:
        parsed = DeleteGameImageBody.model_validate({} if body is None else body)
    except ValidationError as exc:
        from oneirodex.utils.api_contract import api_error_payload

        payload, status = api_error_payload(
            'Invalid request.', code='unprocessable',
            detail=format_validation_errors(exc),
        )
        return JSONResponse(payload, status_code=status)
    if data.scan_running():
        return _error(
            'A scan is running. Deleting images is available again as soon as it finishes.',
            'forbidden', 403,
        )
    try:
        image = data.delete_image_record_and_file(
            parsed.image_id, config=app.config,
        )
        if image is None:
            return _error('Image not found', 'not_found', 404)
    except Exception:
        rollback = getattr(data, 'rollback', None)
        if callable(rollback):
            rollback()
        return _error(
            'An unexpected error occurred while deleting the image',
            'internal', 500,
        )
    result = {'message': 'Image deleted successfully'}
    if parsed.is_cover:
        root_path = request.scope.get('root_path', '').rstrip('/')
        result['default_cover'] = f'{root_path}/static/newstyle/default_cover.jpg'
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(result))
