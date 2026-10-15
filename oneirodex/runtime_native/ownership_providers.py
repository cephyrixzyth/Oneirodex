"""Native FastAPI read API for store ownership provider capabilities."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


class OwnershipProviderData:
    """Read capability and operator policy metadata without provider access."""

    def capabilities(self) -> dict:
        from oneirodex.utils.store_capabilities import provider_capabilities
        from oneirodex.utils.store_ownership import is_ownership_sync_enabled
        from oneirodex.utils.store_ownership_common import unofficial_store_opt_in

        return {
            'schema_version': 1,
            'providers': provider_capabilities(
                enabled=is_ownership_sync_enabled(),
                unofficial_stores=unofficial_store_opt_in(),
            ),
        }

    def connections(self, user):
        from oneirodex.utils.store_connection_status import member_connections

        return member_connections(user)

    def summary(self, user):
        from oneirodex.utils.store_ownership import get_ownership_summary

        return get_ownership_summary(user.id)

    def titles(self, user, after_id: int, status: str | None):
        from oneirodex.utils.ownership_review import list_review_titles

        return list_review_titles(user, after_id, status)

    def candidates(self, user, title_id: int):
        from oneirodex.utils.ownership_review import match_candidates

        return match_candidates(user, title_id)

    def decide(self, user, title_id: int, expected_revision, game_uuid, *, undo=False):
        from oneirodex.utils.ownership_review import decide_match

        return decide_match(
            user, title_id, expected_revision, game_uuid, undo=undo,
        )

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def cancel_sync(self, user_id: int, store: str):
        from oneirodex.utils.store_sync_jobs import (
            LIVE_SYNC_ADAPTERS, job_dict, request_cancel,
        )

        if store not in LIVE_SYNC_ADAPTERS:
            return None, (404, 'not_found', 'No live sync exists for this store')
        from oneirodex.utils.store_sync_errors import SyncOutcomeError

        try:
            job = request_cancel(user_id, store)
        except SyncOutcomeError as exc:
            from oneirodex.utils.store_sync_errors import REASONS, reason_payload

            from oneirodex.utils.store_sync_jobs import PROVIDER_NAMES

            entry = REASONS.get(exc.reason, REASONS['internal_error'])
            detail = reason_payload(exc.reason, PROVIDER_NAMES.get(store, store))
            return None, (
                entry.http_status, entry.envelope_code, detail['message'],
                {'detail': detail, 'job': job_dict(exc.job)},
            )
        return {'job': job_dict(job)}, None


def create_ownership_provider_router(
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
    data = data_access or OwnershipProviderData()

    @router.api_route('/api/ownership/providers', methods=['GET', 'HEAD'])
    def ownership_providers(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload(data.capabilities()))
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/ownership/connections', methods=['GET', 'HEAD'])
    def ownership_connections(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload(data.connections(auth.user)))
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/ownership', methods=['GET', 'HEAD'])
    def ownership_status(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.api_contract import api_ok_payload

                response = JSONResponse(api_ok_payload(data.summary(auth.user)))
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/ownership/titles', methods=['GET', 'HEAD'])
    def ownership_titles(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                raw = request.query_params.get('after_id', '0')
                status = request.query_params.get('status') or None
                if (
                    not raw.isascii() or not raw.isdigit() or len(raw) > 10
                    or int(raw) > 2147483647
                ):
                    response = _error_response(
                        400, 'bad_request',
                        'after_id must be a nonnegative integer cursor',
                    )
                elif status not in (None, 'needs_review', 'matched'):
                    response = _error_response(
                        400, 'bad_request', 'status must be needs_review or matched',
                    )
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(data.titles(
                        auth.user, int(raw), status,
                    )))
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)
            _finish(response, flask_app, request)
            return response

    @router.api_route(
        '/api/ownership/titles/{title_id:int}/candidates', methods=['GET', 'HEAD']
    )
    def ownership_candidates(title_id: int, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.ownership_review import ReviewError

                try:
                    result = data.candidates(auth.user, title_id)
                except ReviewError as exc:
                    status = 404 if exc.code == 'not_found' else 400
                    response = _error_response(status, exc.code, str(exc))
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(result))
                    if auth.should_set_session_cookie:
                        _set_session_cookie(response, flask_app, auth)
            _finish(response, flask_app, request)
            return response

    @router.post('/api/ownership/titles/{title_id:int}/match')
    async def review_ownership_match(title_id: int, request: Request):
        return await _decide_match(
            title_id, request, flask_app, data,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            undo=False,
        )

    @router.post('/api/ownership/titles/{title_id:int}/match/undo')
    async def undo_ownership_match(title_id: int, request: Request):
        return await _decide_match(
            title_id, request, flask_app, data,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            undo=True,
        )

    @router.post('/api/ownership/{store:str}/sync/cancel')
    async def cancel_ownership_sync(store: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config,
                find_user=find_user,
                find_token=find_token,
                commit_token_touch=commit_token_touch,
                load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from .csrf_compat import csrf_error_response

            if auth.token is not None and not auth.has_scope('write:library'):
                response = _error_response(
                    403, 'forbidden', 'Bearer token requires write:library scope',
                )
            else:
                response = (
                    None if auth.token is not None
                    else csrf_error_response(request, auth.session_data, flask_app.config)
                )
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                result, refusal = data.cancel_sync(auth.user.id, store)
                if refusal:
                    status, code, message, *fields = refusal
                    extra = fields[0] if fields else {}
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, response_status = api_error_payload(
                        message, code=code, status=status, **extra,
                    )
                    response = JSONResponse(payload, status_code=response_status)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(
                        api_ok_payload(result), status_code=202,
                    )
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
            _finish(response, flask_app, request)
            return response

    return router


def mount_ownership_provider_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_ownership_provider_router(flask_app, **kwargs))
    return app


def _finish(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''


def _error_response(status: int, code: str, message: str):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=response_status)


async def _decide_match(
    title_id, request, flask_app, data, *, find_user, find_token,
    commit_token_touch, load_user_id, login_manager, database_scope, undo,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config,
            find_user=find_user,
            find_token=find_token,
            commit_token_touch=commit_token_touch,
            load_user_id=load_user_id,
            login_manager=login_manager,
        )
        from .csrf_compat import csrf_error_response

        if auth.token is not None and not auth.has_scope('write:library'):
            response = _error_response(
                403, 'forbidden', 'Bearer token requires write:library scope',
            )
        else:
            response = (
                None if auth.token is not None
                else csrf_error_response(request, auth.session_data, flask_app.config)
            )
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        elif response is None:
            payload = await _json_object(request)
            if not isinstance(payload, dict) or (not undo and 'game_uuid' not in payload):
                response = _error_response(
                    400, 'bad_request',
                    'A JSON decision with game_uuid (or null) is required',
                )
            else:
                from oneirodex.utils.ownership_review import ReviewError

                try:
                    result = data.decide(
                        auth.user, title_id, payload.get('expected_revision'),
                        payload.get('game_uuid'), undo=undo,
                    )
                except ReviewError as exc:
                    data.rollback()
                    status = {'bad_request': 400, 'not_found': 404, 'conflict': 409}.get(
                        exc.code, 400,
                    )
                    response = _error_response(status, exc.code, str(exc))
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(result))
                if auth.should_set_session_cookie:
                    _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _json_object(request):
    import json

    try:
        payload = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else None
