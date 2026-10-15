"""Native multipart upload for a member's account avatar."""
from __future__ import annotations

from contextlib import nullcontext
from email import policy
from email.parser import BytesParser
from io import BytesIO
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse
from werkzeug.datastructures import FileStorage

from .acquire_status import _login_redirect
from .csrf_compat import csrf_error_response
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class AccountAvatarUploadData:
    """Adapter over existing avatar validation, storage, and transaction code."""

    def save(self, file: FileStorage, user, flask_app):
        from oneirodex.utils.avatar import save_avatar

        return save_avatar(file, user, flask_app)

    def avatar_url(self, path: str):
        from oneirodex.utils.avatar import avatar_url

        return avatar_url(path)

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


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
                file, too_large = await _avatar_upload(request)
                from oneirodex.utils.api_contract import api_error_payload, api_ok_payload

                if too_large:
                    payload, status = api_error_payload(
                        'Image is larger than the 5MB limit.', code='unprocessable'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif file is None:
                    payload, status = api_error_payload(
                        'Choose an image first.', code='bad_request'
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    path, error = data.save(file, auth.user, flask_app)
                    if error:
                        payload, status = api_error_payload(error, code='unprocessable')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            data.commit()
                        except Exception as exc:
                            data.rollback()
                            flask_app.logger.warning('avatar commit failed: %s', exc)
                            payload, status = api_error_payload(
                                "Couldn't save that avatar. Try a different image.",
                                code='internal',
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
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
                file, csrf_token, too_large = await _legacy_avatar_upload(
                    request, field_name=str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token'),
                )
                response = csrf_error_response(
                    request, auth.session_data, flask_app.config, token=csrf_token,
                )
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
                        path, error = data.save(file, auth.user, flask_app)
                        if error:
                            _flash(auth.session_data, 'error', error)
                        else:
                            try:
                                data.commit()
                                _flash(auth.session_data, 'success', 'Profile updated successfully!')
                            except Exception:
                                data.rollback()
                                _flash(auth.session_data, 'error', 'Failed to update profile. Please try again.')
                    response = RedirectResponse('/library?account=avatar', status_code=302)

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


async def _avatar_upload(request: Request) -> tuple[FileStorage | None, bool]:
    """Read a bounded multipart body and extract the first `avatar` file."""
    content_type = request.headers.get('content-type', '')
    if not content_type.lower().startswith('multipart/form-data'):
        return None, False

    try:
        from werkzeug.http import parse_options_header

        _media_type, options = parse_options_header(content_type)
        boundary = options.get('boundary')
        if not boundary or len(boundary) > 200:
            return None, False
        boundary_bytes = boundary.encode('ascii')
    except (UnicodeEncodeError, ValueError, TypeError):
        return None, False

    # File size is validated by save_avatar. This envelope cap prevents an
    # unbounded body or unrelated fields from being buffered in memory.
    max_body = 5 * 1024 * 1024 + 64 * 1024
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_body:
            return None, True

    message = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: multipart/form-data; boundary='
        + boundary_bytes
        + b'\r\nMIME-Version: 1.0\r\n\r\n'
        + bytes(body)
    )
    if not message.is_multipart():
        return None, False
    for part in message.iter_parts():
        if part.get_content_disposition() != 'form-data':
            continue
        if part.get_param('name', header='content-disposition') != 'avatar':
            continue
        filename = part.get_filename() or ''
        payload = part.get_payload(decode=True) or b''
        return FileStorage(
            stream=BytesIO(payload), filename=filename,
            content_type=part.get_content_type(),
        ), False
    return None, False


async def _legacy_avatar_upload(
    request: Request, *, field_name: str = 'csrf_token',
) -> tuple[FileStorage | None, str | None, bool]:
    """Read the classic multipart form, including its hidden CSRF field."""
    content_type = request.headers.get('content-type', '')
    if not content_type.lower().startswith('multipart/form-data'):
        return None, None, False
    try:
        from werkzeug.http import parse_options_header

        _media_type, options = parse_options_header(content_type)
        boundary = options.get('boundary')
        if not boundary or len(boundary) > 200:
            return None, None, False
        boundary_bytes = boundary.encode('ascii')
    except (UnicodeEncodeError, ValueError, TypeError):
        return None, None, False
    max_body = 5 * 1024 * 1024 + 64 * 1024
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_body:
            return None, None, True
    message = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: multipart/form-data; boundary=' + boundary_bytes
        + b'\r\nMIME-Version: 1.0\r\n\r\n' + bytes(body)
    )
    if not message.is_multipart():
        return None, None, False
    csrf_token = None
    file = None
    for part in message.iter_parts():
        if part.get_content_disposition() != 'form-data':
            continue
        name = part.get_param('name', header='content-disposition')
        if name == field_name and not part.get_filename():
            csrf_token = (part.get_payload(decode=True) or b'').decode('utf-8', 'replace')
        elif name == 'avatar' and part.get_filename():
            file = FileStorage(
                stream=BytesIO(part.get_payload(decode=True) or b''),
                filename=part.get_filename() or '',
                content_type=part.get_content_type(),
            )
    return file, csrf_token, False


def _flash(session_data, category, message):
    flashes = list(session_data.get('_flashes') or [])
    flashes.append((category, message))
    session_data['_flashes'] = flashes
