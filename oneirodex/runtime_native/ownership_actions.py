"""Native FastAPI routes for store ownership connections and imports."""
from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

from .oidc_status import _set_session_cookie
from .request_auth import request_auth_context


_CONNECT_MODELS: dict[str, str] = {
    'steam': 'ConnectSteamBody', 'gog': 'GogConnectBody',
    'epic': 'EpicConnectBody', 'amazon': 'AmazonConnectBody',
    'xbox': 'XboxConnectBody', 'psn': 'PsnConnectBody',
}
_LIVE_STORES = frozenset({'steam', 'gog', 'epic', 'amazon', 'xbox', 'psn'})
_CSV_STORES = frozenset((*_LIVE_STORES, 'meta_quest'))
_CONNECTORS = {
    'steam': 'connect_steam_account', 'gog': 'connect_gog_account',
    'epic': 'connect_epic_account', 'amazon': 'connect_amazon_account',
    'xbox': 'connect_xbox_account', 'psn': 'connect_psn_account',
}
_DISCONNECTORS = {
    'steam': 'disconnect_steam_account', 'gog': 'disconnect_gog_account',
    'epic': 'disconnect_epic_account', 'amazon': 'disconnect_amazon_account',
    'xbox': 'disconnect_xbox_account', 'psn': 'disconnect_psn_account',
}
_IMPORTERS = {
    'steam': 'import_steam_csv', 'gog': 'import_gog_csv',
    'epic': 'import_epic_csv', 'amazon': 'import_amazon_csv',
    'xbox': 'import_xbox_csv', 'psn': 'import_psn_csv',
    'meta_quest': 'import_meta_quest_csv',
}


class OwnershipActionsData:
    """Lazy bridge to existing ownership services; tests replace this adapter."""

    def enabled(self) -> bool:
        from oneirodex.utils.store_ownership import is_ownership_sync_enabled

        return is_ownership_sync_enabled()

    def connect(self, user_id: int, store: str, fields: dict[str, Any]):
        from oneirodex.utils import store_ownership
        from oneirodex.utils.store_sync_jobs import exclusive_link_change

        connector = getattr(store_ownership, _CONNECTORS[store])
        return exclusive_link_change(
            user_id, store, 'connect', lambda: connector(user_id, **fields),
        )

    def disconnect(self, user_id: int, store: str):
        from oneirodex.utils import store_ownership
        from oneirodex.utils.store_sync_jobs import exclusive_link_change

        disconnect = getattr(store_ownership, _DISCONNECTORS[store])
        return exclusive_link_change(
            user_id, store, 'disconnect', lambda: disconnect(user_id),
            clear_history=True,
        )

    def sync(self, user_id: int, store: str):
        from oneirodex.utils.store_sync_jobs import run_store_sync

        return run_store_sync(user_id, store, trigger='member', actor_id=user_id)

    def sync_all(self, user_id: int):
        from oneirodex.utils.store_sync_all import sync_all_stores

        return sync_all_stores(user_id, trigger='member', actor_id=user_id)

    def import_csv(self, user_id: int, store: str, csv_text: str):
        from oneirodex.utils import store_ownership

        return getattr(store_ownership, _IMPORTERS[store])(user_id, csv_text)

    def summary(self, user_id: int):
        from oneirodex.utils.store_ownership import get_ownership_summary

        return get_ownership_summary(user_id)


def create_ownership_actions_router(
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
    data = data_access or OwnershipActionsData()

    # Keep this exact route before the one-segment store route below.
    @router.post('/api/ownership/sync-all')
    async def sync_all_ownership(request: Request):
        return await _handle_action(
            request, flask_app, data, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            action='sync_all',
        )

    @router.post('/api/ownership/{store:str}')
    async def connect_ownership(store: str, request: Request):
        return await _handle_action(
            request, flask_app, data, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            action='connect', store=store,
        )

    @router.delete('/api/ownership/{store:str}')
    async def disconnect_ownership(store: str, request: Request):
        return await _handle_action(
            request, flask_app, data, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            action='disconnect', store=store,
        )

    @router.post('/api/ownership/{store:str}/sync')
    async def sync_ownership(store: str, request: Request):
        return await _handle_action(
            request, flask_app, data, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            action='sync', store=store,
        )

    @router.post('/api/ownership/{store:str}/csv')
    async def import_ownership_csv(store: str, request: Request):
        return await _handle_action(
            request, flask_app, data, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager, database_scope=database_scope,
            action='csv', store=store,
        )

    return router


def mount_ownership_actions_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_ownership_actions_router(flask_app, **kwargs))
    return app


async def _handle_action(
    request, flask_app, data, *, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, database_scope, action, store=None,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        # Bearer writes need an explicit scope. Cookie writes retain CSRF.
        from .csrf_compat import csrf_error_response

        if auth.token is not None and not auth.has_scope('write:library'):
            response = _error(403, 'forbidden', 'Bearer token requires write:library scope')
        else:
            response = (
                None if auth.token is not None
                else csrf_error_response(request, auth.session_data, flask_app.config)
            )
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        elif response is None:
            response = await _dispatch_action(request, flask_app, data, auth, action, store)
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _dispatch_action(request, flask_app, data, auth, action, store):
    from oneirodex.utils.api_contract import api_error_payload, api_ok_payload

    user_id = auth.user.id
    if action in ('connect', 'disconnect') and store not in _LIVE_STORES:
        return _error(404, 'not_found', 'Not found')
    if action == 'sync' and store not in _LIVE_STORES:
        return _error(404, 'not_found', 'No live sync exists for this store')
    if action == 'csv' and store not in _CSV_STORES:
        return _error(404, 'not_found', 'Not found')
    if action in ('disconnect', 'sync', 'sync_all', 'csv') and not data.enabled():
        if action == 'sync':
            return _outcome_error(store or 'steam', 'sync_disabled')
        return _error(403, 'forbidden', 'Store ownership sync is disabled by administrator')

    if action == 'connect':
        body, error = await _validated_body(request, store, flask_app.config)
        if error is not None:
            return error
        if not data.enabled():
            return _error(403, 'forbidden', 'Store ownership sync is disabled by administrator')
        try:
            account = data.connect(user_id, store, _connect_fields(store, body))
        except Exception as exc:
            from oneirodex.utils.store_sync_errors import SyncOutcomeError

            if isinstance(exc, SyncOutcomeError):
                return _outcome_error(store, exc.reason, exc.job)
            if isinstance(exc, ValueError):
                return _error(400, 'bad_request', str(exc))
            raise
        return JSONResponse(api_ok_payload({
            'account': account.to_dict(), 'summary': data.summary(user_id),
        }), status_code=201)

    if action == 'disconnect':
        try:
            data.disconnect(user_id, store)
        except Exception as exc:
            from oneirodex.utils.store_sync_errors import SyncOutcomeError

            if isinstance(exc, SyncOutcomeError):
                return _outcome_error(store, exc.reason, exc.job)
            raise
        return JSONResponse(api_ok_payload({'summary': data.summary(user_id)}))

    if action == 'sync':
        try:
            outcome = data.sync(user_id, store)
        except Exception as exc:
            from oneirodex.utils.store_sync_errors import SyncOutcomeError

            if isinstance(exc, SyncOutcomeError):
                return _outcome_error(store, exc.reason, exc.job)
            raise
        job = outcome['job']
        if job.status == 'failed':
            return _outcome_error(store, outcome['reason'], job)
        from oneirodex.utils.store_sync_jobs import job_dict

        payload = {**(outcome['result'] or {}), 'store': store, 'job': job_dict(job)}
        if job.status == 'cancelled':
            payload.update(synced=0, matched=0, cancelled=True)
        payload['summary'] = data.summary(user_id)
        return JSONResponse(api_ok_payload(payload))

    if action == 'sync_all':
        results = data.sync_all(user_id)
        return JSONResponse(api_ok_payload({
            'results': results, 'summary': data.summary(user_id),
        }))

    csv_text, error = await _read_csv_payload(request, flask_app)
    if error is not None:
        return error
    if not csv_text.strip():
        return _error(400, 'bad_request', 'csv content required')
    try:
        result = data.import_csv(user_id, store, csv_text)
    except PermissionError as exc:
        return _error(403, 'forbidden', str(exc))
    except ValueError as exc:
        return _error(400, 'bad_request', str(exc))
    extra = {}
    if store == 'meta_quest':
        extra['note'] = 'Ownership register only — Oneirodex never downloads Meta/Quest DRM titles.'
    return JSONResponse(api_ok_payload({
        **result, 'summary': data.summary(user_id), **extra,
    }))


async def _validated_body(request, store, config):
    from pydantic import ValidationError

    from oneirodex.schemas import ownership as schemas
    from oneirodex.utils.validation import format_validation_errors

    payload, error = await _json_body(request, config)
    if error is not None:
        return None, error
    model = getattr(schemas, _CONNECT_MODELS[store])
    try:
        return model.model_validate(payload), None
    except ValidationError as exc:
        return None, _error(
            422, 'unprocessable', 'Invalid request.',
            detail=format_validation_errors(exc),
        )


def _connect_fields(store, body):
    if store == 'steam':
        return {'steam_id': body.steam_id}
    if store == 'gog':
        return {
            'gog_user_id': (body.gog_user_id or body.user_id or '').strip() or None,
            'note': (body.note or '').strip() or None,
            'refresh_token': (body.refresh_token or body.token or '').strip() or None,
            'access_token': (body.access_token or '').strip() or None,
        }
    if store == 'epic':
        return {
            'epic_account_id': (body.epic_account_id or body.user_id or '').strip() or None,
            'note': (body.note or '').strip() or None,
            'device_auth': body.device_auth or body.token or None,
        }
    if store == 'amazon':
        return {
            'amazon_user_id': (body.amazon_user_id or body.user_id or '').strip() or None,
            'note': (body.note or '').strip() or None,
            'credential': body.credential or body.token or body.nile_json or None,
            'refresh_token': (body.refresh_token or '').strip() or None,
            'access_token': (body.access_token or '').strip() or None,
            'device_serial': (body.device_serial or body.device_serial_number or '').strip() or None,
        }
    return body.model_dump(exclude_none=True)


async def _json_body(request, config):
    if not _is_json_request(request):
        return {}, None
    raw, error = await _bounded_body(request, config)
    if error is not None:
        return None, error
    try:
        payload = json.loads(raw or b'{}')
    except (TypeError, ValueError):
        payload = {}
    return payload, None


async def _read_csv_payload(request, flask_app):
    content_type = request.headers.get('content-type', '').lower()
    if _is_json_request(request):
        payload, error = await _json_body(request, flask_app.config)
        if error is not None:
            return None, error
        value = payload.get('csv') or '' if isinstance(payload, dict) else ''
        return (value if isinstance(value, str) else ''), None
    raw, error = await _bounded_body(request, flask_app.config)
    if error is not None:
        return None, error
    if content_type.startswith('multipart/form-data'):
        replayed = _request_with_body(request, raw)
        try:
            form = await replayed.form(max_files=1, max_fields=10)
            upload = form.get('file')
            if upload is not None and hasattr(upload, 'read'):
                try:
                    return (await upload.read()).decode('utf-8', errors='replace'), None
                finally:
                    await form.close()
            value = form.get('csv') or ''
            await form.close()
            return (value if isinstance(value, str) else ''), None
        except Exception:
            return None, _error(400, 'bad_request', 'Invalid form data')
    if content_type.startswith('application/x-www-form-urlencoded'):
        replayed = _request_with_body(request, raw)
        try:
            form = await replayed.form(max_fields=10)
        except Exception:
            return None, _error(400, 'bad_request', 'Invalid form data')
        value = form.get('csv') or ''
        return (value if isinstance(value, str) else ''), None
    return '', None


def _is_json_request(request):
    mimetype = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    return mimetype == 'application/json' or (
        mimetype.startswith('application/') and mimetype.endswith('+json')
    )


async def _bounded_body(request, config):
    limit = _body_limit(config)
    content_length = request.headers.get('content-length')
    try:
        if content_length is not None and int(content_length) > limit:
            return b'', _too_large(config)
    except ValueError:
        return b'', _error(400, 'bad_request', 'Invalid content length')
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return b'', _too_large(config)
        chunks.append(chunk)
    return b''.join(chunks), None


def _request_with_body(request, body):
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {'type': 'http.disconnect'}
        delivered = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return StarletteRequest(request.scope, receive)


def _body_limit(config):
    try:
        value = int(config.get('MAX_CONTENT_LENGTH') or 32 * 1024 * 1024)
    except (TypeError, ValueError, OverflowError):
        value = 32 * 1024 * 1024
    return max(0, value)


def _too_large(config):
    limit_mb = config.get('MAX_UPLOAD_MB', max(1, _body_limit(config) // (1024 * 1024)))
    return _error(
        413, 'payload_too_large',
        f'The file you tried to upload is too large. Maximum size is {limit_mb}MB.',
    )


def _outcome_error(store, reason, job=None):
    from oneirodex.utils.store_sync_errors import REASONS, reason_payload
    from oneirodex.utils.store_sync_jobs import PROVIDER_NAMES, job_dict

    entry = REASONS.get(reason) or REASONS['internal_error']
    info = reason_payload(reason, PROVIDER_NAMES.get(store, store))
    return _error(
        entry.http_status, entry.envelope_code, info['message'],
        detail=info, job=job_dict(job) if job is not None else None,
    )


def _error(status, code, message, **fields):
    from oneirodex.utils.api_contract import api_error_payload

    payload, response_status = api_error_payload(message, code=code, status=status, **fields)
    return JSONResponse(payload, status_code=response_status)


def _finish(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''


def _login_redirect(flask_app, request, login_manager, auth):
    from .acquire_status import _login_redirect as login_redirect

    return login_redirect(flask_app, request, login_manager, auth)
