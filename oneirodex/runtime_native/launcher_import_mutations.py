"""Native bounded upload and raw-body routes for launcher ownership imports."""
from __future__ import annotations

from contextlib import nullcontext
import logging
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context

_MAX_UPLOAD = 8 * 1024 * 1024
_SAFE_LAUNCHER_IMPORT_ERRORS = frozenset({
    'The file is empty',
    'CSV has no header row',
    'CSV must include a Name or Title column',
    'The file is not valid JSON or CSV',
    'The file must be UTF-8 text',
    'No games found in that export',
})


class LauncherImportMutationData:
    def enabled(self):
        from oneirodex.utils.store_ownership_common import is_ownership_sync_enabled
        return is_ownership_sync_enabled()

    def playnite_json(self, user_id, value):
        from oneirodex.utils.playnite_import import import_playnite_json
        return import_playnite_json(user_id, value)

    def playnite_csv(self, user_id, value):
        from oneirodex.utils.playnite_import import import_playnite_csv
        return import_playnite_csv(user_id, value)

    def launcher(self, user_id, value, *, filename, launcher):
        from oneirodex.utils.launcher_imports import import_launcher_export
        return import_launcher_export(user_id, value, filename=filename, launcher=launcher)


def create_launcher_import_mutation_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    opts = dict(flask_app=flask_app, data=data_access or LauncherImportMutationData(),
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager, database_scope=database_scope)

    @router.post('/api/imports/playnite')
    async def import_playnite(request: Request):
        return await _run(request, **opts, kind='playnite')

    @router.post('/api/imports/launcher')
    async def import_launcher(request: Request):
        return await _run(request, **opts, kind='launcher')

    return router


def mount_launcher_import_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_launcher_import_mutation_router(flask_app, **kwargs))
    return app


async def _run(request, *, flask_app, data, find_user, find_token,
               commit_token_touch, load_user_id, login_manager,
               database_scope, kind):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
        session = load_session_cookie(
            request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
            max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
            fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
        )
        csrf = csrf_error_response(request, session, flask_app.config)
        auth = None
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        if auth.token is not None and not auth.has_scope('write:library'):
            payload, status = api_error_payload(
                'Bearer token requires write:library scope', code='forbidden',
            )
            response = JSONResponse(payload, status_code=status)
        elif auth.token is None and csrf is not None:
            response = csrf
        elif auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth,
                message=getattr(login_manager, 'login_message', None),
                category=getattr(login_manager, 'login_message_category', 'message'), include_next=True)
        elif not data.enabled():
            payload, status = api_error_payload('Store ownership sync is disabled by administrator', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        else:
            form = None
            try:
                form, upload, body_bytes = await _request_payload(request)
                if kind == 'playnite':
                    if upload is not None:
                        filename = (upload.filename or '').lower()
                        try:
                            text = body_bytes.decode('utf-8-sig')
                        except UnicodeDecodeError:
                            payload, status = api_error_payload('File must be UTF-8 text', code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            result = (data.playnite_csv(auth.user.id, text) if filename.endswith('.csv')
                                      else data.playnite_json(auth.user.id, text))
                            response = _playnite_result(result, api_error_payload, api_ok_payload)
                    else:
                        try:
                            import json
                            value = json.loads(body_bytes)
                        except Exception:
                            value = None
                        if value is None:
                            payload, status = api_error_payload('JSON body or file upload required', code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            result = data.playnite_json(auth.user.id, value)
                            response = _playnite_result(result, api_error_payload, api_ok_payload)
                else:
                    filename = upload.filename or '' if upload is not None else ''
                    launcher = ((form.get('launcher') if form is not None else None)
                                or request.query_params.get('launcher') or None)
                    if not body_bytes.strip():
                        payload, status = api_error_payload('JSON body or file upload required', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        outcome = data.launcher(auth.user.id, body_bytes, filename=filename,
                                                launcher=(str(launcher).strip() or None) if launcher else None)
                        result = outcome.to_dict()
                        if outcome.errors and not (outcome.imported or outcome.updated):
                            payload, status = api_error_payload(outcome.errors[0], code='bad_request', **result)
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload(result))
            except ValueError as exc:
                candidate = str(exc)
                if kind == 'playnite':
                    message = 'The Playnite export could not be read'
                else:
                    message = (
                        candidate if candidate in _SAFE_LAUNCHER_IMPORT_ERRORS
                        else 'The launcher export could not be read'
                    )
                payload, status = api_error_payload(message, code='bad_request')
                response = JSONResponse(payload, status_code=status)
            except Exception:
                from oneirodex.runtime_native.db_session import native_db as db
                db.session.rollback()
                logging.getLogger(__name__).warning('Launcher import failed')
                payload, status = api_error_payload('Could not import launcher library data.', code='internal')
                response = JSONResponse(payload, status_code=status)
            finally:
                if form is not None:
                    await form.close()
        if auth is not None and auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values
    response.headers.setdefault('Cache-Control', 'no-store')
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response


def _playnite_result(result, error_builder, ok_builder):
    payload = result.to_dict()
    if result.errors and result.imported == 0 and result.matched == 0:
        body, status = error_builder(result.errors[0], code='bad_request', **payload)
        return JSONResponse(body, status_code=status)
    return JSONResponse(ok_builder(payload))


async def _request_payload(request):
    form = None
    upload = None
    if request.headers.get('content-type', '').lower().startswith('multipart/form-data'):
        form = await request.form(max_files=1, max_fields=12, max_part_size=_MAX_UPLOAD)
        candidate = form.get('file')
        if isinstance(candidate, UploadFile):
            upload = candidate
            content = await candidate.read(_MAX_UPLOAD + 1)
        else:
            content = b''
        if len(content) > _MAX_UPLOAD:
            raise ValueError('Upload is too large')
        return form, upload, content
    content = await request.body()
    if len(content) > _MAX_UPLOAD:
        raise ValueError('Request body is too large')
    return form, upload, content
