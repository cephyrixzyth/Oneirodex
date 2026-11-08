"""Native multipart upload for a member's account avatar."""
from __future__ import annotations

import asyncio
from contextlib import nullcontext
from io import BytesIO
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, RedirectResponse, Response
from werkzeug.datastructures import FileStorage

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response, csrf_html_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


_AVATAR_MAX_BODY_BYTES = 5 * 1024 * 1024 + 64 * 1024
_AVATAR_MAX_FILES = 1
_AVATAR_MAX_FIELDS = 1


class AccountAvatarUploadData:
    """Adapter over existing avatar validation, storage, and transaction code."""

    def save(self, file: FileStorage, user, flask_app):
        from oneirodex.utils.avatar import save_avatar

        return save_avatar(file, user, flask_app)

    def avatar_url(self, path: str):
        from oneirodex.utils.avatar import avatar_url

        return avatar_url(path)

    def prepare_cleanup(self, user, previous_path: str | None, new_path: str, flask_app) -> None:
        from oneirodex.runtime_native.db_session import native_db
        from oneirodex.utils.user_deletion import enqueue_avatar_replacement_cleanup

        enqueue_avatar_replacement_cleanup(
            native_db.session, flask_app, user.id, previous_path, new_path,
        )

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


async def _save_avatar_cancellable(data, file, user, flask_app, previous_path):
    """Finish and roll back staged avatar work before propagating cancellation.

    Starlette's thread-pool await can be cancelled while its synchronous worker
    keeps running. Avatar writes are staged before the route commits the user
    pointer, so let the worker finish, roll back its ORM mutation, and remove
    its newly written files before the request scope closes.
    """
    from starlette.concurrency import run_in_threadpool

    worker = asyncio.create_task(run_in_threadpool(data.save, file, user, flask_app))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            path, _error = await asyncio.shield(worker)
        except BaseException:
            data.rollback()
            raise
        try:
            data.rollback()
        finally:
            if path:
                from oneirodex.utils.avatar import finalize_avatar_change

                finalize_avatar_change(
                    flask_app, previous_path, path, committed=False,
                )
        raise


def create_account_avatar_upload_router(
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
    """Mount POST `/api/account/avatar` without Starlette's optional parser."""
    router = APIRouter()
    data = data_access or AccountAvatarUploadData()

    @router.post('/api/account/avatar')
    async def account_avatar(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                file, too_large, too_many_parts = await _avatar_upload(request)
                from oneirodex.utils.api_contract import api_error_payload, api_ok_payload

                if too_large:
                    payload, status = api_error_payload(
                        'Image is larger than the 5MB limit.', code='unprocessable'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif too_many_parts:
                    payload, status = api_error_payload(
                        'Avatar form contains too many parts.', code='payload_too_large'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif file is None:
                    payload, status = api_error_payload(
                        'Choose an image first.', code='bad_request'
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    previous_path = getattr(auth.user, 'avatarpath', None)
                    path, error = await _save_avatar_cancellable(
                        data, file, auth.user, flask_app, previous_path,
                    )
                    if error:
                        payload, status = api_error_payload(error, code='unprocessable')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            if hasattr(data, 'prepare_cleanup'):
                                data.prepare_cleanup(auth.user, previous_path, path, flask_app)
                            data.commit()
                        except Exception as exc:
                            data.rollback()
                            from oneirodex.utils.avatar import finalize_avatar_change

                            finalize_avatar_change(
                                flask_app, previous_path, path, committed=False,
                            )
                            flask_app.logger.warning('avatar commit failed: %s', exc)
                            payload, status = api_error_payload(
                                "Couldn't save that avatar. Try a different image.",
                                code='internal',
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            from oneirodex.utils.avatar import finalize_avatar_change

                            finalize_avatar_change(
                                flask_app, previous_path, path, committed=True,
                            )
                            response = JSONResponse(api_ok_payload({
                                'avatar_path': path,
                                'avatar_url': data.avatar_url(path),
                            }))

            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.api_route('/settings_profile_edit', methods=['GET', 'HEAD', 'POST'])
    async def legacy_profile_edit(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request,
                flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif request.method in ('GET', 'HEAD'):
                response = RedirectResponse('/library?account=avatar', status_code=302)
            else:
                file, csrf_token, too_large, too_many_parts = await _legacy_avatar_upload(
                    request, field_name=str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'),
                )
                response = None
                if too_many_parts:
                    response = _legacy_avatar_parts_limit_response()
                if response is None:
                    response = csrf_error_response(
                        request, auth.session_data, flask_app.config, token=csrf_token,
                    )
                    if response is not None:
                        response = csrf_html_error_response(response)
                if response is None:
                    if too_large:
                        _flash(auth.session_data, 'error', 'Image is larger than the 5MB limit.')
                    elif file is None:
                        if not getattr(auth.user, 'avatarpath', None):
                            from oneirodex.utils.avatar import DEFAULT_AVATAR
                            auth.user.avatarpath = DEFAULT_AVATAR
                        try:
                            data.commit()
                            _flash(auth.session_data, 'success', 'Profile updated successfully!')
                        except Exception:
                            data.rollback()
                            _flash(auth.session_data, 'error', 'Failed to update profile. Please try again.')
                    else:
                        previous_path = getattr(auth.user, 'avatarpath', None)
                        path, error = await _save_avatar_cancellable(
                            data, file, auth.user, flask_app, previous_path,
                        )
                        if error:
                            _flash(auth.session_data, 'error', error)
                        else:
                            try:
                                if hasattr(data, 'prepare_cleanup'):
                                    data.prepare_cleanup(auth.user, previous_path, path, flask_app)
                                data.commit()
                                from oneirodex.utils.avatar import finalize_avatar_change

                                finalize_avatar_change(
                                    flask_app, previous_path, path, committed=True,
                                )
                                _flash(auth.session_data, 'success', 'Profile updated successfully!')
                            except Exception:
                                data.rollback()
                                from oneirodex.utils.avatar import finalize_avatar_change

                                finalize_avatar_change(
                                    flask_app, previous_path, path, committed=False,
                                )
                                _flash(auth.session_data, 'error', 'Failed to update profile. Please try again.')
                    if response is None:
                        response = _legacy_redirect_response('/settings_profile_edit')

            if auth.should_set_session_cookie or auth.session_data.get('_flashes'):
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            response.headers.setdefault('Cache-Control', 'no-store')
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_account_avatar_upload_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_account_avatar_upload_router(flask_app, **kwargs))
    return app


async def _avatar_upload(request: Request) -> tuple[FileStorage | None, bool, bool]:
    """Read bounded multipart data and extract the `avatar` file."""
    file, _csrf_token, too_large, too_many_parts = await _read_avatar_form(request)
    return file, too_large, too_many_parts


async def _read_avatar_form(
    request: Request, *, csrf_field: str | None = None,
) -> tuple[FileStorage | None, str | None, bool, bool]:
    """Parse avatar multipart data with body, file, and field limits."""
    content_type = request.headers.get('content-type', '')
    if not content_type.lower().startswith('multipart/form-data'):
        return None, None, False, False

    from .bounded_multipart import (
        InvalidContentLength,
        RequestBodyTooLarge,
        bounded_multipart_form,
    )

    try:
        form = await bounded_multipart_form(
            request,
            max_body_bytes=_AVATAR_MAX_BODY_BYTES,
            max_files=_AVATAR_MAX_FILES,
            max_fields=_AVATAR_MAX_FIELDS,
            max_part_size=_AVATAR_MAX_BODY_BYTES,
        )
    except (InvalidContentLength, RequestBodyTooLarge):
        return None, None, True, False
    except HTTPException as exc:
        if exc.status_code == 400 and str(exc.detail).startswith((
            'Too many files.', 'Too many fields.',
        )):
            return None, None, False, True
        return None, None, False, False

    file = None
    csrf_token = None
    try:
        for name, value in form.multi_items():
            if csrf_field is not None and name == csrf_field and isinstance(value, str):
                csrf_token = value
            elif name == 'avatar' and isinstance(value, UploadFile):
                payload = await value.read()
                file = FileStorage(
                    stream=BytesIO(payload),
                    filename=value.filename or '',
                    content_type=value.content_type or 'application/octet-stream',
                )
    finally:
        await form.close()
    return file, csrf_token, False, False


async def _legacy_avatar_upload(
    request: Request, *, field_name: str = 'csrf_token',
) -> tuple[FileStorage | None, str | None, bool, bool]:
    """Read the classic multipart form, including its hidden CSRF field."""
    return await _read_avatar_form(request, csrf_field=field_name)


def _legacy_avatar_parts_limit_response() -> Response:
    """Return Werkzeug's standard HTML 413 page without trusting a partial form."""
    from werkzeug.exceptions import RequestEntityTooLarge

    response = RequestEntityTooLarge().get_response()
    return Response(
        content=response.get_data(),
        status_code=response.status_code,
        media_type='text/html',
    )


def _flash(session_data, category, message):
    flashes = list(session_data.get('_flashes') or [])
    flashes.append((category, message))
    session_data['_flashes'] = flashes


def _legacy_redirect_response(location: str) -> Response:
    """Keep Werkzeug's HTML redirect response for classic form submissions."""
    from werkzeug.utils import redirect

    legacy_response = redirect(location)
    return Response(
        content=legacy_response.get_data(),
        status_code=legacy_response.status_code,
        headers=dict(legacy_response.headers),
    )
