"""Native ASGI admin mutations for library creation and batch jobs.

All durable writes, scans, and deletion scheduling live behind
``LibraryAdminMutationData`` so route behavior can be tested with a fake.
"""
from __future__ import annotations

import json
import logging
import os
import base64
from contextlib import nullcontext
from io import BytesIO
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse

from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context

logger = logging.getLogger(__name__)


class LibraryAdminMutationData:
    """Production adapter; tests replace it to prevent every real side effect."""

    def preview_image(self, image_data: str) -> str:
        from PIL import Image as PILImage

        if image_data.startswith('data:image'):
            image_data = image_data.split(',', 1)[1]
        image_bytes = base64.b64decode(image_data)
        with PILImage.open(BytesIO(image_bytes)) as opened:
            image = opened.convert('RGBA')
            if image.width > 1024 or image.height > 1024:
                image.thumbnail((1024, 1024), PILImage.LANCZOS)
            output = BytesIO()
            image.save(output, 'PNG')
            return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()

    def library(self, library_uuid: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library

        return db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()

    def create(self, *, name: str, platform, scan_depth: int, watch_enabled,
               image_bytes: bytes | None, user, config, root_path: str = ''):
        from PIL import Image as PILImage

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library
        from oneirodex.utils.event_logging import log_system_event

        image_url = _static_url('newstyle/default_library.jpg', root_path)
        saved_path = None
        if image_bytes:
            with PILImage.open(BytesIO(image_bytes)) as opened:
                if opened.width * opened.height > 80_000_000:
                    raise ValueError('Library image dimensions are too large.')
                converted = opened.convert('RGBA')
                if converted.width > 1024 or converted.height > 1024:
                    converted.thumbnail((1024, 1024), PILImage.LANCZOS)
                image_name = f'{uuid4()}.png'
                image_dir = os.path.join(config['UPLOAD_FOLDER'], 'images')
                os.makedirs(image_dir, exist_ok=True)
                saved_path = os.path.join(image_dir, image_name)
                converted.save(saved_path, 'PNG')
                image_url = _static_url(f'library/images/{image_name}', root_path)

        library = Library(
            uuid=str(uuid4()), name=name, platform=platform, scan_depth=scan_depth,
            watch_enabled=watch_enabled, image_url=image_url,
        )
        db.session.add(library)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            if saved_path and os.path.exists(saved_path):
                os.remove(saved_path)
            raise
        log_system_event(
            f'Library created: {library.name}', event_type='library',
            event_level='information', audit_user=getattr(user, 'id', None),
        )
        return {'library_uuid': library.uuid, 'name': library.name}

    def update(self, library, *, name: str, platform, scan_depth: int,
               watch_enabled, image, app, user):
        from PIL import Image as PILImage

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.runtime_native.library_reads import LibraryReadData
        from oneirodex.utils.event_logging import log_system_event

        saved_path = None
        if image:
            filename, content = image
            with PILImage.open(BytesIO(content)) as opened:
                if opened.width * opened.height > 80_000_000:
                    raise ValueError('Library image dimensions are too large.')
                converted = opened.convert('RGBA')
                if converted.width > 1024 or converted.height > 1024:
                    converted.thumbnail((1024, 1024), PILImage.LANCZOS)
                image_name = f'{uuid4()}.png'
                image_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'images')
                os.makedirs(image_dir, exist_ok=True)
                saved_path = os.path.join(image_dir, image_name)
                converted.save(saved_path, 'PNG')
                library.image_url = f'/static/library/images/{image_name}'
        library.name = name
        library.platform = platform
        library.scan_depth = scan_depth
        library.watch_enabled = watch_enabled
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            if saved_path and os.path.exists(saved_path):
                os.remove(saved_path)
            raise
        log_system_event(
            f'Library updated: {library.name}', event_type='library',
            event_level='information', audit_user=getattr(user, 'id', None),
        )
        return LibraryReadData.public_fields(library)

    def start_scan(self, *, library, folder: str, options: dict, app,
                   database_scope=None):
        from oneirodex.utils.scan_queue import start_or_queue_scan

        return start_or_queue_scan(
            folder_path=folder, library_uuid=library.uuid,
            scan_mode=options['scan_mode'], remove_missing=options['remove_missing'],
            download_missing_images=options['download_missing_images'],
            force_updates_extras_scan=options['force_updates_extras'],
            queue_policy=options['queue_policy'], allow_force=True, app=app,
            database_scope=database_scope,
            fetch_hltb=options.get('fetch_hltb', False),
            force_hltb_refetch=options.get('force_hltb_refetch', False),
            schedule=options.get('schedule'),
            schedule_fields=options.get('schedule_fields'),
        )

    def fail_scan_for_legacy_mode(self, *, library, folder: str, options: dict):
        """Preserve v1.1.8's accepted-then-failed result for unknown modes.

        The old worker accepted the request, then failed because it had no
        branch for the mode. The native queue stores scan mode as a boolean,
        so persist the same terminal failure directly instead of silently
        converting the malformed request into a folder scan.
        """
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.scan_queue import create_scan_job_row

        job = create_scan_job_row(
            folder_path=folder,
            library_uuid=library.uuid,
            scan_mode='folders',
            remove_missing=options['remove_missing'],
            download_missing_images=options['download_missing_images'],
            force_updates_extras_scan=options['force_updates_extras'],
            schedule=options.get('schedule'),
            schedule_fields=options.get('schedule_fields'),
            status='Failed',
        )
        job.error_message = (
            "cannot access local variable 'game_names_with_paths' "
            'where it is not associated with a value'
        )
        db.session.commit()
        return {
            'status': 'started',
            'job_id': job.id,
            'position': None,
            'message': f'Scan started (job {job.id[:8]}…).',
        }

    def refresh_queue(self):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library

        libraries = db.session.execute(select(Library).order_by(Library.name.asc())).scalars().all()
        return [
            {'uuid': row.uuid, 'name': row.name, 'folder': row.last_scan_folder}
            for row in libraries if row.last_scan_folder
        ]

    def refresh_busy(self):
        from oneirodex.utils.scan_queue import is_scan_busy

        return is_scan_busy()

    def enqueue_refresh(self, queue):
        from oneirodex.utils.scan_queue import enqueue_library_refresh_jobs

        return enqueue_library_refresh_jobs(queue)

    def promote_refresh(self, app):
        from oneirodex.utils.scan_queue import promote_next_queued_scan

        return promote_next_queued_scan(app)

    def force_refresh(self, queue, app, *, database_scope=None):
        from threading import Thread

        from oneirodex.utilities import scan_and_add_games
        from contextlib import nullcontext

        def run_queue():
            scope = database_scope(app) if database_scope else nullcontext()
            # Native ASGI callers already supply a request-independent DB scope
            # and explicit app/config. Keep the Flask context only for legacy
            # callers that do not have that native boundary.
            app_scope = app.app_context() if database_scope is None else nullcontext()
            with app_scope, scope:
                for item in queue:
                    try:
                        scan_and_add_games(
                            item['folder'], scan_mode='folders', library_uuid=item['uuid'],
                            remove_missing=False, force_parallel=True,
                            database_scope=database_scope,
                            app=app,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("Refresh all failed for library %s", item['name'])

        Thread(target=run_queue, daemon=True, name='oneirodex-refresh-all').start()

    def resolve_scan_path(self, app, folder, library_root):
        from oneirodex.utils.library_roots import resolve_scan_path
        return resolve_scan_path(folder, library_root, app)

    def allowed_bases(self, app):
        from oneirodex.utils.security import get_allowed_base_directories
        return get_allowed_base_directories(app)

    def safe_path(self, path, allowed_bases):
        from oneirodex.utils.security import is_safe_path
        return is_safe_path(path, allowed_bases)

    def scan_mode_for_path(self, path, mode):
        from oneirodex.utils.services.scan_orchestration import resolve_scan_mode_for_path
        return resolve_scan_mode_for_path(path, mode)

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db
        db.session.rollback()

    def start_delete(self, library, app, *, database_scope=None):
        from oneirodex.utils.library_deletion import start_library_delete_job

        return start_library_delete_job(
            library, app=app, database_scope=database_scope,
        )

    def log_event(self, message, *, level, user):
        from oneirodex.utils.event_logging import log_system_event

        log_system_event(
            message, event_type='library', event_level=level,
            audit_user=getattr(user, 'id', None),
        )


def create_library_admin_mutations_router(
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
    data = data_access or LibraryAdminMutationData()

    @router.post('/api/library/preview-cropped-image')
    async def preview_cropped_image(request: Request):
        return await _handle(
            request, flask_app, data, action='preview_cropped', find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope,
        )

    @router.post('/api/admin/libraries')
    async def create_library(request: Request):
        return await _handle(
            request, flask_app, data, action='create', find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope,
        )

    @router.post('/admin/library/add')
    async def legacy_create_library(request: Request):
        return await _legacy_library_form(request, flask_app, data,
                                          action='create', library_uuid=None,
                                          find_user=find_user, find_token=find_token,
                                          commit_token_touch=commit_token_touch,
                                          load_user_id=load_user_id,
                                          login_manager=login_manager,
                                          database_scope=database_scope)

    @router.post('/admin/library/edit/{library_uuid}')
    async def legacy_update_library(library_uuid: str, request: Request):
        return await _legacy_library_form(request, flask_app, data,
                                          action='update', library_uuid=library_uuid,
                                          find_user=find_user, find_token=find_token,
                                          commit_token_touch=commit_token_touch,
                                          load_user_id=load_user_id,
                                          login_manager=login_manager,
                                          database_scope=database_scope)

    @router.post('/api/admin/libraries/scan')
    async def single_scan(request: Request):
        return await _handle(
            request, flask_app, data, action='single_scan',
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    @router.post('/api/admin/libraries/refresh_all')
    async def refresh_all(request: Request):
        return await _handle(
            request, flask_app, data, action='refresh_all',
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    @router.put('/api/admin/libraries/{library_uuid}')
    async def update_library(library_uuid: str, request: Request):
        return await _handle(
            request, flask_app, data, action='update', library_uuid=library_uuid,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
        )

    @router.post('/api/admin/libraries/batch/scan')
    async def batch_scan(request: Request):
        return await _handle(
            request, flask_app, data, action='scan', find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope,
        )

    @router.post('/api/admin/libraries/batch/delete')
    async def batch_delete(request: Request):
        return await _handle(
            request, flask_app, data, action='delete', find_user=find_user,
            find_token=find_token, commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
            database_scope=database_scope,
        )

    @router.post('/delete_full_library/{library_uuid}')
    async def delete_full_library(library_uuid: str, request: Request):
        return await _handle(
            request, flask_app, data, action='delete_single',
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            library_uuid=library_uuid,
        )

    return router


def mount_library_admin_mutations_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_library_admin_mutations_router(flask_app, **kwargs))
    return app


async def _legacy_library_form(request, app, data, *, action, library_uuid,
                               find_user, find_token, commit_token_touch,
                               load_user_id, login_manager, database_scope):
    """Keep the old multipart form contract on the native admin runtime."""
    from contextlib import nullcontext

    from starlette.datastructures import UploadFile

    from .csrf_compat import csrf_error_response
    from .request_auth import _lifetime_seconds
    from .session_compat import load_session_cookie
    from .oidc_status import _login_redirect
    from oneirodex.platform import LibraryPlatform
    from oneirodex.utils.role_catalog import normalize_role
    from starlette.responses import HTMLResponse

    target = '/admin/library/add' if action == 'create' else f'/admin/library/edit/{library_uuid}'
    scope = database_scope(app) if database_scope else nullcontext()
    with scope:
        limit = min(int(app.config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024),
                    32 * 1024 * 1024)
        content_length = request.headers.get('content-length')
        try:
            too_large = content_length is not None and int(content_length) > limit
        except (TypeError, ValueError):
            too_large = True
        raw_chunks = []
        raw_size = 0
        if not too_large:
            async for chunk in request.stream():
                raw_size += len(chunk)
                if raw_size > limit:
                    too_large = True
                    raw_chunks = []
                    break
                raw_chunks.append(chunk)
        if too_large:
            form = None
            raw_image = None
            filename = ''
            form_values = {}
        else:
            replay = Request(request.scope, receive=_body_receive(b''.join(raw_chunks)))
            form = await replay.form(max_files=1, max_fields=20, max_part_size=64 * 1024)
            form_values = {key: value for key, value in form.items() if not isinstance(value, UploadFile)}
            upload = form.get('image')
            raw_image = None
            filename = ''
            if isinstance(upload, UploadFile) and upload.filename:
                filename = upload.filename
                raw_image = await upload.read(10 * 1024 * 1024 + 1)

        try:
            cookie_name = str(app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name), app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                fallback_secret_keys=app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            response = csrf_error_response(
                request, session_data, app.config,
                token=str(form_values.get('csrf_token') or '') if form_values else None,
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
                    response = _error('Admin required', 'forbidden', 403)

            message = None
            category = 'error'
            response_status = 200
            if response is None:
                if too_large:
                    message = 'Request body is too large.'
                elif raw_image is not None and len(raw_image) > 10 * 1024 * 1024:
                    message = 'File size is too large. Maximum allowed is 10 MB.'
                else:
                    name = str(form_values.get('name') or '').strip()
                    platform_key = str(form_values.get('platform') or '').strip()
                    try:
                        platform = LibraryPlatform[platform_key]
                    except KeyError:
                        platform = None
                    try:
                        depth = int(form_values.get('scan_depth') or 1)
                    except (TypeError, ValueError):
                        depth = 0
                    watch_raw = str(form_values.get('watch_enabled') or 'default')
                    if not name:
                        message = 'Please correct the errors below.'
                    elif len(name) > 255:
                        message = 'Please correct the errors below.'
                    elif platform is None:
                        # WTForms rejects values outside the SelectField choices
                        # before the legacy route reaches its explicit KeyError.
                        message = 'Please correct the errors below.'
                    elif depth not in (1, 2):
                        message = 'Please correct the errors below.'
                    else:
                        # WTForms SelectField accepts only its declared choice
                        # values on the legacy multipart form. Keep the more
                        # permissive boolean aliases on the JSON API, but do
                        # not silently accept them on this compatibility route.
                        if watch_raw not in ('default', 'on', 'off'):
                            watch = 'invalid'
                        else:
                            watch = _watch_value(watch_raw)
                        if watch == 'invalid':
                            message = 'Please correct the errors below.'
                        else:
                            image = None
                            if raw_image is not None:
                                extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
                                if extension not in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
                                    message = 'Please correct the errors below.'
                                else:
                                    from PIL import Image as PILImage, UnidentifiedImageError
                                    from io import BytesIO
                                    try:
                                        with PILImage.open(BytesIO(raw_image)) as opened:
                                            if opened.width * opened.height > 80_000_000:
                                                message = 'Library image dimensions are too large.'
                                            else:
                                                image = raw_image
                                    except (UnidentifiedImageError, OSError, ValueError):
                                        message = 'Please correct the errors below.'
                                        # v1.1.8 let corrupt image decoding escape
                                        # and returned HTTP 500. Keep the generic
                                        # response body, while matching that status.
                                        response_status = 500
                            if message is None:
                                try:
                                    if action == 'create':
                                        data.create(
                                            name=name, platform=platform, scan_depth=depth,
                                            watch_enabled=watch, image_bytes=image,
                                            user=auth.user, config=app.config,
                                            root_path=request.scope.get('root_path', ''),
                                        )
                                    else:
                                        library = data.library(str(library_uuid))
                                        if library is None:
                                            response = HTMLResponse(
                                                '<!doctype html>\n<html lang=en>\n'
                                                '<title>404 Not Found</title>\n'
                                                '<h1>Not Found</h1>\n'
                                                '<p>The requested URL was not found on the server. '
                                                'If you entered the URL manually please check your spelling '
                                                'and try again.</p>\n',
                                                status_code=404,
                                            )
                                        else:
                                            data.update(
                                                library, name=name, platform=platform,
                                                scan_depth=depth, watch_enabled=watch,
                                                image=(filename, image) if image is not None else None,
                                                app=app, user=auth.user,
                                            )
                                    if message is None and response is None:
                                        message, category = 'Library saved successfully!', 'success'
                                except Exception:
                                    from oneirodex.runtime_native.db_session import native_db as db

                                    db.session.rollback()
                                    message = 'Failed to save library. Please try again.'
            if response is None:
                notice = message or 'Please correct the errors below.'
                if category == 'success':
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append((category, notice))
                    auth.session_data['_flashes'] = flashes
                    response = RedirectResponse('/libraries', status_code=302)
                    _set_session_cookie(response, app, auth)
                else:
                    response = _legacy_library_form_error_response(
                        app, auth, category, notice, status_code=response_status,
                    )
            return response
        finally:
            if form is not None:
                await form.close()


def _legacy_library_form_error_response(
    app, auth, category: str, message: str, *, status_code: int = 200,
):
    """Render validation flashes inline, as the legacy library form did."""
    from pathlib import Path
    from starlette.responses import HTMLResponse

    from .admin_pilot import _shell_with_admin_flashes

    shell_path = (
        Path(__file__).resolve().parents[1]
        / 'static' / 'dist' / 'admin-pilot' / 'index.html'
    )
    try:
        shell = shell_path.read_text(encoding='utf-8')
    except OSError:
        shell = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<title>Libraries · Oneirodex Admin</title></head><body><main>'
            '<div id="admin-app-root"></div></main></body></html>'
        )
    previous_flashes = list(auth.session_data.pop('_flashes', []) or [])
    response = HTMLResponse(
        _shell_with_admin_flashes(shell, [*previous_flashes, (category, message)]),
        status_code=status_code, headers={'Cache-Control': 'no-store'},
    )
    if auth.should_set_session_cookie or previous_flashes:
        _set_session_cookie(response, app, auth)
    return response


async def _handle(request, flask_app, data, *, action, find_user, find_token,
                  commit_token_touch, load_user_id, login_manager, database_scope,
                  library_uuid=None):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        from .csrf_compat import csrf_error_response
        from .acquire_status import _login_redirect

        csrf_token = None
        delete_payload = None
        delete_too_large = False
        if action == 'delete_single':
            delete_payload, delete_too_large = await _json_object_or_form(request, flask_app.config)
            if auth.token is None and request.headers.get('X-CSRFToken') is None:
                form = delete_payload.get('__form__', {})
                csrf_token = form.get(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'))
        elif auth.token is None and request.headers.get('X-CSRFToken') is None:
            try:
                form = await request.form(max_files=0, max_fields=10, max_part_size=16 * 1024)
                csrf_token = form.get(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'))
            except Exception:
                pass
        response = csrf_error_response(
            request, auth.session_data, flask_app.config, token=csrf_token,
        ) if auth.token is None else None
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        if response is None:
            from oneirodex.utils.role_catalog import normalize_role

            if normalize_role(getattr(auth.user, 'role', None)) != 'admin' or (
                auth.token is not None and not auth.has_scope('admin')
            ):
                response = _error('Admin required', 'forbidden', 403)
        if response is None:
            if action == 'create':
                response = await _create(request, flask_app, data, auth.user)
            elif action == 'update':
                response = await _update(request, flask_app, data, auth.user, library_uuid)
            elif action == 'single_scan':
                response = await _single_scan(
                    request, flask_app, data, auth.user,
                    database_scope=database_scope,
                )
            elif action == 'refresh_all':
                response = await _refresh_all(request, flask_app, data, database_scope=database_scope)
            elif action == 'scan':
                response = await _scan(
                    request, flask_app, data, auth.user,
                    database_scope=database_scope,
                )
            elif action == 'delete_single':
                response = await _delete_single(
                    request, flask_app, data, auth.user, library_uuid,
                    database_scope=database_scope, payload=delete_payload,
                    too_large=delete_too_large,
                )
            elif action == 'preview_cropped':
                response = await _preview_cropped_image(request, data)
            else:
                response = await _delete(
                    request, data, auth.user, flask_app,
                    database_scope=database_scope,
                )
        if auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        return response


async def _preview_cropped_image(request, data):
    from oneirodex.schemas.admin_libraries import PreviewCroppedImageBody
    from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
    from oneirodex.utils.validation import format_validation_errors
    from pydantic import ValidationError

    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        model = PreviewCroppedImageBody.model_validate(body if isinstance(body, dict) else {})
    except ValidationError as exc:
        payload, status = api_error_payload(
            'Invalid request.', code='unprocessable', detail=format_validation_errors(exc),
        )
        return JSONResponse(payload, status_code=status)
    try:
        preview_url = data.preview_image(model.image_data)
    except Exception:
        return _error('Failed to process image', 'internal', 500)
    return JSONResponse(api_ok_payload({
        'status': 'success', 'preview_url': preview_url,
        'message': 'Image processed successfully',
    }))


async def _create(request, app, data, user):
    from oneirodex.platform import LibraryPlatform

    payload, image, too_large = await _create_payload(request, app.config)
    if too_large:
        return _error('Request body is too large.', 'bad_request', 413)
    name = str(payload.get('name') or '').strip()
    platform_key = str(payload.get('platform') or '').strip()
    try:
        depth = int(payload.get('scan_depth', 1))
        watch = _watch_value(payload.get('watch_enabled', 'default'))
    except (TypeError, ValueError):
        return _error('Choose a supported scan depth and watch setting.', 'bad_request', 400)
    if not name or len(name) > 255:
        return _error('Library name is required and must be 255 characters or fewer.', 'bad_request', 400)
    if depth not in (1, 2):
        return _error('Scan depth must be 1 or 2.', 'bad_request', 400)
    try:
        platform = LibraryPlatform[platform_key]
    except KeyError:
        return _error('Choose a supported platform.', 'bad_request', 400)
    if image is not None:
        filename, content = image
        extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if extension not in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
            return _error('Choose a JPG, PNG, GIF, or WebP library image.', 'bad_request', 400)
        if len(content) > 10 * 1024 * 1024:
            return _error('Library image must be 10 MB or smaller.', 'bad_request', 400)
        from PIL import Image as PILImage, UnidentifiedImageError
        try:
            with PILImage.open(BytesIO(content)) as opened:
                if opened.width * opened.height > 80_000_000:
                    return _error('Library image dimensions are too large.', 'bad_request', 400)
        except (UnidentifiedImageError, OSError, ValueError):
            return _error('The uploaded library image could not be read.', 'bad_request', 400)
    try:
        result = data.create(name=name, platform=platform, scan_depth=depth,
                             watch_enabled=watch, image_bytes=image[1] if image else None,
                             user=user, config=app.config,
                             root_path=request.scope.get('root_path', ''))
    except Exception:  # noqa: BLE001 — do not expose storage/database details
        return _error('Library could not be created.', 'internal', 500)
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload(result))


async def _update(request, app, data, user, library_uuid):
    from oneirodex.platform import LibraryPlatform

    library = data.library(library_uuid)
    if library is None:
        return _error('Library not found.', 'not_found', 404)
    payload, image, too_large = await _create_payload(request, app.config)
    if too_large:
        return _error('Request body is too large.', 'bad_request', 413)
    name = str(payload.get('name') or '').strip()
    if not name or len(name) > 255:
        return _error('Library name is required and must be 255 characters or fewer.', 'bad_request', 400)
    try:
        platform = LibraryPlatform[str(payload.get('platform') or '').strip()]
        depth = int(payload.get('scan_depth', 1))
        watch = _watch_value(payload.get('watch_enabled', 'default'))
    except (KeyError, TypeError, ValueError):
        return _error('Choose a supported platform, scan depth, and watch setting.', 'bad_request', 400)
    if depth not in (1, 2):
        return _error('Choose a supported platform, scan depth, and watch setting.', 'bad_request', 400)
    if image:
        filename, content = image
        extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if extension not in {'jpg', 'jpeg', 'png', 'gif', 'webp'}:
            return _error('Choose a JPG, PNG, GIF, or WebP library image.', 'bad_request', 400)
        if len(content) > 10 * 1024 * 1024:
            return _error('Library image must be 10 MB or smaller.', 'bad_request', 400)
        from PIL import Image as PILImage, UnidentifiedImageError
        try:
            with PILImage.open(BytesIO(content)) as opened:
                if opened.width * opened.height > 80_000_000:
                    return _error('Library image dimensions are too large.', 'bad_request', 400)
        except (UnidentifiedImageError, OSError, ValueError):
            return _error('The uploaded library image could not be read.', 'bad_request', 400)
    try:
        result = data.update(
            library, name=name, platform=platform, scan_depth=depth,
            watch_enabled=watch, image=image, app=app, user=user,
        )
    except Exception:  # noqa: BLE001 — do not expose storage/database details
        return _error('Library could not be saved.', 'internal', 500)
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload(result))


async def _single_scan(request, app, data, user, *, database_scope=None):
    from oneirodex.utils.scan_queue import (
        FORCE_PARALLEL_RISK, normalize_schedule_fields,
        parse_force_parallel, parse_queue_policy,
    )

    payload, too_large = await _input_payload(request, app.config)
    if too_large:
        return _error('Request body is too large.', 'bad_request', 413)
    form = payload.pop('__form__', {})
    def value(key, default=None):
        if key in payload:
            return payload.get(key)
        return form.get(key) or request.query_params.get(key) or default

    library_uuid = payload.get('library_uuid') or form.get('library_uuid') or request.query_params.get('library_uuid')
    if not library_uuid:
        return _error('library_uuid is required', 'bad_request', 400,
                      body_status='rejected', job_id=None, position=None)
    library = data.library(str(library_uuid))
    if library is None:
        return _error('Library not found', 'not_found', 404,
                      body_status='rejected', job_id=None, position=None)
    use_library_root = payload.get('use_library_root') is True
    if 'use_library_root' in payload and not isinstance(payload.get('use_library_root'), bool):
        return _error('use_library_root must be a boolean', 'bad_request', 400,
                      body_status='rejected', job_id=None, position=None)
    folder = payload.get('folder', '') if use_library_root else (
        payload.get('folder') or form.get('folder') or request.query_params.get('folder')
        or getattr(library, 'last_scan_folder', None)
    )
    if folder is None:
        folder = ''
    # v1.1.8 stringified JSON scalar folder values before storing the path.
    # Keep path allowlisting below; a malformed scalar can only address a
    # child of an allowed scan root after resolution.
    if not isinstance(folder, str):
        folder = str(folder)
    if not folder and not use_library_root:
        return _error(
            'No folder provided and library has no last_scan_folder. Run one Auto Scan first or pass folder.',
            'bad_request', 400, body_status='rejected', job_id=None, position=None,
        )
    folder = folder.strip()
    library_root = payload.get('library_root')
    if library_root is not None and not isinstance(library_root, str):
        return _error('library_root must be a string', 'bad_request', 400,
                      body_status='rejected', job_id=None, position=None)
    resolved, root_error = data.resolve_scan_path(app, folder, library_root)
    if root_error:
        return _error('Unknown scan location', 'bad_request', 400,
                      body_status='rejected', job_id=None, position=None)
    allowed = data.allowed_bases(app)
    if not allowed:
        return _error('Scan locations are not configured', 'unavailable', 503,
                      body_status='rejected', job_id=None, position=None)
    safe, _path_error = data.safe_path(resolved, allowed)
    if not safe:
        return _error('Access denied for this scan location', 'forbidden', 403,
                      body_status='rejected', job_id=None, position=None)
    scan_mode = value('scan_mode', 'folders') or 'folders'
    if not isinstance(scan_mode, str):
        scan_mode = str(scan_mode)
    invalid_scan_mode = scan_mode not in ('auto', 'folders', 'files')
    if invalid_scan_mode:
        scan_mode = 'folders'
    elif scan_mode == 'auto':
        scan_mode = data.scan_mode_for_path(resolved, scan_mode)
    force_raw = payload.get('force_parallel') if 'force_parallel' in payload else (form.get('force_parallel') or request.query_params.get('force_parallel'))
    policy_raw = payload.get('queue_policy') if 'queue_policy' in payload else (form.get('queue_policy') or request.query_params.get('queue_policy'))
    schedule = payload.get('schedule')
    if schedule is not None and not isinstance(schedule, str):
        return _error('schedule must be a string', 'bad_request', 400,
                      body_status='rejected', job_id=None, position=None)
    # Preserve non-empty SelectField values exactly so padded choices are
    # rejected like v1.1.8. Whitespace-only is still the optional "once" value.
    schedule = schedule if schedule and schedule.strip() else None
    interval_unit = payload.get('schedule_interval_unit')
    cron_expr = payload.get('schedule_cron')
    if interval_unit is not None and not isinstance(interval_unit, str):
        return _error('schedule_interval_unit must be a string', 'bad_request', 400,
                      body_status='rejected', job_id=None, position=None)
    if cron_expr is not None and not isinstance(cron_expr, str):
        return _error('schedule_cron must be a string', 'bad_request', 400,
                      body_status='rejected', job_id=None, position=None)
    schedule_fields = normalize_schedule_fields(
        schedule, interval_value=payload.get('schedule_interval_value'),
        interval_unit=interval_unit, cron_expr=cron_expr,
    )
    if schedule_fields.get('error'):
        return _error(schedule_fields['error'], 'bad_request', 400,
                      body_status='rejected', job_id=None, position=None)

    def flag(key, default=False):
        raw = payload.get(key) if key in payload else (form.get(key) or request.query_params.get(key))
        if raw is None:
            return default
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw != 0
        return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')

    options = {
        'scan_mode': scan_mode,
        'remove_missing': flag('remove_missing'),
        'download_missing_images': flag('download_missing_images'),
        'force_updates_extras': flag('force_updates_extras', flag('force_updates_extras_scan')),
        'fetch_hltb': flag('fetch_hltb'),
        'force_hltb_refetch': flag('force_hltb_refetch'),
        'queue_policy': parse_queue_policy(policy_raw, force_parallel=force_raw),
        'schedule': schedule,
        'schedule_fields': schedule_fields,
    }
    try:
        if invalid_scan_mode:
            result = data.fail_scan_for_legacy_mode(
                library=library, folder=resolved, options=options,
            )
        else:
            result = data.start_scan(
                library=library, folder=resolved, options=options, app=app,
                database_scope=database_scope,
            )
    except Exception:
        data.rollback()
        return _error('Scan request could not be queued.', 'internal', 500,
                      body_status='rejected', job_id=None, position=None)
    http = 200 if result.get('status') in ('started', 'queued') else 409
    if result.get('status') == 'started' and parse_force_parallel(force_raw):
        result = dict(result)
        result.setdefault('risk', FORCE_PARALLEL_RISK)
    if result.get('status') in ('started', 'queued'):
        from oneirodex.utils.api_contract import api_ok_payload
        return JSONResponse(api_ok_payload(result), status_code=http)
    extras = {key: val for key, val in result.items()
              if key not in ('ok', 'error', 'error_code', 'message', 'status')}
    return _error(result.get('message') or 'Scan rejected', 'conflict', http,
                  body_status='rejected', **extras)


async def _refresh_all(request, app, data, *, database_scope=None):
    from oneirodex.utils.scan_queue import FORCE_PARALLEL_RISK, parse_queue_policy

    payload, too_large = await _input_payload(request, app.config)
    if too_large:
        return _error('Request body is too large.', 'bad_request', 413)
    form = payload.get('__form__', {})
    force_raw = payload.get('force_parallel') if 'force_parallel' in payload else (
        form.get('force_parallel') or request.query_params.get('force_parallel')
    )
    policy_raw = payload.get('queue_policy') if 'queue_policy' in payload else (
        form.get('queue_policy') or request.query_params.get('queue_policy')
    )
    force = parse_queue_policy(policy_raw, force_parallel=force_raw) == 'force'
    try:
        queue = data.refresh_queue()
        if not queue:
            return _error(
                'No libraries have a remembered scan folder yet.', 'bad_request', 400,
                body_status='rejected',
                body_error=(
                    'No libraries have a remembered scan folder yet. '
                    'Run one Auto Scan per library first.'
                ),
                queued=[],
            )
        if force:
            data.force_refresh(queue, app, database_scope=database_scope)
            return _ok({
                'status': 'started', 'queued': queue, 'count': len(queue),
                'message': (
                    f'Refresh-all started for {len(queue)} libraries '
                    f'(sequential worker, force_parallel). {FORCE_PARALLEL_RISK}'
                ),
                'risk': FORCE_PARALLEL_RISK,
            })

        busy = data.refresh_busy()
        result = data.enqueue_refresh(queue)
        if not busy:
            promoted = data.promote_refresh(app)
            if promoted:
                result['status'] = 'started'
                result['job_id'] = promoted.id
                result['message'] = (
                    f'Refresh-all: started first of {len(queue)} queued library scan(s); '
                    'remaining stay Queued (FIFO).'
                )
                for item in result.get('jobs') or []:
                    if item.get('job_id') == promoted.id:
                        item['position'] = None
                        item['status'] = 'started'
                    elif item.get('position'):
                        item['position'] = max(1, int(item['position']) - 1)
        return _ok(result)
    except Exception:  # noqa: BLE001 — keep queue internals out of the response
        import logging

        logging.getLogger(__name__).exception('Native refresh-all request failed')
        return _error('Refresh-all could not be queued.', 'internal', 500)


async def _scan(request, app, data, user, *, database_scope=None):
    from oneirodex.utils.library_batch import (
        LIBRARY_BATCH_UUID_CAP, parse_bool_flag, parse_library_uuids,
    )
    from oneirodex.utils.scan_queue import FORCE_PARALLEL_RISK, parse_force_parallel, parse_queue_policy

    body = await _json_object(request)
    uuids, err = parse_library_uuids(body)
    if err:
        return _rejected(err[0], err[1])
    if len(uuids) > LIBRARY_BATCH_UUID_CAP:
        return _cap_error(LIBRARY_BATCH_UUID_CAP)
    folders_map = body.get('folders') if isinstance(body.get('folders'), dict) else {}
    force_raw = body.get('force_parallel')
    options = {
        'scan_mode': body.get('scan_mode') or 'folders',
        'remove_missing': parse_bool_flag(body.get('remove_missing'), default=False),
        'download_missing_images': parse_bool_flag(body.get('download_missing_images'), default=False),
        'force_updates_extras': parse_bool_flag(body.get('force_updates_extras'), default=False),
        'queue_policy': parse_queue_policy(body.get('queue_policy'), force_parallel=force_raw),
    }
    started = queued = skipped = failed = 0
    results = []
    for uuid in uuids:
        library = data.library(uuid)
        if library is None:
            results.append({'uuid': uuid, 'ok': False, 'error': 'not_found', 'status': 'rejected'})
            failed += 1
            continue
        folder = folders_map.get(uuid) or body.get('folder') or getattr(library, 'last_scan_folder', None)
        if not folder:
            results.append({'uuid': uuid, 'name': library.name, 'ok': False, 'error': 'no_scan_folder',
                            'status': 'skipped', 'message': 'No folder provided and library has no last_scan_folder. Run one Auto Scan first or pass folder/folders.'})
            skipped += 1
            continue
        try:
            outcome = data.start_scan(
                library=library, folder=folder, options=options, app=app,
                database_scope=database_scope,
            )
            status = outcome.get('status')
            row = {'uuid': uuid, 'name': library.name, 'ok': status in ('started', 'queued'),
                   'status': status, 'job_id': outcome.get('job_id'), 'position': outcome.get('position'),
                   'message': outcome.get('message'), 'coalesced': outcome.get('coalesced')}
            if status == 'started' and parse_force_parallel(force_raw):
                row['risk'] = FORCE_PARALLEL_RISK
            if status == 'started': started += 1
            elif status == 'queued': queued += 1
            else:
                failed += 1
                row['ok'] = False
                row['error'] = outcome.get('message') or status or 'rejected'
            results.append(row)
        except Exception:  # preserve per-row partial success without exposing paths
            results.append({'uuid': uuid, 'name': library.name, 'ok': False,
                            'error': 'internal', 'status': 'error'})
            failed += 1
    data.log_event(f"Batch library scan by {getattr(user, 'name', 'admin')}: started={started} queued={queued} skipped={skipped} failed={failed}", level='information', user=user)
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload({'started': started, 'queued': queued, 'skipped': skipped,
                                        'failed': failed, 'count': len(uuids), 'results': results}))


async def _delete_single(request, app, data, user, library_uuid, *, database_scope=None,
                         payload=None, too_large=False):
    from oneirodex.utils.library_batch import (
        parse_bool_flag, parse_confirm_names, require_confirm_or_force,
    )
    from oneirodex.utils.api_contract import api_ok_payload, api_error_payload

    if not library_uuid:
        return _error('No library specified', 'bad_request', 400, body_status='error')
    library = data.library(library_uuid)
    if library is None:
        return _error('Library not found', 'not_found', 404, body_status='error')
    if too_large:
        return _error('Request body is too large.', 'bad_request', 413)
    form = payload.get('__form__', {})
    force_raw = payload.get('force') if 'force' in payload else (
        payload.get('force_delete') if 'force_delete' in payload else
        (form.get('force') or form.get('force_delete')
         or request.query_params.get('force') or request.query_params.get('force_delete'))
    )
    confirm_raw = payload.get('confirm_name') if 'confirm_name' in payload else (
        form.get('confirm_name') or request.query_params.get('confirm_name')
    )
    if force_raw is not None or confirm_raw is not None:
        force = parse_bool_flag(force_raw, default=False)
        confirm_names = parse_confirm_names(payload)
        confirm_error = require_confirm_or_force(
            library_uuid=library.uuid, library_name=library.name, force=force,
            confirm_names=confirm_names,
            single_confirm_name=str(confirm_raw) if confirm_raw is not None else None,
        )
        if confirm_error:
            message = (
                'Type the exact library name to confirm, or pass force=true '
                '(admin + CSRF still required).'
                if confirm_error == 'confirm_name_required'
                else 'confirm_name does not match library name.'
            )
            body, status = api_error_payload(
                message, code='bad_request', body_status='error',
                body_error=confirm_error,
                expected_name=library.name if confirm_error == 'confirm_name_mismatch' else None,
            )
            return JSONResponse(body, status_code=status)
    else:
        force = False
    try:
        job_id = data.start_delete(library, app, database_scope=database_scope)
    except Exception:
        data.rollback()
        return _error('Library deletion could not be started.', 'unavailable', 503)
    return JSONResponse(api_ok_payload({'status': 'started', 'job_id': job_id}))


async def _json_object_or_form(request, config):
    is_json = 'json' in request.headers.get('content-type', '').lower()
    limit = min(int(config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024), 32 * 1024 * 1024)
    if not is_json:
        limit = min(limit, 64 * 1024)
    try:
        if int(request.headers.get('content-length') or '0') > limit:
            return ({}, True) if is_json else ({'__form__': {}}, True)
    except (TypeError, ValueError):
        return ({}, True) if is_json else ({'__form__': {}}, True)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            return ({}, True) if is_json else ({'__form__': {}}, True)
    if is_json:
        try:
            value = json.loads(raw or b'{}')
        except (TypeError, ValueError, UnicodeDecodeError):
            value = {}
        return (value if isinstance(value, dict) else {}), False
    content_type = request.headers.get('content-type', '').lower()
    if not content_type.startswith(('multipart/form-data', 'application/x-www-form-urlencoded')):
        return {'__form__': {}}, False
    replay = Request(request.scope, receive=_body_receive(bytes(raw)))
    try:
        form = await replay.form(max_files=0, max_fields=10, max_part_size=16 * 1024)
    except Exception:
        return {'__form__': {}}, False
    try:
        return {'__form__': dict(form)}, False
    finally:
        await form.close()


async def _delete(request, data, user, flask_app, *, database_scope=None):
    from oneirodex.utils.library_batch import (
        LIBRARY_BATCH_DELETE_CAP, parse_bool_flag, parse_confirm_names,
        parse_library_uuids, require_confirm_or_force,
    )
    body = await _json_object(request)
    uuids, err = parse_library_uuids(body)
    if err:
        return _rejected(err[0], err[1])
    if len(uuids) > LIBRARY_BATCH_DELETE_CAP:
        return _cap_error(LIBRARY_BATCH_DELETE_CAP)
    force = parse_bool_flag(body.get('force') if 'force' in body else body.get('force_delete'), default=False)
    names = parse_confirm_names(body)
    single = str(body['confirm_name']) if body.get('confirm_name') is not None else None
    if not force and not names and not (single and single.strip()):
        from oneirodex.utils.api_contract import api_error_payload
        payload, status = api_error_payload(
            'Provide confirm_names {uuid: exact library name} for each selection, or force=true to skip typed confirmation (admin + CSRF still required).',
            code='bad_request', body_status='rejected', body_error='confirm_name_required',
        )
        return JSONResponse(payload, status_code=status)
    started = failed = 0
    results = []
    for uuid in uuids:
        library = data.library(uuid)
        if library is None:
            results.append({'uuid': uuid, 'ok': False, 'error': 'not_found', 'status': 'rejected'})
            failed += 1
            continue
        confirm_err = require_confirm_or_force(library_uuid=uuid, library_name=library.name,
                                               force=force, confirm_names=names,
                                               single_confirm_name=single)
        if confirm_err:
            results.append({'uuid': uuid, 'name': library.name, 'ok': False, 'error': confirm_err,
                            'status': 'rejected', 'expected_name': library.name if confirm_err == 'confirm_name_mismatch' else None})
            failed += 1
            continue
        try:
            job_id = data.start_delete(
                library, flask_app, database_scope=database_scope,
            )
            started += 1
            results.append({'uuid': uuid, 'name': library.name, 'ok': True, 'status': 'started',
                            'job_id': job_id, 'force': force})
        except Exception:
            results.append({'uuid': uuid, 'name': library.name, 'ok': False,
                            'error': 'internal', 'status': 'error'})
            failed += 1
    data.log_event(f"Batch library delete by {getattr(user, 'name', 'admin')}: started={started} failed={failed} force={force}",
                   level='warning' if force else 'information', user=user)
    return JSONResponse({'ok': started > 0, 'started': started, 'failed': failed,
                         'count': len(uuids), 'force': force, 'results': results,
                         'progress_hint': {'sse': '/delete_library_progress/<job_id>',
                                           'poll': '/check_deletion_progress/<job_id>'}},
                        status_code=200 if started else 400)


async def _create_payload(request, config):
    limit = min(int(config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024), 32 * 1024 * 1024)
    length = request.headers.get('content-length')
    try:
        if length is not None and int(length) > limit:
            return {}, None, True
    except (TypeError, ValueError):
        return {}, None, True
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return {}, None, True
        chunks.append(chunk)
    raw = b''.join(chunks)
    if size > limit:
        return {}, None, True
    content_type = request.headers.get('content-type', '').lower()
    if content_type.startswith('multipart/form-data'):
        replay = Request(request.scope, receive=_body_receive(raw))
        form = None
        try:
            form = await replay.form(max_files=1, max_fields=20)
            payload = dict(form)
            upload = form.get('image')
            image = (upload.filename or '', await upload.read()) if upload is not None and upload.filename else None
            return payload, image, False
        except Exception:
            return {}, None, False
        finally:
            if form is not None:
                await form.close()
    if 'json' in content_type:
        try:
            value = json.loads(raw or b'{}')
            return (value if isinstance(value, dict) else {}), None, False
        except (TypeError, ValueError):
            return {}, None, False
    return {}, None, False


def _body_receive(raw):
    sent = False
    async def receive():
        nonlocal sent
        if sent:
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        sent = True
        return {'type': 'http.request', 'body': raw, 'more_body': False}
    return receive


async def _json_object(request):
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _watch_value(raw):
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ('', 'null', 'none', 'default', 'follow', 'global'):
        return None
    if text in ('1', 'true', 'yes', 'on', 'enabled'):
        return True
    if text in ('0', 'false', 'no', 'off', 'disabled'):
        return False
    raise ValueError('Invalid watch_enabled')


def _rejected(payload, status):
    from oneirodex.utils.api_contract import api_error_payload
    message, token = payload.get('message') or payload.get('error') or 'Rejected', payload.get('error')
    extras = {key: value for key, value in payload.items()
              if key not in ('ok', 'error', 'message', 'status', 'success', 'error_code')}
    if token and token != message:
        extras['body_error'] = token
    codes = {400: 'bad_request', 403: 'forbidden', 404: 'not_found', 409: 'conflict', 500: 'internal'}
    body, code_status = api_error_payload(message, code=codes.get(status, 'bad_request'), status=status,
                                          body_status=payload.get('status', 'rejected'), **extras)
    return JSONResponse(body, status_code=code_status)


def _cap_error(cap):
    from oneirodex.utils.api_contract import api_error_payload
    body, status = api_error_payload(f'library_uuids cap is {cap}', code='bad_request',
                                     body_status='rejected', cap=cap)
    return JSONResponse(body, status_code=status)


def _error(message, code, status, **extras):
    from oneirodex.utils.api_contract import api_error_payload
    body, actual = api_error_payload(message, code=code, status=status, **extras)
    return JSONResponse(body, status_code=actual)


def _ok(payload, status=200):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload), status_code=status)


def _static_url(filename: str, root_path: str = '') -> str:
    from urllib.parse import quote

    prefix = str(root_path or '').strip('/')
    prefix = f'/{prefix}' if prefix else ''
    return f'{prefix}/static/{quote(filename.lstrip("/"), safe="/")}'


async def _input_payload(request, config):
    """Read the small JSON/form scan request without unbounded body buffering."""
    limit = min(int(config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024), 32 * 1024 * 1024)
    try:
        if int(request.headers.get('content-length') or '0') > limit:
            return {}, True
    except (TypeError, ValueError):
        return {}, True
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            return {}, True
    content_type = request.headers.get('content-type', '').lower()
    if 'json' in content_type:
        try:
            value = json.loads(raw or b'{}')
            return (value if isinstance(value, dict) else {}), False
        except (TypeError, ValueError, UnicodeDecodeError):
            return {}, False
    if content_type.startswith(('multipart/form-data', 'application/x-www-form-urlencoded')):
        replay = Request(request.scope, receive=_body_receive(bytes(raw)))
        form = None
        try:
            form = await replay.form(max_files=1, max_fields=100)
            return {'__form__': dict(form)}, False
        except Exception:
            return {'__form__': {}}, False
        finally:
            if form is not None:
                await form.close()
    return {}, False
