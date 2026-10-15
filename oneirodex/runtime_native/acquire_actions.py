"""Native FastAPI Acquire search and send actions."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect, _set_session_cookie
from .csrf_compat import csrf_error_response
from .request_auth import request_auth_context


class AcquireActionData:
    def arr_enabled(self, *, config=None):
        from oneirodex.utils.module_status import arr_module_on

        return arr_module_on(config=config)

    def debrid_enabled(self):
        from oneirodex.utils.debrid_connectors import debrid_enabled

        return debrid_enabled()

    def search(self, query: str, *, current_label: str):
        from oneirodex.utils.acquire_scoring import (
            rank_acquire_hits, title_looks_like_newer_repack,
        )
        from oneirodex.utils.arr_connectors import search_indexers
        from oneirodex.utils.indexer_registry import indexer_status_summary

        hits = search_indexers(query)
        ranked = rank_acquire_hits([hit.to_dict() for hit in hits], query=query)
        if current_label:
            for row in ranked:
                row['newer_repack'] = title_looks_like_newer_repack(
                    str(row.get('title') or ''), current_label
                )
        return {'q': query, 'results': ranked, 'warnings': list(indexer_status_summary().get('warnings') or [])}

    def validate_url(self, url: str):
        from oneirodex.utils.security import validate_user_outbound_http_url

        return validate_user_outbound_http_url(url)

    def send(self, url: str, provider: str):
        from oneirodex.utils.arr_connectors import send_to_download_client
        from oneirodex.utils.debrid_connectors import (
            alldebrid_upload_magnet, premiumize_add_magnet,
            real_debrid_add_magnet, torbox_add_magnet,
        )

        if provider in ('qbittorrent', 'transmission', 'sabnzbd', 'nzbget', 'deluge'):
            return send_to_download_client(url, provider=provider)
        if provider == 'real_debrid':
            return real_debrid_add_magnet(url)
        if provider == 'alldebrid':
            return alldebrid_upload_magnet(url)
        if provider == 'premiumize':
            return premiumize_add_magnet(url)
        if provider == 'torbox':
            return torbox_add_magnet(url)
        raise ValueError('Unknown provider')

    def safe_error(self, exc, *, indexer=False):
        from oneirodex.utils.arr_connectors import client_error_message

        return client_error_message(exc, noun='indexer') if indexer else client_error_message(exc)


def create_acquire_actions_router(
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
    data = data_access or AcquireActionData()

    @router.api_route('/api/acquire/search', methods=['GET', 'HEAD'])
    def acquire_search(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            else:
                from oneirodex.utils.role_catalog import normalize_role

                role = normalize_role(getattr(auth.user, 'role', None))
                if role == 'child':
                    response = _error('Acquire search is not available on child accounts', 'forbidden')
                elif not data.arr_enabled(config=flask_app.config):
                    response = _error('Arr module disabled', 'forbidden')
                else:
                    query = (_first(request, 'q') or '').strip()
                    current_label = (_first(request, 'current') or '').strip()
                    if not query:
                        response = _error('q required', 'bad_request')
                    else:
                        try:
                            response = JSONResponse(data.search(query, current_label=current_label))
                        except Exception as exc:
                            response = _error(data.safe_error(exc, indexer=True), 'bad_gateway')
            _finish(response, flask_app, request, auth)
            return response

    @router.post('/api/acquire/download')
    async def acquire_download(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = _auth(request, flask_app, find_user, find_token, commit_token_touch,
                         load_user_id, login_manager)
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None:
                from oneirodex.utils.role_catalog import role_at_least

                if not _librarian(auth.user, auth.token, role_at_least):
                    response = _error('Librarian or admin required', 'forbidden')
                else:
                    body, response = await _validated(request)
                    if response is None:
                        url = (body.url or body.magnet or '').strip()
                        provider = (body.provider or 'qbittorrent').strip().lower()
                        if url.lower().startswith(('http://', 'https://')):
                            ok, checked = data.validate_url(url)
                            if not ok:
                                response = _error(checked, 'bad_request')
                            else:
                                url = checked
                        if response is None:
                            if provider in ('qbittorrent', 'transmission', 'sabnzbd', 'nzbget', 'deluge'):
                                enabled = data.arr_enabled(config=flask_app.config)
                                unavailable_message = 'Arr module disabled'
                            elif provider in ('real_debrid', 'alldebrid', 'premiumize', 'torbox'):
                                enabled = data.debrid_enabled()
                                unavailable_message = 'Debrid disabled'
                            else:
                                enabled = False
                                unavailable_message = 'Unknown provider'
                            if unavailable_message == 'Unknown provider':
                                response = _error(unavailable_message, 'bad_request')
                            elif not enabled:
                                response = _error(unavailable_message, 'forbidden')
                            else:
                                try:
                                    result = data.send(url, provider)
                                except Exception as exc:
                                    response = _error(data.safe_error(exc), 'bad_gateway')
                                else:
                                    response = _success({'provider': provider, 'result': result})
            _finish(response, flask_app, request, auth)
            return response

    return router


def mount_acquire_actions_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_acquire_actions_router(flask_app, **kwargs))
    return app


async def _validated(request):
    import json

    from oneirodex.schemas.acquire import AcquireDownloadBody
    from oneirodex.utils.api_contract import api_error_payload
    from oneirodex.utils.validation import format_validation_errors

    try:
        raw = json.loads(await request.body() or b'{}')
    except (TypeError, ValueError):
        raw = {}
    try:
        body = AcquireDownloadBody.model_validate(raw if isinstance(raw, dict) else {})
    except ValidationError as exc:
        payload, status = api_error_payload(
            'Invalid request.', code='unprocessable',
            detail=format_validation_errors(exc),
        )
        return None, JSONResponse(payload, status_code=status)
    return body, None


def _librarian(user, token, role_at_least):
    return (
        bool(getattr(user, 'is_authenticated', True))
        and role_at_least(getattr(user, 'role', None), 'librarian')
        and (token is None or token.has_scope('admin'))
    )


def _auth(request, flask_app, find_user, find_token, commit_token_touch, load_user_id, login_manager):
    return request_auth_context(
        request, flask_app.config, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager,
    )


def _first(request, key):
    values = request.query_params.getlist(key)
    return values[0] if values else None


def _error(message, code):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


def _success(payload):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload))


def _from_flask(response, status):
    from .oidc_status import _from_flask_response

    return _from_flask_response(response, status)


def _finish(response, flask_app, request, auth):
    if auth.should_set_session_cookie:
        _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
