"""Native FastAPI read routes for administrator ownership diagnostics."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context
from .query_compat import first_query_value


class OwnershipAdminReadData:
    """Adapter for the stored, credential-redacted administrator projection."""

    def connections(self, after_id: int) -> dict:
        from oneirodex.utils.store_connection_status import admin_connections

        return admin_connections(after_id=after_id)

    def member_store_problem(self, user_id: int, store: str):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.store_sync_jobs import LIVE_SYNC_ADAPTERS

        if store not in LIVE_SYNC_ADAPTERS:
            return ('No live sync exists for this store', 'not_found', 404)
        if db.session.execute(select(User.id).where(User.id == user_id)).first() is None:
            return ('Member not found', 'not_found', 404)
        return None

    def retry(self, user_id: int, store: str, actor_id: int):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import StoreAccount
        from oneirodex.utils.store_ownership_common import is_ownership_sync_enabled
        from oneirodex.utils.store_sync_errors import SyncOutcomeError
        from oneirodex.utils.store_sync_jobs import run_store_sync

        if not is_ownership_sync_enabled():
            return None, ('Store ownership sync is disabled by administrator', 'forbidden', 403)
        linked = db.session.execute(select(StoreAccount.id).where(
            StoreAccount.user_id == user_id, StoreAccount.store == store,
        )).first()
        if linked is None:
            return None, _ownership_outcome_error(store, 'not_connected')
        try:
            outcome = run_store_sync(user_id, store, trigger='admin', actor_id=actor_id)
        except SyncOutcomeError as exc:
            return None, _ownership_outcome_error(store, exc.reason, exc.job)
        job = outcome['job']
        if job.status == 'failed':
            return None, _ownership_outcome_error(store, outcome['reason'], job)
        from oneirodex.utils.store_sync_jobs import job_dict
        return {'job': job_dict(job)}, None

    def cancel(self, user_id: int, store: str):
        from oneirodex.utils.store_sync_errors import SyncOutcomeError
        from oneirodex.utils.store_sync_jobs import job_dict, request_cancel

        try:
            job = request_cancel(user_id, store)
        except SyncOutcomeError as exc:
            return None, _ownership_outcome_error(store, exc.reason, exc.job)
        return {'job': job_dict(job)}, None


def create_ownership_admin_read_router(
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
    data = data_access if data_access is not None else OwnershipAdminReadData()

    @router.api_route('/api/admin/ownership/connections', methods=['GET', 'HEAD'])
    def admin_ownership_connections(request: Request):
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
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user
            if user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            elif (
                not bool(getattr(user, 'is_authenticated', True))
                or normalize_role(getattr(user, 'role', None) or '') != 'admin'
            ):
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger',
                    include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                from oneirodex.utils.api_contract import api_error_payload

                payload, status = api_error_payload(
                    'This token does not have the admin scope', code='forbidden',
                )
                response = JSONResponse(payload, status_code=status)
            else:
                raw = first_query_value(request.query_params, 'after_id', '0')
                if (
                    not raw.isascii() or not raw.isdigit() or len(raw) > 10
                    or int(raw) > 2147483647
                ):
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(
                        'after_id must be a nonnegative integer cursor',
                        code='bad_request',
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(data.connections(int(raw))))
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)

        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    @router.post('/api/admin/ownership/connections/{user_id:int}/{store}/sync')
    def retry_ownership_sync(user_id: int, store: str, request: Request):
        return _admin_ownership_mutation(request, flask_app, data, user_id, store,
                                         'sync', find_user, find_token,
                                         commit_token_touch, load_user_id,
                                         login_manager, database_scope)

    @router.post('/api/admin/ownership/connections/{user_id:int}/{store}/cancel')
    def cancel_ownership_sync(user_id: int, store: str, request: Request):
        return _admin_ownership_mutation(request, flask_app, data, user_id, store,
                                         'cancel', find_user, find_token,
                                         commit_token_touch, load_user_id,
                                         login_manager, database_scope)

    return router


def mount_ownership_admin_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_ownership_admin_read_router(flask_app, **kwargs))
    return app


def _ownership_outcome_error(store, reason, job=None):
    from oneirodex.utils.store_sync_errors import REASONS, reason_payload
    from oneirodex.utils.store_sync_jobs import PROVIDER_NAMES, job_dict

    entry = REASONS.get(reason) or REASONS['internal_error']
    info = reason_payload(reason, PROVIDER_NAMES.get(store, store))
    return (info['message'], entry.envelope_code, entry.http_status, {
        'detail': info, 'job': job_dict(job) if job is not None else None,
    })


def _admin_ownership_mutation(request, flask_app, data, user_id, store, action,
                              find_user, find_token, commit_token_touch,
                              load_user_id, login_manager, database_scope):
    from contextlib import nullcontext
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        from .request_auth import request_auth_context
        cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
        session = load_session_cookie(
            request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
            max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
            fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
        )
        csrf_response = csrf_error_response(request, session, flask_app.config)
        auth = None
        if csrf_response is None:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        from oneirodex.utils.role_catalog import normalize_role
        if csrf_response is not None:
            response = csrf_response
        elif auth.user is None:
            response = _login_redirect(
                flask_app, request, login_manager, auth,
                message=getattr(login_manager, 'login_message', None),
                category=getattr(login_manager, 'login_message_category', 'message'),
                include_next=True,
            )
        elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
            response = _login_redirect(
                flask_app, request, login_manager, auth,
                message='You must be an admin to access this page.', category='danger',
                include_next=False,
            )
        elif auth.token is not None and not auth.has_scope('admin'):
            payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        else:
            problem = data.member_store_problem(user_id, store)
            if problem:
                payload, status = api_error_payload(problem[0], code=problem[1], status=problem[2])
                response = JSONResponse(payload, status_code=status)
            else:
                try:
                    result, error = (data.retry(user_id, store, auth.user.id)
                                     if action == 'sync' else data.cancel(user_id, store))
                    if error:
                        message, code, status, *extra = error
                        payload, status = api_error_payload(message, code=code, status=status,
                                                            **(extra[0] if extra else {}))
                        response = JSONResponse(payload, status_code=status)
                    else:
                        payload = api_ok_payload({'job': result['job']})
                        status = 200 if action == 'sync' else 202
                        response = JSONResponse(payload, status_code=status)
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    import logging
                    logging.getLogger(__name__).warning('Ownership sync action failed')
                    payload, status = api_error_payload('Ownership sync action failed', code='internal')
                    response = JSONResponse(payload, status_code=status)
        if auth is not None and auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie
            _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response
