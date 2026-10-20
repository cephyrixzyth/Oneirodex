"""Native session reads for member and administrator download queues."""
from __future__ import annotations

from .form_compat import first_form_value
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect
from .request_auth import request_auth_context
from .response_compat import flask_redirect_response


class DownloadRequestReadData:
    """Project download requests without exposing server filesystem paths."""

    @staticmethod
    def _filename(row):
        import os
        path = getattr(row, 'zip_file_path', None)
        return os.path.basename(str(path).replace('\\', '/')) if path else None

    def my_downloads(self, user):
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        from oneirodex.utils.library_acl import user_can_access_game

        rows = db.session.execute(
            select(DownloadRequest).options(joinedload(DownloadRequest.game))
            .filter_by(user_id=user.id).order_by(DownloadRequest.request_time.desc())
        ).scalars().unique().all()
        result = []
        for row in rows:
            if row.game is None or not user_can_access_game(user, row.game):
                continue
            status = row.status or 'pending'
            result.append({
                'id': row.id, 'game_name': row.game.name,
                'status': status, 'file_name': self._filename(row),
                'download_url': f'/download_zip/{row.id}' if status == 'available' else None,
                'download_size': row.download_size,
            })
        return result

    def admin_requests(self):
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest, User

        rows = db.session.execute(
            select(DownloadRequest, User.name.label('username'))
            .join(User, DownloadRequest.user_id == User.id)
            .options(joinedload(DownloadRequest.game))
            .order_by(DownloadRequest.request_time.desc(), DownloadRequest.id.desc())
        ).all()
        return [{
            'id': row.id, 'username': username,
            'game_uuid': row.game_uuid[:8] if row.game_uuid else '',
            'status': row.status or 'unknown', 'file_name': self._filename(row),
            'request_time': row.request_time.isoformat() if row.request_time else None,
            'completion_time': row.completion_time.isoformat() if row.completion_time else None,
        } for row, username in rows]

    def my_download_status(self, user, request_id: int):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest

        return db.session.execute(
            select(DownloadRequest).filter_by(id=request_id, user_id=user.id)
        ).scalars().first()

    def delete(self, request_id: int) -> bool:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        from oneirodex.utils.event_logging import log_system_event

        row = db.session.get(DownloadRequest, request_id)
        if row is None:
            return False
        log_system_event(
            f'Deleting download request {request_id} for user {row.user_id}',
            event_type='download_api', event_level='info',
        )
        db.session.delete(row)
        db.session.commit()
        log_system_event(
            f'Successfully deleted download request {request_id}',
            event_type='download_api', event_level='info',
        )
        return True

    def delete_for_user(self, user, request_id: int) -> bool:
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        from oneirodex.utils.event_logging import log_system_event

        row = db.session.execute(
            select(DownloadRequest).filter_by(id=request_id, user_id=user.id)
        ).scalars().first()
        if row is None:
            return False
        db.session.delete(row)
        db.session.commit()
        log_system_event(
            f'User {user.id} deleted download request {request_id}',
            event_type='audit', event_level='information',
        )
        return True

    def delete_admin_form(self, request_id: int) -> bool:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DownloadRequest
        from oneirodex.utils.event_logging import log_system_event

        row = db.session.get(DownloadRequest, request_id)
        if row is None:
            return False
        log_system_event(
            f'Admin deleting download request {request_id}',
            event_type='admin_download', event_level='info',
        )
        db.session.delete(row)
        db.session.commit()
        return True


def create_download_request_read_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or DownloadRequestReadData()

    @router.api_route('/api/my_downloads', methods=['GET', 'HEAD'])
    @router.api_route('/api/admin/download-requests', methods=['GET', 'HEAD'])
    @router.delete('/api/delete_download/{request_id:int}')
    def download_requests(request: Request):
        is_delete = request.method == 'DELETE'
        is_admin_route = is_delete or request.url.path.endswith('/admin/download-requests')
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if is_delete:
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session, flask_app.config)
            if csrf_response is not None:
                response = csrf_response
                auth = None
            else:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
            from oneirodex.utils.role_catalog import normalize_role
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload

            if csrf_response is not None:
                pass
            else:
                user = auth.user
                is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            if csrf_response is None and user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            elif csrf_response is None and is_admin_route and not is_admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif csrf_response is None and is_admin_route and auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif csrf_response is None and is_delete:
                try:
                    request_id = int(request.path_params['request_id'])
                    if request_id <= 0:
                        from oneirodex.utils.event_logging import log_system_event
                        log_system_event(
                            f'Invalid request ID: {request_id}',
                            event_type='download_api', event_level='warning',
                        )
                        payload, status = api_error_payload('Invalid request ID', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    elif not data.delete(request_id):
                        payload, status = api_error_payload('Download request not found', code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        response = JSONResponse(api_ok_payload({'message': 'Download request deleted successfully'}))
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    from oneirodex.utils.event_logging import log_system_event
                    log_system_event(
                        f'Error deleting download request {request_id}: Could not delete the download request',
                        event_type='download_api', event_level='error',
                    )
                    import logging
                    logging.getLogger(__name__).warning('Delete download request failed')
                    payload, status = api_error_payload('Could not delete the download request', code='internal')
                    response = JSONResponse(payload, status_code=status)
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie
                    _set_session_cookie(response, flask_app, auth)
            elif csrf_response is None and is_admin_route:
                response = JSONResponse(api_ok_payload({'requests': data.admin_requests()}))
            elif csrf_response is None:
                response = JSONResponse(data.my_downloads(user))
                if auth.should_set_session_cookie:
                    from .oidc_status import _set_session_cookie
                    _set_session_cookie(response, flask_app, auth)

        from oneirodex.utils.security_headers import security_header_values
        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    @router.api_route('/check_download_status/{download_id}', methods=['GET', 'HEAD'])
    def check_download_status(request: Request, download_id: str):
        from .oidc_status import _set_session_cookie
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.security_headers import security_header_values

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            else:
                try:
                    request_id = int(download_id)
                except (ValueError, TypeError):
                    log_system_event(
                        f'Invalid download_id parameter in status check: {download_id}',
                        event_type='security', event_level='warning',
                    )
                    payload, status = api_error_payload(
                        'Invalid download ID', code='bad_request',
                        body_status='invalid', downloadId=download_id, found=False,
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    row = data.my_download_status(auth.user, request_id)
                    if row is None:
                        log_system_event(
                            f'Unauthorized download status check: user {auth.user.id} tried to check download {request_id}',
                            event_type='security', event_level='warning',
                        )
                        payload, status = api_error_payload(
                            'Download request not found', code='not_found',
                            body_status='not_found', downloadId=request_id, found=False,
                        )
                    else:
                        payload = api_ok_payload({
                            'status': row.status,
                            'downloadId': row.id,
                            'found': True,
                        })
                        status = 200
                    response = JSONResponse(payload, status_code=status)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)

        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    @router.post('/delete_download/{download_id:int}')
    async def delete_download_form(request: Request, download_id: int):
        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        from .oidc_status import _set_session_cookie
        from oneirodex.utils.security_headers import security_header_values

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            form = await request.form(max_files=0, max_fields=10, max_part_size=16 * 1024)
            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            csrf = csrf_error_response(
                request, session_data, flask_app.config,
                token=str(first_form_value(form, 'csrf_token') or ''),
            )
            if csrf is not None:
                response = csrf
                auth = None
            else:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
                if auth.user is None:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'),
                        include_next=True,
                    )
                elif not data.delete_for_user(auth.user, download_id):
                    response = Response(status_code=404)
                else:
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append(('info', 'Download request removed.'))
                    auth.session_data['_flashes'] = flashes
                    response = flask_redirect_response('/downloads', status_code=302)
            if auth is not None and auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)

        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        return response

    @router.post('/delete_download_request/{request_id:int}')
    async def delete_download_request_form(request: Request, request_id: int):
        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        from .oidc_status import _set_session_cookie
        from oneirodex.utils.api_contract import api_error_payload
        from oneirodex.utils.role_catalog import normalize_role
        from oneirodex.utils.security_headers import security_header_values

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            form = await request.form(max_files=0, max_fields=10, max_part_size=16 * 1024)
            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            csrf = csrf_error_response(
                request, session_data, flask_app.config,
                token=str(first_form_value(form, 'csrf_token') or ''),
            )
            if csrf is not None:
                response = csrf
                auth = None
            else:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
                role = normalize_role(getattr(auth.user, 'role', None) or '')
                if auth.user is None:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'),
                        include_next=True,
                    )
                elif role != 'admin':
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden',
                    )
                    response = JSONResponse(payload, status_code=status)
                elif not data.delete_admin_form(request_id):
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append(('error', 'Download request not found.'))
                    auth.session_data['_flashes'] = flashes
                    response = flask_redirect_response('/admin/manage-downloads', status_code=302)
                else:
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append(('success', 'Download request deleted.'))
                    auth.session_data['_flashes'] = flashes
                    response = flask_redirect_response('/admin/manage-downloads', status_code=302)
            if auth is not None and auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)

        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie'
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        return response

    return router


def mount_download_request_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_download_request_read_router(flask_app, **kwargs))
    return app
