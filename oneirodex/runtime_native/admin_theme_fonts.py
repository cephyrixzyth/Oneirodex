"""FastAPI admin upload/delete actions for operator supplied theme fonts."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse
from werkzeug.datastructures import FileStorage

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


def create_admin_theme_font_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id=None,
    login_manager=None,
    database_scope=None,
    font_store=None,
) -> APIRouter:
    router = APIRouter()

    @router.post('/admin/api/theme/fonts')
    async def upload_font(request: Request):
        return await _handle(request, flask_app, 'upload', None, find_user, find_token,
                             commit_token_touch, load_user_id, login_manager,
                             database_scope, font_store)

    @router.delete('/admin/api/theme/fonts/{filename:path}')
    async def delete_font(filename: str, request: Request):
        return await _handle(request, flask_app, 'delete', filename, find_user, find_token,
                             commit_token_touch, load_user_id, login_manager,
                             database_scope, font_store)

    return router


async def _handle(
    request, flask_app, action, filename, find_user, find_token,
    commit_token_touch, load_user_id, login_manager, database_scope, font_store,
):
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
            payload, status = api_error_payload(
                'This token does not have the admin scope', code='forbidden',
            )
            response = JSONResponse(payload, status_code=status)
        else:
            form = None
            try:
                if action == 'upload':
                    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                    if content_type != 'multipart/form-data':
                        payload, status = api_error_payload(
                            'Choose a font file to upload.', code='bad_request',
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        limit = _max_bytes(flask_app.config)
                        form = await request.form(max_files=1, max_fields=4, max_part_size=limit)
                        from .csrf_compat import csrf_error_response
                        csrf = csrf_error_response(
                            request, auth.session_data, flask_app.config,
                            token=form.get('csrf_token'),
                        ) if auth.token is None else None
                        if csrf is not None:
                            response = csrf
                        else:
                            upload = form.get('file')
                            if upload is None or not hasattr(upload, 'file'):
                                payload, status = api_error_payload(
                                    'Choose a font file to upload.', code='bad_request',
                                )
                                response = JSONResponse(payload, status_code=status)
                            else:
                                store = font_store or _font_store()
                                wrapped = FileStorage(stream=upload.file, filename=upload.filename)
                                result = store.store(
                                    wrapped,
                                    configured_root=flask_app.config.get('FONT_PATH') or None,
                                    max_bytes=flask_app.config.get('FONT_MAX_BYTES'),
                                )
                                response = JSONResponse(api_ok_payload(result), status_code=201)
                else:
                    from .csrf_compat import csrf_error_response
                    csrf = csrf_error_response(request, auth.session_data, flask_app.config) \
                        if auth.token is None else None
                    if csrf is not None:
                        response = csrf
                    else:
                        store = font_store or _font_store()
                        removed = store.delete(
                            filename,
                            configured_root=flask_app.config.get('FONT_PATH') or None,
                        )
                        if not removed:
                            payload, status = api_error_payload('Font not found', code='not_found')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload({'removed': filename}))
            except ValueError as exc:
                payload, status = api_error_payload(str(exc), code='bad_request')
                response = JSONResponse(payload, status_code=status)
            except OSError:
                payload, status = api_error_payload(
                    'Could not write to the font folder', code='unavailable',
                )
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


def _max_bytes(config):
    from oneirodex.utils.theme_fonts import DEFAULT_FONT_MAX_BYTES
    try:
        value = int(config.get('FONT_MAX_BYTES') or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else DEFAULT_FONT_MAX_BYTES


class _FontStore:
    def store(self, file_storage, **kwargs):
        from oneirodex.utils.theme_fonts import store_font_file
        return store_font_file(file_storage, **kwargs)

    def delete(self, filename, **kwargs):
        from oneirodex.utils.theme_fonts import delete_font_file
        return delete_font_file(filename, **kwargs)


def _font_store():
    return _FontStore()


def mount_admin_theme_font_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_theme_font_router(flask_app, **kwargs))
    return app
