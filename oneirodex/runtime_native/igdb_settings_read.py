"""Native admin read for IGDB credentials with secret presence only."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class IgdbSettingsData:
    def read(self) -> dict:
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.igdb_settings import igdb_public_state

        return {'settings': igdb_public_state(global_settings_row())}

    def save(self, payload: dict) -> dict:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.cache import cache
        from oneirodex.utils.global_settings import global_settings_row, global_settings_row_or_create
        from oneirodex.utils.igdb_settings import igdb_public_state

        settings = global_settings_row() or global_settings_row_or_create()
        settings.igdb_client_id = payload['igdb_client_id']
        if payload['igdb_client_secret']:
            settings.igdb_client_secret = payload['igdb_client_secret']
        db.session.commit()
        cache.delete('global_settings')
        return {'settings': igdb_public_state(settings)}

    def test_connection(self) -> dict | bool | None:
        from datetime import datetime, timezone

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.global_settings import global_settings_row
        from oneirodex.utils.igdb_api import make_igdb_api_request
        from oneirodex.utils.igdb_settings import igdb_public_state

        settings = global_settings_row()
        if not settings or not settings.igdb_client_id or not settings.igdb_client_secret:
            return None
        result = make_igdb_api_request(
            'https://api.igdb.com/v4/games', 'fields name; limit 1;'
        )
        if not isinstance(result, list):
            return False
        settings.igdb_last_tested = datetime.now(timezone.utc)
        db.session.commit()
        return {'settings': igdb_public_state(settings)}


def create_igdb_settings_router(
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
    data = data_access or IgdbSettingsData()

    @router.api_route('/api/admin/igdb/settings', methods=['GET', 'HEAD', 'PUT'])
    @router.api_route('/api/admin/igdb/test', methods=['POST'])
    @router.api_route('/admin/integrations/igdb/save', methods=['POST'])
    @router.api_route('/admin/integrations/igdb/test', methods=['POST'])
    @router.api_route('/admin/igdb_settings', methods=['POST'])
    @router.api_route('/admin/test_igdb', methods=['POST'])
    async def igdb_settings(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method in ('PUT', 'POST'):
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name),
                    flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(
                        flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                    ),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = None
            if csrf_response is None:
                auth = request_auth_context(
                    request, flask_app.config,
                    find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id, login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            if csrf_response is not None:
                response = csrf_response
            else:
                assert auth is not None
                user = auth.user
                is_admin = (
                    user is not None
                    and bool(getattr(user, 'is_authenticated', True))
                    and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                )
                if user is None:
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
                elif request.url.path in {'/admin/igdb_settings', '/admin/integrations/igdb/save'}:
                    try:
                        body = await request.json()
                    except Exception:
                        body = None
                    from oneirodex.utils.igdb_settings import validate_igdb_data

                    try:
                        payload = validate_igdb_data(body)
                        data.save(payload)
                        response = JSONResponse(api_ok_payload({
                            'status': 'success',
                            'message': 'IGDB settings updated successfully',
                        }))
                    except ValueError as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        import logging

                        db.session.rollback()
                        logging.getLogger(__name__).warning('IGDB settings form save failed')
                        payload, status = api_error_payload('Could not save IGDB settings', code='internal')
                        response = JSONResponse(payload, status_code=status)
                elif request.method == 'POST':
                    try:
                        result = data.test_connection()
                        if result is None:
                            payload, status = api_error_payload(
                                'Save a client ID and secret before testing the connection',
                                code='bad_request',
                            )
                            response = JSONResponse(payload, status_code=status)
                        elif result is False:
                            payload, status = api_error_payload(
                                'IGDB connection failed. Check the saved credentials and provider access.',
                                code='bad_gateway',
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload({
                                **result, 'message': 'IGDB connection successful.',
                            }))
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        import logging

                        db.session.rollback()
                        logging.getLogger(__name__).warning('IGDB connection test failed')
                        payload, status = api_error_payload(
                            'IGDB connection test failed', code='bad_gateway'
                        )
                        response = JSONResponse(payload, status_code=status)
                elif request.method == 'PUT':
                    try:
                        body = await request.json()
                    except Exception:
                        body = None
                    from oneirodex.utils.igdb_settings import validate_igdb_data

                    try:
                        payload = validate_igdb_data(body)
                    except ValueError as exc:
                        error, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(error, status_code=status)
                    else:
                        try:
                            response = JSONResponse(api_ok_payload(data.save(payload)))
                        except Exception:
                            from oneirodex.runtime_native.db_session import native_db as db
                            import logging

                            db.session.rollback()
                            logging.getLogger(__name__).warning('IGDB settings API save failed')
                            error, status = api_error_payload(
                                'Could not save IGDB settings', code='internal'
                            )
                            response = JSONResponse(error, status_code=status)
                        else:
                            if auth.should_set_session_cookie:
                                from .acquire_status import _set_session_cookie

                                _set_session_cookie(response, flask_app, auth)
                else:
                    try:
                        response = JSONResponse(api_ok_payload(data.read()))
                    except Exception:
                        import logging

                        logging.getLogger(__name__).warning('IGDB settings API load failed')
                        error, status = api_error_payload(
                            'Could not load IGDB settings', code='internal'
                        )
                        response = JSONResponse(error, status_code=status)

        from oneirodex.utils.security_headers import security_header_values

        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_igdb_settings_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_igdb_settings_router(flask_app, **kwargs))
    return app
