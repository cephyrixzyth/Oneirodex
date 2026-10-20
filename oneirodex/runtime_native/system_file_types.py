"""Native admin API for allowed and ignored file-type configuration."""
from __future__ import annotations

import re
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class FileTypeConflict(Exception):
    pass


class FileTypeMissing(Exception):
    pass


class SystemFileTypeData:
    def _model(self, category):
        from oneirodex.models import AllowedFileType, IgnoredFileType

        return AllowedFileType if category == 'allowed' else IgnoredFileType

    def list(self, category):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db

        model = self._model(category)
        records = db.session.execute(select(model).order_by(model.value.asc())).scalars().all()
        return [{'id': item.id, 'value': item.value} for item in records]

    def create(self, category, value):
        from sqlalchemy.exc import IntegrityError
        from oneirodex.runtime_native.db_session import native_db as db

        record = self._model(category)(value=value)
        try:
            db.session.add(record)
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise FileTypeConflict from exc
        return {'id': record.id, 'value': record.value}

    def update(self, category, record_id, value):
        from sqlalchemy.exc import IntegrityError
        from oneirodex.runtime_native.db_session import native_db as db

        record = db.session.get(self._model(category), record_id)
        if record is None:
            raise FileTypeMissing
        record.value = value
        try:
            db.session.commit()
        except IntegrityError as exc:
            db.session.rollback()
            raise FileTypeConflict from exc
        return {'id': record.id, 'value': record.value}

    def delete(self, category, record_id):
        from oneirodex.runtime_native.db_session import native_db as db

        record = db.session.get(self._model(category), record_id)
        if record is None:
            raise FileTypeMissing
        db.session.delete(record)
        db.session.commit()

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()


def validate_file_type_value(value):
    if not value or not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not re.fullmatch(r'[a-z0-9.-]+', value):
        return None
    if value.startswith('.'):
        value = value[1:]
    if len(value) > 10:
        return None
    return value


def create_system_file_types_router(
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
    data = data_access or SystemFileTypeData()

    @router.api_route('/api/file_types/{type_category}', methods=['GET', 'POST', 'PUT', 'DELETE', 'HEAD'])
    async def manage_file_types(type_category: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
            )
            if request.method in ('POST', 'PUT', 'DELETE'):
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                response = None
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and not _is_admin(auth.user):
                from .oidc_status import _login_redirect as admin_login_redirect

                response = admin_login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif response is None and auth.token is not None and not auth.has_scope('admin'):
                response = _error(403, 'forbidden', 'This token does not have the admin scope')
            elif response is None and type_category not in ('allowed', 'ignored'):
                response = _error(400, 'bad_request', 'Invalid type category')
            elif response is None:
                response = await _handle_file_type_request(request, type_category, data)
            if response is not None and auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


async def _handle_file_type_request(request, category, data):
    method = request.method
    if method == 'GET':
        try:
            return JSONResponse(data.list(category))
        except Exception:
            data.rollback()
            return _error(500, 'internal', 'An error occurred while processing your request')

    content_type = (
        request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    )
    is_json = content_type == 'application/json' or (
        content_type.startswith('application/') and content_type.endswith('+json')
    )
    if not is_json:
        return _error(400, 'bad_request', 'Request must be JSON')
    try:
        body = await request.json()
    except Exception:
        return _error(400, 'bad_request', 'Invalid JSON format')
    if body is None:
        return _error(400, 'bad_request', 'Invalid JSON format')

    required = {'POST': ('value',), 'PUT': ('id', 'value'), 'DELETE': ('id',)}.get(method, ())
    try:
        for field in required:
            if field not in body:
                return _error(400, 'bad_request', f'Missing required field: {field}')
    except TypeError:
        return _error(400, 'bad_request', 'Invalid JSON format')

    if not isinstance(body, dict):
        if method == 'POST':
            return _error(500, 'internal', 'An error occurred while processing your request')
        return _error(400, 'bad_request', 'Invalid ID format')
    if method == 'POST':
        value = validate_file_type_value(body.get('value'))
        if value is None:
            return _error(400, 'bad_request', 'Invalid file type format')
        try:
            return JSONResponse(data.create(category, value), status_code=201)
        except FileTypeConflict:
            return _error(409, 'conflict', 'File type already exists')
        except Exception:
            data.rollback()
            return _error(500, 'internal', 'An error occurred while processing your request')
    try:
        record_id = int(body['id'])
    except (ValueError, TypeError, OverflowError):
        return _error(400, 'bad_request', 'Invalid ID format')
    if method == 'PUT':
        value = validate_file_type_value(body.get('value'))
        if value is None:
            return _error(400, 'bad_request', 'Invalid file type format')
        try:
            return JSONResponse(data.update(category, record_id, value))
        except FileTypeMissing:
            return _error(404, 'not_found', 'File type not found')
        except FileTypeConflict:
            return _error(409, 'conflict', 'File type already exists')
        except Exception:
            data.rollback()
            return _error(500, 'internal', 'An error occurred while processing your request')
    try:
        data.delete(category, record_id)
        from oneirodex.utils.api_contract import api_ok_payload

        return JSONResponse(api_ok_payload())
    except FileTypeMissing:
        return _error(404, 'not_found', 'File type not found')
    except Exception:
        data.rollback()
        return _error(500, 'internal', 'An error occurred while processing your request')


def mount_system_file_type_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_system_file_types_router(flask_app, **kwargs))
    return app


def _error(status, code, message):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=resolved)


def _is_admin(user):
    from oneirodex.utils.role_catalog import normalize_role

    return normalize_role(getattr(user, 'role', None) or '') == 'admin'
