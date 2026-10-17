"""Native read-only admin theme inventory endpoint."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class AdminThemesData:
    def payload(self, app, user) -> dict:
        from oneirodex.utils.themes import ThemeManager

        manager = ThemeManager(app)
        preference = getattr(user, 'preferences', None)
        active = getattr(preference, 'theme', None) or 'default'
        return {
            'themes': manager.get_installed_themes(),
            'default_theme': manager.get_default_theme(),
            'active_theme': active,
        }

    def upload(self, app, user, filename: str, content: bytes):
        from io import BytesIO
        from werkzeug.datastructures import FileStorage

        from oneirodex.utils.theme_validation import is_valid_theme_name, validate_theme_file
        from oneirodex.utils.themes import ThemeManager

        upload = FileStorage(stream=BytesIO(content), filename=filename)
        valid, reason = validate_theme_file(upload)
        if not valid:
            return None, (reason or 'Invalid theme ZIP', 'bad_request')
        manager = ThemeManager(app)
        try:
            result = manager.upload_theme(upload)
            if not result:
                return None, ('Theme upload failed. Check the ZIP contents and try again.', 'bad_request')
            valid_name, reason = is_valid_theme_name(result.get('name', ''))
            if not valid_name:
                from werkzeug.utils import secure_filename

                try:
                    manager.delete_themefile(secure_filename(str(result.get('name', ''))))
                except Exception:
                    app.logger.exception('Could not clean up rejected theme upload')
                return None, (reason or 'Invalid theme name', 'bad_request')
        except ValueError as exc:
            return None, (str(exc), 'bad_request')
        except Exception:
            app.logger.exception('Theme upload failed')
            return None, ('Theme upload failed. Please try again.', 'internal')
        return {'status': 'uploaded', 'theme': result, **self.payload(app, user)}, None

    def delete(self, app, user, theme_name: str):
        from oneirodex.utils.theme_validation import is_valid_theme_name
        from oneirodex.utils.themes import ThemeManager

        valid, reason = is_valid_theme_name(theme_name)
        if not valid:
            return None, (reason or 'Invalid theme name', 'bad_request')
        try:
            ThemeManager(app).delete_themefile(theme_name)
        except ValueError as exc:
            return None, (str(exc), 'bad_request')
        except Exception:
            app.logger.exception('Theme deletion failed')
            return None, ('Theme deletion failed. Please try again.', 'internal')
        return {'status': 'deleted', 'theme_name': theme_name, **self.payload(app, user)}, None

    def reset(self, app, user):
        from oneirodex.utils.theme_reset import reset_default_theme_assets

        return reset_default_theme_assets(
            app.root_path, audit_user_id=getattr(user, 'id', None), logger=app.logger,
        )


def create_admin_themes_read_router(
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
    data = data_access or AdminThemesData()

    @router.api_route('/api/admin/themes', methods=['GET', 'HEAD', 'POST'])
    @router.api_route('/api/admin/themes/{theme_name}', methods=['DELETE'])
    @router.post('/admin/themes', include_in_schema=False)
    @router.post('/admin/themes/delete/{theme_name}', include_in_schema=False)
    @router.post('/admin/themes/reset', include_in_schema=False)
    async def admin_themes(request: Request, theme_name: str | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user
            is_admin = (
                user is not None
                and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            csrf_response = None
            compat_form = None
            can_parse_form = is_admin and (
                auth.token is None or auth.has_scope('admin')
            )
            if request.method not in ('GET', 'HEAD') and auth.token is None and can_parse_form:
                from .csrf_compat import csrf_error_response

                form_csrf_token = None
                if request.url.path in {
                    '/admin/themes', '/admin/themes/reset',
                } or request.url.path.startswith('/admin/themes/delete/'):
                    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                    if content_type in {'application/x-www-form-urlencoded', 'multipart/form-data'}:
                        try:
                            from .bounded_multipart import (
                                InvalidContentLength, RequestBodyTooLarge,
                                bounded_multipart_form,
                            )

                            max_bytes = int(
                                flask_app.config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024
                            )
                            compat_form = await bounded_multipart_form(
                                request, max_body_bytes=max_bytes + 64 * 1024,
                                max_files=1, max_fields=12, max_part_size=max_bytes,
                            )
                            form_csrf_token = compat_form.get('csrf_token')
                        except RequestBodyTooLarge:
                            from oneirodex.utils.api_contract import api_error_payload

                            payload, status = api_error_payload(
                                'Theme upload exceeds the maximum request size.',
                                code='payload_too_large',
                            )
                            csrf_response = JSONResponse(payload, status_code=status)
                        except InvalidContentLength:
                            from oneirodex.utils.api_contract import api_error_payload

                            payload, status = api_error_payload(
                                'Invalid request size.', code='bad_request',
                            )
                            csrf_response = JSONResponse(payload, status_code=status)
                        except Exception:
                            form_csrf_token = None
                if csrf_response is None:
                    csrf_response = csrf_error_response(
                        request, auth.session_data, flask_app.config, token=form_csrf_token,
                    )
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            elif not is_admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden'
                )
                response = JSONResponse(payload, status_code=status)
            elif request.url.path == '/admin/themes' and request.method == 'POST':
                result, error = await _admin_theme_form_upload(
                    request, compat_form, flask_app, data, user,
                )
                if error is None:
                    theme_name = (result or {}).get('theme', {}).get('name', 'theme')
                    message, category = f"Theme '{theme_name}' uploaded successfully!", 'success'
                else:
                    reason, _error_code = error
                    message, category = f'Upload failed: {reason}', 'error'
                response = _theme_form_redirect(auth, message, category)
            elif request.url.path.startswith('/admin/themes/delete/') and request.method == 'POST':
                result, error = data.delete(flask_app, user, theme_name or '')
                if error is None:
                    message = f"Theme '{(result or {}).get('theme_name', theme_name)}' deleted successfully!"
                    category = 'success'
                else:
                    message, category = f'Deletion failed: {error[0]}', 'error'
                response = _theme_form_redirect(auth, message, category)
            elif request.url.path == '/admin/themes/reset' and request.method == 'POST':
                ok, message = data.reset(flask_app, user)
                is_json = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                if is_json == 'application/json' or is_json.endswith('+json'):
                    if ok:
                        response = JSONResponse(api_ok_payload({'status': 'reset', 'message': message}))
                    else:
                        payload, status = api_error_payload(
                            'Default theme reset failed. Please try again.', code='internal',
                        )
                        response = JSONResponse(payload, status_code=status)
                else:
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append(('success' if ok else 'error', message))
                    auth.session_data['_flashes'] = flashes
                    response = RedirectResponse('/admin/themes', status_code=302)
            elif request.method == 'POST' or request.method == 'DELETE':
                response = await _admin_theme_action(
                    request, flask_app, data, user, theme_name, api_ok_payload, api_error_payload,
                )
            else:
                response = JSONResponse(api_ok_payload(data.payload(flask_app, user)))

            if compat_form is not None:
                await compat_form.close()

        from oneirodex.utils.security_headers import security_header_values

        if auth.should_set_session_cookie:
            from .acquire_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    async def _admin_theme_action(request, app, data, user, theme_name, api_ok, api_error):
        if request.method == 'POST':
            try:
                max_bytes = int(app.config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024)
                try:
                    declared_length = int(request.headers.get('content-length') or 0)
                except ValueError:
                    declared_length = 0
                if declared_length > max_bytes:
                    payload, status = api_error(
                        'Theme upload exceeds the maximum request size.', code='bad_request',
                    )
                    return JSONResponse(payload, status_code=status)
                from .bounded_multipart import (
                    InvalidContentLength, RequestBodyTooLarge, bounded_multipart_form,
                )

                try:
                    form = await bounded_multipart_form(
                        request, max_body_bytes=max_bytes + 64 * 1024,
                        max_files=1, max_fields=12, max_part_size=max_bytes,
                    )
                except RequestBodyTooLarge:
                    payload, status = api_error(
                        'Theme upload exceeds the maximum request size.',
                        code='payload_too_large',
                    )
                    return JSONResponse(payload, status_code=status)
                except InvalidContentLength:
                    payload, status = api_error('Invalid request size.', code='bad_request')
                    return JSONResponse(payload, status_code=status)
                try:
                    upload = form.get('theme_zip')
                    if upload is None:
                        result, error = data.upload(app, user, '', b'')
                    else:
                        content = await upload.read(max_bytes + 1)
                        if len(content) > max_bytes:
                            result, error = None, ('Theme upload exceeds the maximum request size.', 'bad_request')
                        else:
                            result, error = data.upload(app, user, upload.filename or '', content)
                finally:
                    await form.close()
            except Exception:
                result, error = None, ('Theme upload failed. Please try again.', 'internal')
        else:
            result, error = data.delete(app, user, theme_name or '')
        if error is not None:
            payload, status = api_error(error[0], code=error[1])
            return JSONResponse(payload, status_code=status)
        return JSONResponse(api_ok(result))

    return router


def _theme_form_redirect(auth, message: str, category: str) -> Response:
    flashes = list(auth.session_data.get('_flashes') or [])
    flashes.append((category, message))
    auth.session_data['_flashes'] = flashes
    return RedirectResponse('/admin/themes', status_code=302)


async def _admin_theme_form_upload(request, form, app, data, user):
    if form is None:
        return None, ('Please choose a valid theme archive and try again.', 'bad_request')
    try:
        max_bytes = int(app.config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024)
        upload = form.get('theme_zip')
        if upload is None:
            return None, ('No file provided', 'bad_request')
        try:
            declared_length = int(request.headers.get('content-length') or 0)
        except ValueError:
            declared_length = 0
        if declared_length > max_bytes:
            return None, ('Theme upload exceeds the maximum request size.', 'bad_request')
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            return None, ('Theme upload exceeds the maximum request size.', 'bad_request')
        return data.upload(app, user, upload.filename or '', content)
    except Exception:
        app.logger.exception('Theme form upload failed')
        return None, ('Theme upload failed. Please try again.', 'internal')


def mount_admin_themes_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_themes_read_router(flask_app, **kwargs))
    return app
