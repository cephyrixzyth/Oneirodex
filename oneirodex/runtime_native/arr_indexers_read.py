"""Native admin read for saved *arr indexers and local presets."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class ArrIndexersData:
    def read(self) -> dict:
        from oneirodex.utils.indexer_registry import (
            indexer_public_view,
            list_indexers,
            load_indexer_presets,
        )

        return {
            'indexers': [indexer_public_view(row) for row in list_indexers()],
            'presets': load_indexer_presets(),
        }

    def read_one(self, indexer_id: str) -> dict | None:
        from oneirodex.utils.indexer_registry import get_indexer, indexer_public_view

        row = get_indexer(indexer_id)
        return {'indexer': indexer_public_view(row)} if row else None

    def create(self, payload: dict) -> dict:
        from oneirodex.utils.indexer_registry import add_indexer, indexer_public_view

        return indexer_public_view(add_indexer(payload))

    def update(self, indexer_id: str, payload: dict) -> dict:
        from oneirodex.utils.indexer_registry import indexer_public_view, update_indexer

        return indexer_public_view(update_indexer(indexer_id, payload))

    def delete(self, indexer_id: str) -> bool:
        from oneirodex.utils.indexer_registry import delete_indexer

        return delete_indexer(indexer_id)

    def bulk_import(self, payload) -> list[dict]:
        from oneirodex.utils.indexer_registry import bulk_import_indexers, indexer_public_view

        return [indexer_public_view(row) for row in bulk_import_indexers(payload)]

    def enable_presets(self, preset_ids: list[str]) -> list[dict]:
        from oneirodex.utils.indexer_registry import enable_presets, indexer_public_view

        return [indexer_public_view(row) for row in enable_presets(preset_ids)]

    def module_status(self, *, config) -> dict:
        from oneirodex.utils.module_status import arr_db_enabled, arr_module_on, env_flag

        env_enabled = env_flag('ENABLE_ARR_MODULE', config=config)
        return {
            'enabled': arr_module_on(config=config),
            'db_enabled': arr_db_enabled(),
            'env_enabled': env_enabled,
        }

    def save_module_status(self, enabled: bool, *, config) -> dict:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.module_status import ensure_global_settings

        settings = ensure_global_settings()
        settings.enable_arr_module = enabled
        db.session.commit()
        return {
            'status': 'saved',
            'enabled': self.module_status(config=config)['enabled'],
            'db_enabled': bool(settings.enable_arr_module),
            'env_enabled': self.module_status(config=config)['env_enabled'],
        }

    def search(self, query: str, *, limit: int, include_disallowed: bool) -> dict:
        from oneirodex.utils.arr_connectors import client_error_message, search_indexers
        from oneirodex.utils.indexer_registry import indexer_status_summary
        from oneirodex.utils.quality_profiles import score_release_title

        try:
            hits = search_indexers(query, limit=limit)
        except RuntimeError as exc:
            raise ValueError(client_error_message(exc, noun='indexer')) from exc
        results = []
        excluded = 0
        for hit in hits:
            payload = hit.to_dict()
            quality = score_release_title(hit.title, size_bytes=hit.size)
            payload['quality'] = quality
            if not quality.get('allowed', True) and not include_disallowed:
                excluded += 1
                continue
            results.append(payload)
        results.sort(key=lambda item: item['quality']['score'], reverse=True)
        return {
            'query': query,
            'results': results,
            'excluded_by_quality': excluded,
            'warnings': indexer_status_summary().get('warnings') or [],
        }

    def download(self, url: str):
        from oneirodex.utils.arr_connectors import qbittorrent_add_url

        return qbittorrent_add_url(url)

    def hardlink_preview(self, dest: str, *, limit: int, app):
        from oneirodex.utils.arr_hardlink_pipeline import propose_hardlinks

        return propose_hardlinks(dest, limit=limit, app=app)

    def hardlink_apply(self, proposals: list[dict], *, only_ok: bool, app):
        from oneirodex.utils.arr_hardlink_pipeline import apply_proposals

        return apply_proposals(proposals, only_ok=only_ok, app=app)


def create_arr_indexers_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    module_enabled: Callable[..., bool] | None = None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ArrIndexersData()
    if module_enabled is None:
        from oneirodex.utils.module_status import arr_module_on

        module_enabled = arr_module_on

    @router.api_route('/api/arr/indexers', methods=['GET', 'HEAD', 'POST'])
    @router.api_route(
        '/api/arr/indexers/{indexer_id}',
        methods=['GET', 'HEAD', 'PUT', 'PATCH', 'DELETE'],
    )
    @router.api_route('/api/arr/indexers/bulk', methods=['POST'])
    @router.api_route('/api/arr/indexers/enable-presets', methods=['POST'])
    @router.api_route('/api/arr/module', methods=['GET', 'HEAD', 'PUT'])
    @router.api_route('/api/arr/search', methods=['GET', 'HEAD'])
    @router.api_route('/api/arr/download', methods=['POST'])
    @router.api_route('/api/arr/hardlink/preview', methods=['POST'])
    @router.api_route('/api/arr/hardlink/apply', methods=['POST'])
    async def arr_indexers(request: Request, indexer_id: str | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            writing = request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
            if writing:
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
                    request,
                    flask_app.config,
                    find_user=find_user,
                    find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id,
                    login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload
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
                elif request.url.path not in ('/api/arr/module',) and not module_enabled(config=flask_app.config):
                    payload, status = api_error_payload(
                        'Arr module is disabled', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif request.url.path == '/api/arr/module':
                    if request.method == 'PUT':
                        try:
                            body = await request.json()
                        except Exception:
                            body = {}
                        if not isinstance(body, dict) or not ({'enabled', 'enable_arr_module'} & body.keys()):
                            payload, status = api_error_payload('enabled is required', code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            enabled = bool(body.get('enabled', body.get('enable_arr_module')))
                            try:
                                result = data.save_module_status(enabled, config=flask_app.config)
                            except Exception:
                                from oneirodex.runtime_native.db_session import native_db as db
                                import logging
                                db.session.rollback()
                                logging.getLogger(__name__).warning('Could not save Arr module status')
                                payload, status = api_error_payload('Could not save Arr module status', code='internal')
                                response = JSONResponse(payload, status_code=status)
                            else:
                                from oneirodex.utils.api_contract import api_ok_payload
                                response = JSONResponse(api_ok_payload(result))
                    else:
                        response = JSONResponse(data.module_status(config=flask_app.config))
                elif request.url.path == '/api/arr/search':
                    query = (request.query_params.get('q') or request.query_params.get('query') or '').strip()
                    if not query:
                        payload, status = api_error_payload('Query parameter q is required', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            limit = min(int(request.query_params.get('limit') or 25), 50)
                        except (TypeError, ValueError):
                            limit = 25
                        include_disallowed = (request.query_params.get('include_disallowed') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
                        try:
                            response = JSONResponse(data.search(
                                query, limit=limit, include_disallowed=include_disallowed,
                            ))
                        except ValueError as exc:
                            payload, status = api_error_payload(str(exc), code='bad_gateway')
                            response = JSONResponse(payload, status_code=status)
                elif request.method == 'POST':
                    try:
                        body = await request.json()
                    except Exception:
                        body = None
                    if request.url.path == '/api/arr/download':
                        from pydantic import ValidationError
                        from oneirodex.schemas.arr import ArrDownloadBody
                        from oneirodex.utils.validation import format_validation_errors

                        try:
                            model = ArrDownloadBody.model_validate(body if isinstance(body, dict) else {})
                        except ValidationError as exc:
                            payload, status = api_error_payload(
                                'Invalid request.', code='unprocessable',
                                detail=format_validation_errors(exc),
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            url = (model.download_url or model.url or '').strip()
                            if url.lower().startswith(('http://', 'https://')):
                                from oneirodex.utils.security import validate_user_outbound_http_url

                                ok, result = validate_user_outbound_http_url(url)
                                if not ok:
                                    payload, status = api_error_payload(result, code='bad_request')
                                    response = JSONResponse(payload, status_code=status)
                                    url = ''
                                else:
                                    url = result
                            if url:
                                try:
                                    result = data.download(url)
                                except Exception as exc:
                                    from oneirodex.utils.arr_connectors import client_error_message
                                    import requests

                                    if isinstance(exc, (RuntimeError, requests.RequestException)):
                                        code = 'bad_gateway'
                                    elif isinstance(exc, ValueError):
                                        code = 'bad_request'
                                    else:
                                        code = 'internal'
                                    payload, status = api_error_payload(
                                        client_error_message(exc, noun='qBittorrent server')
                                        if code != 'internal' else 'Could not send the download to the client',
                                        code=code,
                                    )
                                    response = JSONResponse(payload, status_code=status)
                                else:
                                    from oneirodex.utils.api_contract import api_ok_payload

                                    response = JSONResponse(api_ok_payload(result), status_code=202)
                    elif request.url.path in ('/api/arr/hardlink/preview', '/api/arr/hardlink/apply'):
                        from oneirodex.utils.arr_hardlink_pipeline import pipeline_enabled

                        if not pipeline_enabled(config=flask_app.config):
                            payload, status = api_error_payload(
                                'Arr-hardlink pipeline is disabled. Set ENABLE_ARR_HARDLINK_PIPELINE=true.',
                                code='forbidden',
                            )
                            response = JSONResponse(payload, status_code=status)
                        elif request.url.path.endswith('/preview'):
                            from pydantic import ValidationError
                            from oneirodex.schemas.arr import ArrHardlinkPreviewBody
                            from oneirodex.utils.validation import format_validation_errors

                            try:
                                model = ArrHardlinkPreviewBody.model_validate(body if isinstance(body, dict) else {})
                            except ValidationError as exc:
                                payload, status = api_error_payload(
                                    'Invalid request.', code='unprocessable',
                                    detail=format_validation_errors(exc),
                                )
                                response = JSONResponse(payload, status_code=status)
                            else:
                                dest = (model.library_dest_dir or model.dest_dir or '').strip()
                                try:
                                    limit = min(int(model.limit or 50), 200)
                                except (TypeError, ValueError):
                                    limit = 50
                                try:
                                    result = data.hardlink_preview(dest, limit=limit, app=flask_app)
                                except ValueError as exc:
                                    payload, status = api_error_payload(str(exc), code='bad_request')
                                    response = JSONResponse(payload, status_code=status)
                                except PermissionError as exc:
                                    payload, status = api_error_payload(str(exc), code='forbidden')
                                    response = JSONResponse(payload, status_code=status)
                                except RuntimeError as exc:
                                    payload, status = api_error_payload(str(exc), code='bad_gateway')
                                    response = JSONResponse(payload, status_code=status)
                                else:
                                    response = JSONResponse(result)
                        else:
                            payload_data = body if isinstance(body, dict) else {}
                            proposals = payload_data.get('proposals')
                            response = None
                            if not isinstance(proposals, list) or not proposals:
                                dest = str(payload_data.get('library_dest_dir') or payload_data.get('dest_dir') or '').strip()
                                if not dest:
                                    payload, status = api_error_payload('proposals or library_dest_dir required', code='bad_request')
                                    response = JSONResponse(payload, status_code=status)
                                    proposals = []
                                else:
                                    try:
                                        limit = int(payload_data.get('limit') or 50)
                                        preview = data.hardlink_preview(dest, limit=limit, app=flask_app)
                                        proposals = preview.get('proposals') or []
                                    except ValueError as exc:
                                        payload, status = api_error_payload(str(exc), code='bad_request')
                                        response = JSONResponse(payload, status_code=status)
                                        proposals = []
                                    except PermissionError as exc:
                                        payload, status = api_error_payload(str(exc), code='forbidden')
                                        response = JSONResponse(payload, status_code=status)
                                        proposals = []
                                    except RuntimeError as exc:
                                        payload, status = api_error_payload(str(exc), code='bad_gateway')
                                        response = JSONResponse(payload, status_code=status)
                                        proposals = []
                            if response is None:
                                try:
                                    result = data.hardlink_apply(
                                        proposals, only_ok=bool(payload_data.get('only_ok', True)),
                                        app=flask_app,
                                    )
                                except PermissionError as exc:
                                    payload, status = api_error_payload(str(exc), code='forbidden')
                                    response = JSONResponse(payload, status_code=status)
                                else:
                                    response = JSONResponse(result, status_code=201)
                    elif request.url.path == '/api/arr/indexers/bulk':
                        if body is None:
                            body = (await request.body()).decode('utf-8', errors='replace').strip()
                        try:
                            created = data.bulk_import(body)
                        except ValueError as exc:
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        except Exception:
                            payload, status = api_error_payload(
                                'Could not import indexers', code='bad_request'
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            from oneirodex.utils.api_contract import api_ok_payload

                            response = JSONResponse(api_ok_payload({
                                'status': 'imported', 'count': len(created),
                                'indexers': created,
                            }), status_code=201)
                    elif request.url.path == '/api/arr/indexers/enable-presets':
                        preset_ids = body.get('preset_ids') or body.get('ids') or [] if isinstance(body, dict) else []
                        if not isinstance(preset_ids, list):
                            payload, status = api_error_payload(
                                'preset_ids must be an array', code='bad_request'
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            try:
                                created = data.enable_presets(preset_ids)
                            except KeyError as exc:
                                payload, status = api_error_payload(
                                    f'Unknown preset_id: {exc.args[0]}', code='not_found'
                                )
                                response = JSONResponse(payload, status_code=status)
                            except ValueError as exc:
                                payload, status = api_error_payload(str(exc), code='bad_request')
                                response = JSONResponse(payload, status_code=status)
                            else:
                                from oneirodex.utils.api_contract import api_ok_payload

                                response = JSONResponse(api_ok_payload({
                                    'status': 'enabled', 'count': len(created),
                                    'indexers': created,
                                }), status_code=201)
                    else:
                        try:
                            created = data.create(body if isinstance(body, dict) else {})
                        except ValueError as exc:
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            from oneirodex.utils.api_contract import api_ok_payload

                            response = JSONResponse(
                                api_ok_payload({'status': 'created', 'indexer': created}),
                                status_code=201,
                            )
                elif request.method in ('PUT', 'PATCH'):
                    try:
                        body = await request.json()
                    except Exception:
                        body = None
                    try:
                        updated = data.update(
                            indexer_id or '', body if isinstance(body, dict) else {}
                        )
                    except KeyError:
                        payload, status = api_error_payload('Indexer not found', code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    except ValueError as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(
                            api_ok_payload({'status': 'saved', 'indexer': updated})
                        )
                elif request.method == 'DELETE':
                    if not data.delete(indexer_id or ''):
                        payload, status = api_error_payload('Indexer not found', code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({
                            'status': 'deleted', 'id': indexer_id,
                        }))
                elif indexer_id is not None:
                    payload = data.read_one(indexer_id)
                    if payload is None:
                        payload, status = api_error_payload('Indexer not found', code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        response = JSONResponse(payload)
                else:
                    response = JSONResponse(data.read())

        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_arr_indexers_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_arr_indexers_router(flask_app, **kwargs))
    return app
