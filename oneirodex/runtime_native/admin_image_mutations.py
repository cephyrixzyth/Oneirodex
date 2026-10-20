"""Native FastAPI admin image queue mutation routes."""
from __future__ import annotations

import logging
import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class ImageMutationsData:
    def path_status(self, config):
        from oneirodex.utils.cover_selection import image_save_path_status
        return image_save_path_status(config)

    def delete(self, config, image_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Image

        image = db.session.get(Image, image_id)
        if image is None:
            return False
        staged_path = None
        image_path = None
        if image.is_downloaded and image.url:
            root = config.get('IMAGE_SAVE_PATH')
            if root:
                base = Path(root).resolve()
                image_path = (base / image.url).resolve()
                if image_path == base or base not in image_path.parents:
                    raise ValueError('Stored image path is invalid')
                if image_path.exists():
                    if not image_path.is_file():
                        image_path.unlink()
                    staged_path = image_path.with_name(
                        f'.{image_path.name}.delete-{uuid4().hex}'
                    )
                    os.replace(image_path, staged_path)
        try:
            db.session.delete(image)
            db.session.commit()
        except Exception:
            if staged_path is not None and staged_path.exists():
                try:
                    os.replace(staged_path, image_path)
                except OSError:
                    logging.getLogger(__name__).error(
                        'Could not restore image after a failed database delete'
                    )
            raise
        if staged_path is not None:
            try:
                staged_path.unlink()
            except OSError:
                # The database delete committed; report success and leave the
                # unreferenced file for operator cleanup rather than imply the
                # row is still present.
                logging.getLogger(__name__).warning(
                    'Image delete committed but staged file cleanup failed'
                )
        return True

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db
        db.session.rollback()

    def upload_single(self, app, game_uuid, filename, image_type, content):
        from datetime import datetime
        import uuid
        from io import BytesIO
        from pathlib import Path

        from PIL import Image as PILImage
        from sqlalchemy import select
        from werkzeug.utils import secure_filename

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Image
        from oneirodex.utils.image_kinds import SINGULAR_IMAGE_KINDS

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if game is None:
            return None
        safe_name = secure_filename(filename)
        extension = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
        if extension not in {'jpg', 'jpeg', 'png', 'gif'}:
            raise ValueError('Upload a JPG, PNG, or GIF.')
        if len(content) > 3 * 1024 * 1024:
            raise ValueError('File size exceeds the 3MB limit')
        try:
            with PILImage.open(BytesIO(content)) as opened:
                opened.verify()
            with PILImage.open(BytesIO(content)) as opened:
                if opened.width * opened.height > 60_000_000:
                    raise OverflowError('Image pixel limit exceeded')
                source_format = opened.format
                image = opened.copy()
        except OverflowError:
            raise ValueError('That image is too big. The limit is 60 megapixels.') from None
        except Exception as exc:
            from PIL import Image as PIL
            if isinstance(exc, PIL.DecompressionBombError):
                raise ValueError('Invalid image data') from None
            raise ValueError('Invalid image data') from None

        if image_type == 'cover' and (image.width > 1200 or image.height > 1600):
            image.thumbnail((1200, 1600), PILImage.LANCZOS)
        root = Path(app.config['IMAGE_SAVE_PATH']).resolve()
        root.mkdir(parents=True, exist_ok=True)
        if image_type in SINGULAR_IMAGE_KINDS:
            rows = db.session.execute(select(Image).filter_by(
                game_uuid=game_uuid, image_type=image_type,
            )).scalars().all()
            for row in rows:
                old_path = (root / row.url).resolve()
                if root not in old_path.parents:
                    raise ValueError('Stored image path is invalid')
                if old_path.is_file():
                    old_path.unlink()
                db.session.delete(row)
        if image_type in SINGULAR_IMAGE_KINDS:
            name = f'{game_uuid}_{image_type}_{uuid.uuid4().hex[:8]}.{extension}'
        else:
            name = f'{game_uuid}_{datetime.now().strftime("%Y%m%d%H%M%S")}_{uuid.uuid4().hex[:8]}.{extension}'
        target = (root / name).resolve()
        if root not in target.parents:
            raise ValueError('Image target is invalid')
        if image.width > 1200 or image.height > 1600:
            with target.open('wb') as output:
                image.save(output, format=source_format or None)
        else:
            target.write_bytes(content)
        row = Image(game_uuid=game_uuid, image_type=image_type, url=name)
        db.session.add(row)
        db.session.commit()
        return {
            'message': 'File uploaded successfully',
            'url': f'/static/library/images/{name}',
            'flash': 'Image uploaded successfully!',
            'image_id': row.id, 'image_type': image_type, 'kind': image_type,
        }

    def download_images(self, app, body, path_status):
        from datetime import datetime, timezone
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Image

        if 'image_ids' in body or body.get('retry_failed'):
            if body.get('retry_failed'):
                images = db.session.execute(select(Image).filter(
                    Image.is_downloaded.is_(False), Image.last_error.isnot(None),
                )).scalars().all()
            else:
                images = [
                    image for image in (db.session.get(Image, ident) for ident in body['image_ids'])
                    if image is not None
                ]
            downloaded, failed, errors = 0, 0, []
            for image in images:
                if image.is_downloaded:
                    continue
                if not image.download_url:
                    image.last_error = 'No download URL on record for this image.'
                    image.last_attempt_at = datetime.now(timezone.utc)
                    failed += 1
                    errors.append({'image_id': image.id, 'error': image.last_error})
                    continue
                image.last_attempt_at = datetime.now(timezone.utc)
                try:
                    from oneirodex.utils.functions import download_stored_image
                    target = os.path.join(app.config['IMAGE_SAVE_PATH'], image.url)
                    success, error = download_stored_image(image, target)
                except Exception as exc:  # noqa: BLE001
                    success, error = False, str(exc)
                if success:
                    image.is_downloaded = True
                    image.last_error = None
                    downloaded += 1
                else:
                    image.last_error = error or 'Download failed for an unknown reason.'
                    failed += 1
                    errors.append({'image_id': image.id, 'error': image.last_error})
            db.session.commit()
            message = f'Downloaded {downloaded} images'
            if failed:
                message += f', {failed} failed'
            return {
                'downloaded': downloaded, 'failed': failed, 'errors': errors,
                'message': message, 'image_save_path': path_status,
            }
        if 'batch_size' in body:
            from oneirodex.utils.game_core import download_pending_images
            count = download_pending_images(
                batch_size=body.get('batch_size', 10),
                delay_between_downloads=0.1, app=app, use_app_context=False,
            )
            return {
                'downloaded': count,
                'message': f'Downloaded {count} images',
                'image_save_path': path_status,
            }
        raise ValueError('No valid parameters provided')

    def upload_files(self, app, files, default_kind, explicit_uuid):
        import uuid
        from werkzeug.utils import secure_filename
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Image
        from oneirodex.utils.image_kinds import SINGULAR_IMAGE_KINDS, parse_image_kind

        allowed_ext = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
        save_dir = app.config['IMAGE_SAVE_PATH']
        os.makedirs(save_dir, exist_ok=True)
        stored, errors = [], []
        for item in files:
            raw = getattr(item, 'filename', '') or ''
            name = secure_filename(raw)
            stem, ext = os.path.splitext(name)
            ext = ext.lower()
            if ext not in allowed_ext:
                errors.append({'file': raw, 'error': 'Unsupported image type'})
                continue
            stream = item.file
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(0)
            if size <= 0:
                errors.append({'file': raw, 'error': 'Empty file'})
                continue
            if size > 10 * 1024 * 1024:
                errors.append({'file': raw, 'error': 'Larger than the 10MB limit'})
                continue
            parts = stem.split('_')
            candidate_uuid = explicit_uuid or (parts[0] if parts else '')
            kind_hint = parts[1] if (not explicit_uuid and len(parts) > 1) else default_kind
            try:
                kind = parse_image_kind(kind_hint, default=default_kind)
            except ValueError:
                kind = parse_image_kind(default_kind, default='cover')
            game = db.session.execute(select(Game).filter_by(uuid=candidate_uuid)).scalars().first()
            if not game:
                errors.append({'file': raw, 'error': 'No game matched this filename'})
                continue
            file_name = secure_filename(f'{game.uuid}_{kind}_{uuid.uuid4().hex[:8]}{ext}')
            try:
                target = Path(save_dir, file_name).resolve()
                root = Path(save_dir).resolve()
                if root not in target.parents:
                    raise OSError('Image target was outside the configured save folder')
                with target.open('wb') as output:
                    while chunk := stream.read(1024 * 1024):
                        output.write(chunk)
            except OSError:
                errors.append({'file': raw, 'error': 'Could not write image file'})
                continue
            if kind in SINGULAR_IMAGE_KINDS:
                for row in db.session.execute(select(Image).filter_by(
                    game_uuid=game.uuid, image_type=kind,
                )).scalars().all():
                    db.session.delete(row)
            db.session.add(Image(
                game_uuid=game.uuid, image_type=kind, url=file_name, is_downloaded=True,
            ))
            stored.append({
                'file': raw, 'game_uuid': game.uuid, 'game_name': game.name,
                'kind': kind, 'filename': file_name,
            })
        if stored:
            db.session.commit()
        return {'stored': len(stored), 'failed': len(errors), 'images': stored, 'errors': errors}


def create_admin_image_mutation_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, database_scope=None, data_access=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ImageMutationsData()

    @router.post('/upload_image/{game_uuid}')
    async def upload_single_image(game_uuid: str, request: Request):
        from .acquire_status import _login_redirect
        from oneirodex.utils.image_kinds import image_kinds_error_message, parse_image_kind
        from oneirodex.utils.scanning import is_scan_job_running

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            form = None
            response = _admin_denial(flask_app, request, auth, login_manager)
            content_type = request.headers.get('content-type', '').lower()
            if response is None and content_type.startswith('multipart/form-data'):
                from .bounded_multipart import (
                    InvalidContentLength, RequestBodyTooLarge, bounded_multipart_form,
                )

                try:
                    form = await bounded_multipart_form(
                        request, max_body_bytes=3 * 1024 * 1024 + 64 * 1024,
                        max_files=1, max_fields=12, max_part_size=64 * 1024,
                    )
                except RequestBodyTooLarge:
                    payload, status = _error('Upload exceeds the 3MB limit.', 'payload_too_large')
                    response = JSONResponse(payload, status_code=status)
                except InvalidContentLength:
                    payload, status = _error('Invalid request size.', 'bad_request')
                    response = JSONResponse(payload, status_code=status)
            if response is None:
                csrf = csrf_error_response(
                    request, auth.session_data, flask_app.config,
                    token=form.get('csrf_token') if form is not None else None,
                ) if auth.token is None else None
                if csrf is not None:
                    import json

                    from werkzeug.exceptions import BadRequest

                    try:
                        error_payload = json.loads(csrf.body or b'{}')
                    except (TypeError, ValueError, UnicodeDecodeError):
                        error_payload = {}
                    bad_request = BadRequest(
                        description=error_payload.get('message') or 'The CSRF token is invalid.',
                    ).get_response()
                    response = Response(
                        content=bad_request.get_data(),
                        status_code=bad_request.status_code,
                        media_type='text/html',
                    )
            try:
                if response is None and is_scan_job_running():
                    payload, status = _error(
                        'A scan is running. Image uploads are available again as soon as it finishes.',
                        'forbidden',
                    )
                    response = JSONResponse(payload, status_code=status)
                if response is None and form is None:
                    payload, status = _error('No file was included.', 'bad_request')
                    response = JSONResponse(payload, status_code=status)
                if response is None:
                    upload = form.get('file')
                    if upload is None or not getattr(upload, 'filename', ''):
                        payload, status = _error('No file was included.', 'bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            image_type = parse_image_kind(
                                form.get('image_type') or form.get('kind'),
                                default='screenshot',
                            )
                        except ValueError:
                            payload, status = _error(image_kinds_error_message(), 'bad_request')
                            response = JSONResponse(payload, status_code=status)
                        if response is None:
                            raw = await upload.read(3 * 1024 * 1024 + 1)
                            if not raw:
                                payload, status = _error('No file was selected.', 'bad_request')
                                response = JSONResponse(payload, status_code=status)
                            else:
                                try:
                                    result = data.upload_single(
                                        flask_app, game_uuid, upload.filename or '', image_type, raw,
                                    )
                                    if result is None:
                                        payload, status = _error('Game not found', 'not_found')
                                        response = JSONResponse(payload, status_code=status)
                                    else:
                                        from oneirodex.utils.api_contract import api_ok_payload
                                        response = JSONResponse(api_ok_payload(result))
                                except ValueError as exc:
                                    payload, status = _error(str(exc), 'bad_request')
                                    response = JSONResponse(payload, status_code=status)
                                except Exception:
                                    data.rollback()
                                    flask_app.logger.warning('Single game image upload failed')
                                    payload, status = _error('Could not upload the image', 'internal')
                                    response = JSONResponse(payload, status_code=status)
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
                from oneirodex.utils.security_headers import security_header_values
                for key, value in security_header_values(flask_app.config).items():
                    response.headers.setdefault(key, value)
                return response
            finally:
                if form is not None:
                    await form.close()

    @router.delete('/admin/api/delete_image/{image_id:int}')
    async def delete_image(image_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif normalize_role(getattr(auth.user, 'role', '') or '') != 'admin':
                payload, status = api_error_payload('Admin access required', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            else:
                csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
                    if auth.token is None else None
                if csrf is not None:
                    response = csrf
                else:
                    try:
                        removed = data.delete(flask_app.config, image_id)
                        if not removed:
                            payload, status = api_error_payload('Image not found', code='not_found')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload({'message': 'Image deleted successfully'}))
                    except Exception:
                        data.rollback()
                        payload, status = api_error_payload('Could not delete the image', code='internal')
                        response = JSONResponse(payload, status_code=status)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/admin/api/download_images')
    async def download_images(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            denied = _admin_denial(flask_app, request, auth, login_manager)
            if denied is not None:
                response = denied
            else:
                csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
                    if auth.token is None else None
                if csrf is not None:
                    response = csrf
                else:
                    try:
                        body = await request.json()
                    except Exception:
                        body = {}
                    body = body if isinstance(body, dict) else {}
                    path_status = data.path_status(flask_app.config)
                    if not path_status.get('writable') and (
                        'image_ids' in body or body.get('retry_failed') or 'batch_size' in body
                    ):
                        message = path_status.get('error') or 'IMAGE_SAVE_PATH is not writable'
                        payload, status = api_error_payload(
                            message, code='unavailable', image_save_path=path_status,
                            downloaded=0, failed=0, errors=[{'error': message}],
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            result = data.download_images(flask_app, body, path_status)
                            response = JSONResponse(api_ok_payload(result))
                        except ValueError as exc:
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        except Exception:
                            data.rollback()
                            payload, status = api_error_payload(
                                'Could not download the images', code='internal',
                                image_save_path=path_status,
                            )
                            response = JSONResponse(payload, status_code=status)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/admin/api/images/batch_upload')
    async def batch_upload(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            denied = _admin_denial(flask_app, request, auth, login_manager)
            if denied is not None:
                response = denied
                form = None
            else:
                form = None
                try:
                    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                    if content_type != 'multipart/form-data':
                        form = None
                        csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
                            if auth.token is None else None
                    else:
                        form = await request.form(max_files=100, max_fields=12, max_part_size=16 * 1024 * 1024)
                        csrf = csrf_error_response(
                            request, auth.session_data, flask_app.config,
                            token=form.get('csrf_token'),
                        ) if auth.token is None else None
                    if csrf is not None:
                        response = csrf
                    elif form is None:
                        payload, status = _error('Choose one or more image files.', 'bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        files = form.getlist('files') or form.getlist('file')
                        if not files:
                            payload, status = _error('Choose one or more image files.', 'bad_request')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            default_kind = form.get('image_type') or form.get('kind') or 'cover'
                            explicit_uuid = (form.get('game_uuid') or '').strip()
                            result = data.upload_files(
                                flask_app, files, default_kind, explicit_uuid,
                            )
                            from oneirodex.utils.api_contract import api_ok_payload
                            response = JSONResponse(api_ok_payload(result))
                except Exception:
                    data.rollback()
                    payload, status = _error('Could not upload the images', 'internal')
                    response = JSONResponse(payload, status_code=status)
                finally:
                    if form is not None:
                        await form.close()
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_admin_image_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_image_mutation_router(flask_app, **kwargs))
    return app


def _admin_denial(app, request, auth, login_manager):
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.role_catalog import normalize_role
    if auth.user is None:
        return _login_redirect(app, request, login_manager, auth)
    if normalize_role(getattr(auth.user, 'role', '') or '') != 'admin':
        payload, status = api_error_payload('Admin access required', code='forbidden')
        return JSONResponse(payload, status_code=status)
    if auth.token is not None and not auth.has_scope('admin'):
        payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
        return JSONResponse(payload, status_code=status)
    return None


def _error(message, code):
    from oneirodex.utils.api_contract import api_error_payload
    return api_error_payload(message, code=code)
