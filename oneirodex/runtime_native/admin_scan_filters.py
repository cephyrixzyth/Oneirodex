"""Native admin API for scan-filter catalog CRUD."""
from __future__ import annotations

from .form_compat import first_form_value
from contextlib import nullcontext
import logging
import re
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context
from .response_compat import flask_redirect_response


def filter_projection(group):
    raw = (getattr(group, 'filter_pattern', None) or '').strip()
    lowered = raw.lower()
    kind = 'dir' if lowered.startswith('dir:') else 'regex' if lowered.startswith('re:') else 'name'
    from oneirodex.utils.functions import normalize_case_sensitive
    return {
        'id': group.id, 'filter_pattern': getattr(group, 'filter_pattern', None) or '',
        'kind': kind, 'case_sensitive': normalize_case_sensitive(getattr(group, 'case_sensitive', None)),
    }


class AdminScanFiltersData:
    def list(self):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ReleaseGroup
        return db.session.execute(
            select(ReleaseGroup).order_by(ReleaseGroup.filter_pattern.asc(), ReleaseGroup.id.asc())
        ).scalars().all()

    def add(self, pattern, case_sensitive):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ReleaseGroup
        row = ReleaseGroup(filter_pattern=pattern, case_sensitive='yes' if case_sensitive else 'no')
        db.session.add(row)
        db.session.commit()
        return row

    def delete(self, filter_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ReleaseGroup
        row = db.session.get(ReleaseGroup, filter_id)
        if row is None:
            return False
        db.session.delete(row)
        db.session.commit()
        return True

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db
        db.session.rollback()


def create_admin_scan_filters_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminScanFiltersData()
    opts = dict(flask_app=flask_app, data=data, find_user=find_user,
                find_token=find_token, commit_token_touch=commit_token_touch,
                load_user_id=load_user_id, login_manager=login_manager,
                database_scope=database_scope)

    @router.post('/admin/edit_filters')
    async def legacy_add_filter(request: Request):
        return await _handle(request, **opts, filter_id=None, legacy_form=True)

    @router.api_route('/api/admin/scan-filters', methods=['GET', 'HEAD', 'POST'])
    async def filters(request: Request):
        return await _handle(request, **opts, filter_id=None)

    @router.delete('/api/admin/scan-filters/{filter_id:int}')
    async def delete_filter(filter_id: int, request: Request):
        return await _handle(request, **opts, filter_id=filter_id)

    @router.post('/delete_filter/{filter_id:int}')
    async def delete_filter_form(filter_id: int, request: Request):
        return await _handle(request, **opts, filter_id=filter_id, legacy_form=True)

    return router


def mount_admin_scan_filters_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_scan_filters_router(flask_app, **kwargs))
    return app


async def _handle(request, *, flask_app, data, find_user, find_token,
                  commit_token_touch, load_user_id, login_manager,
                  database_scope, filter_id, legacy_form=False):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        csrf = None
        legacy_form_values = None
        if request.method in ('POST', 'DELETE'):
            from .csrf_compat import csrf_error_response
            from .request_auth import _lifetime_seconds
            from .session_compat import load_session_cookie
            form_token = None
            if legacy_form:
                form = await request.form(
                    max_files=0, max_fields=10, max_part_size=16 * 1024,
                )
                legacy_form_values = form
                form_token = str(first_form_value(form, 'csrf_token') or '')
            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session = load_session_cookie(
                request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            csrf = csrf_error_response(
                request, session, flask_app.config, token=form_token,
            )
        auth = None
        if csrf is None:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        from oneirodex.utils.role_catalog import normalize_role
        if csrf is not None:
            response = csrf
        elif auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
            response = _login_redirect(flask_app, request, login_manager, auth,
                message='You must be an admin to access this page.', category='danger', include_next=False)
        elif auth.token is not None and not auth.has_scope('admin'):
            payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        elif legacy_form and filter_id is None and request.method == 'POST':
            pattern = str(legacy_form_values.get('filter_pattern') or '')
            case_raw = legacy_form_values.get('case_sensitive')
            case_value = str(case_raw if case_raw is not None else 'no')
            message = None
            category = 'message'
            if not pattern.strip():
                message, category = 'This field is required.', 'danger'
            elif case_value not in {'yes', 'no'}:
                message, category = 'Not a valid choice.', 'danger'
            else:
                try:
                    data.add(pattern, case_value == 'yes')
                    message = 'New scanning filter added.'
                except Exception:
                    data.rollback()
                    logging.getLogger(__name__).warning('Could not add admin scan filter')
                    message, category = 'Could not add scanning filter.', 'danger'
            flashes = list(auth.session_data.get('_flashes') or [])
            flashes.append((category, message))
            auth.session_data['_flashes'] = flashes
            response = flask_redirect_response('/admin/edit_filters', status_code=302)
            _set_session_cookie(response, flask_app, auth)
        elif filter_id is not None and legacy_form:
            try:
                deleted = data.delete(filter_id)
            except Exception:
                data.rollback()
                logging.getLogger(__name__).warning('Could not delete admin scan filter')
                payload, status = api_error_payload(
                    'Could not remove scanning filter.', code='internal',
                )
                response = JSONResponse(payload, status_code=status)
            else:
                if not deleted:
                    payload, status = api_error_payload(
                        'Scanning filter not found.', code='not_found',
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append(('message', 'Scanning filter removed.'))
                    auth.session_data['_flashes'] = flashes
                    response = flask_redirect_response('/admin/edit_filters', status_code=302)
        elif request.method == 'GET' or request.method == 'HEAD':
            rows = data.list()
            response = JSONResponse(api_ok_payload({'filters': [filter_projection(row) for row in rows]}))
        elif request.method == 'POST':
            body = await _read_json(request)
            if not isinstance(body, dict):
                payload, status = api_error_payload('Send a filter object.', code='bad_request')
                response = JSONResponse(payload, status_code=status)
            else:
                kind = str(body.get('kind') or 'name').strip().lower()
                pattern = str(body.get('pattern') or '').strip()
                case_sensitive = body.get('case_sensitive', False)
                message = None
                if kind not in {'name', 'dir', 'regex'}:
                    message = 'Choose a valid filter type.'
                elif not pattern or len(pattern) > 200:
                    message = 'Pattern must be between 1 and 200 characters.'
                elif kind == 'name' and pattern.lower().startswith(('dir:', 're:')):
                    message = 'Name tags cannot use a reserved filter prefix.'
                elif kind in {'dir', 'regex'} and pattern.lower().startswith(('dir:', 're:')):
                    message = 'Enter the pattern without its type prefix.'
                elif kind == 'regex':
                    try:
                        re.compile(pattern, re.IGNORECASE)
                    except re.error:
                        message = 'Enter a valid regular expression.'
                if kind != 'name':
                    case_sensitive = False
                elif not isinstance(case_sensitive, bool):
                    message = message or 'Choose whether the name tag is case sensitive.'
                if message:
                    payload, status = api_error_payload(message, code='bad_request')
                    response = JSONResponse(payload, status_code=status)
                else:
                    stored = f'dir:{pattern}' if kind == 'dir' else f're:{pattern}' if kind == 'regex' else pattern
                    try:
                        row = data.add(stored, case_sensitive)
                        response = JSONResponse(api_ok_payload({
                            'filter': filter_projection(row), 'message': 'Scanning filter added.',
                        }), status_code=201)
                    except Exception:
                        data.rollback()
                        logging.getLogger(__name__).warning('Could not add admin scan filter')
                        payload, status = api_error_payload('Could not add scanning filter.', code='internal')
                        response = JSONResponse(payload, status_code=status)
        elif filter_id is not None:
            try:
                deleted = data.delete(filter_id)
            except Exception:
                data.rollback()
                logging.getLogger(__name__).warning('Could not delete admin scan filter')
                payload, status = api_error_payload('Could not remove scanning filter.', code='internal')
                response = JSONResponse(payload, status_code=status)
            else:
                if not deleted:
                    payload, status = api_error_payload('Scanning filter not found.', code='not_found')
                    response = JSONResponse(payload, status_code=status)
                else:
                    response = JSONResponse(api_ok_payload({'message': 'Scanning filter removed.'}))
        else:
            payload, status = api_error_payload('Method not allowed.', code='bad_request', status=405)
            response = JSONResponse(payload, status_code=status)
        if auth is not None and auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values
    response.headers.setdefault('Cache-Control', 'no-store')
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
    return response


async def _read_json(request):
    import json
    try:
        if int(request.headers.get('content-length') or '0') > 16 * 1024:
            return None
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16 * 1024:
                return None
        value = json.loads(raw) if raw else None
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None
