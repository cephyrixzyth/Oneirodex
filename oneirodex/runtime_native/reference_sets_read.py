"""Native admin read for the ROM reference-set catalogue and upload limits."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context

MAX_DAT_BYTES = 32 * 1024 * 1024


class ReferenceSetsData:
    def read_sets(self) -> dict:
        from oneirodex.utils.set_completion import list_reference_sets

        return {'sets': list_reference_sets()}

    def completion(self, *, platform: str, region: str, user, include_matched: bool, missing_limit: int | None):
        from oneirodex.utils.set_completion import compute_set_completion

        return compute_set_completion(
            library_platform=platform,
            region=region,
            user=user,
            include_matched=include_matched,
            missing_limit=missing_limit,
        )

    def rehash(self, platform: str) -> dict:
        from oneirodex.utils.set_completion import rehash_library_platform

        return rehash_library_platform(platform)

    def repair_preview(self, *, platform: str, region: str | None, user, limit: int | None):
        from oneirodex.utils.set_repair import repair_preview

        return repair_preview(
            library_platform=platform, region=region, user=user, limit=limit,
        )

    def read(self) -> dict:
        from oneirodex.platform import LibraryPlatform, NATIVE_PC_PLATFORMS
        from oneirodex.utils.functions import igdb_platform_id_for
        from oneirodex.utils.set_completion import (
            REGION_PREF_ORDER,
            VALID_SOURCES,
            list_reference_sets,
        )

        platforms = sorted(
            [{'id': platform.name, 'label': platform.value} for platform in LibraryPlatform],
            key=lambda row: row['label'].lower(),
        )
        return {
            'sets': list_reference_sets(),
            'platforms': platforms,
            'catalog_platforms': [
                platform for platform in platforms
                if platform['id'] not in NATIVE_PC_PLATFORMS
                and igdb_platform_id_for(platform['id']) is not None
            ],
            'regions': list(REGION_PREF_ORDER),
            'sources': sorted(VALID_SOURCES),
            'max_dat_bytes': MAX_DAT_BYTES,
        }

    def upload(self, *, platform: str, region: str, source: str, raw: bytes, uploader_id: int | None, replace: bool, name: str | None = None):
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.set_completion import (
            ReferenceSetReplacementConflict,
            list_reference_sets,
            normalize_region,
            upsert_reference_set,
            validate_library_platform,
        )

        platform = validate_library_platform(platform)
        existing = next((
            row for row in list_reference_sets()
            if row['library_platform'] == platform
            and row['region'] == normalize_region(region)
        ), None)
        if existing and not replace:
            return 'conflict', None
        try:
            reference_set = upsert_reference_set(
                library_platform=platform,
                region=region,
                source=source,
                dat_bytes=raw,
                name=name,
                uploader_id=uploader_id,
                allow_replace=replace,
            )
        except ReferenceSetReplacementConflict:
            return 'conflict', None
        log_system_event(
            f'Reference set uploaded: {reference_set.library_platform}/{reference_set.region} '
            f'({reference_set.entry_count} entries)',
            event_type='admin', event_level='information',
        )
        return 'created', reference_set.to_dict()

    def delete(self, set_id: int) -> bool:
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.set_completion import delete_reference_set

        if not delete_reference_set(set_id):
            return False
        log_system_event(
            f'Reference set deleted: id={set_id}',
            event_type='admin', event_level='information',
        )
        return True


def create_reference_sets_router(
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
    data = data_access or ReferenceSetsData()

    @router.api_route('/api/set-completion', methods=['GET', 'HEAD'])
    def set_completion(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.api_contract import api_error_payload

            if auth.user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            else:
                platform = (request.query_params.get('library_platform') or request.query_params.get('platform') or '').strip()
                region = (request.query_params.get('region') or 'USA').strip()
                include_matched = request.query_params.get('include_matched', '0').lower() in ('1', 'true', 'yes')
                try:
                    missing_limit = int(request.query_params.get('missing_limit'))
                except (TypeError, ValueError):
                    missing_limit = None
                if not platform:
                    payload, status = api_error_payload('library_platform required', code='bad_request')
                    response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        report = data.completion(
                            platform=platform, region=region, user=auth.user,
                            include_matched=include_matched, missing_limit=missing_limit,
                        )
                        if report is None:
                            from oneirodex.utils.set_completion import REGION_PREF_ORDER, VALID_SOURCES

                            payload, status = api_error_payload(
                                f'No reference set for {platform}/{region}', code='not_found',
                                library_platform=platform, region=region,
                                valid_regions=list(REGION_PREF_ORDER),
                                valid_sources=sorted(VALID_SOURCES),
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(report)
                    except ValueError as exc:
                        payload, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(payload, status_code=status)

        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    @router.api_route('/api/reference-sets/rehash', methods=['POST'])
    @router.api_route('/api/reference-sets/repair-preview', methods=['POST'])
    async def reference_set_admin_actions(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            from .csrf_compat import csrf_error_response
            from .request_auth import _lifetime_seconds
            from .session_compat import load_session_cookie

            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            ) if csrf_response is None else None
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user if auth is not None else None
            is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and (
                normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
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
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif request.url.path.endswith('/rehash'):
                try:
                    if 'application/json' in request.headers.get('content-type', ''):
                        try:
                            payload = await request.json()
                        except ValueError:
                            payload = {}
                        payload = payload if isinstance(payload, dict) else {}
                        platform = str(payload.get('library_platform') or payload.get('platform') or '').strip()
                    else:
                        form = await request.form(max_files=0, max_fields=4)
                        platform = str(form.get('library_platform') or form.get('platform') or '').strip()
                    if not platform:
                        payload, status = api_error_payload('library_platform required', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        result = data.rehash(platform)
                        response = JSONResponse(result)
                except ValueError as exc:
                    payload, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(payload, status_code=status)
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    payload, status = api_error_payload('Could not rehash the library platform', code='internal')
                    response = JSONResponse(payload, status_code=status)
            else:
                from pydantic import ValidationError
                from oneirodex.schemas.reference_sets import RepairPreviewBody
                from oneirodex.utils.validation import format_validation_errors

                try:
                    try:
                        raw_payload = await request.json()
                    except ValueError:
                        raw_payload = {}
                    model = RepairPreviewBody.model_validate(raw_payload if isinstance(raw_payload, dict) else {})
                    report = data.repair_preview(
                        platform=model.library_platform, region=model.region,
                        user=user, limit=model.limit,
                    )
                    if report is None:
                        payload, status = api_error_payload(
                            'No reference set for this platform' + (f'/{model.region}' if model.region else ''),
                            code='not_found', library_platform=model.library_platform,
                            region=model.region,
                        )
                        response = JSONResponse(payload, status_code=status)
                    else:
                        response = JSONResponse(api_ok_payload(report))
                except ValidationError as exc:
                    payload, status = api_error_payload(
                        'Invalid request.', code='unprocessable',
                        detail=format_validation_errors(exc),
                    )
                    response = JSONResponse(payload, status_code=status)
                except ValueError as exc:
                    payload, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(payload, status_code=status)
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    payload, status = api_error_payload('Could not build the reference-set repair preview', code='internal')
                    response = JSONResponse(payload, status_code=status)

        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        return response

    @router.api_route('/api/reference-sets', methods=['GET', 'HEAD', 'POST'])
    @router.api_route('/api/reference-sets/{set_id}', methods=['DELETE'])
    async def api_reference_sets(request: Request, set_id: int | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method in ('POST', 'DELETE'):
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            ) if csrf_response is None else None
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user if auth is not None else None
            is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and (
                normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            response = None
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message=getattr(login_manager, 'login_message', None),
                    category=getattr(login_manager, 'login_message_category', 'message'),
                    include_next=True,
                )
            elif request.method in ('POST', 'DELETE') and not is_admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif request.method in ('POST', 'DELETE') and auth.token is not None and not auth.has_scope('admin'):
                payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            elif request.method in ('GET', 'HEAD'):
                try:
                    from .runtime_context import NativeJSONProvider
                    from starlette.responses import Response

                    provider = NativeJSONProvider(flask_app.config)
                    body = (provider.dumps(data.read_sets(), separators=(',', ':')) + '\n').encode('utf-8')
                    response = Response(body, media_type=provider.mimetype)
                except Exception:
                    payload, status = api_error_payload('Could not load reference sets', code='internal')
                    response = JSONResponse(payload, status_code=status)
            elif request.method == 'POST':
                form = await request.form(max_files=1, max_fields=12, max_part_size=64 * 1024)
                upload = form.get('file') or form.get('dat')
                if upload is None or not getattr(upload, 'filename', None):
                    payload, status = api_error_payload('DAT file required', code='bad_request')
                    response = JSONResponse(payload, status_code=status)
                else:
                    platform = str(form.get('library_platform') or form.get('platform') or '').strip()
                    region = str(form.get('region') or 'USA').strip()
                    source = str(form.get('source') or 'nointro').strip()
                    name = str(form.get('name') or '').strip() or None
                    try:
                        raw = await upload.read(MAX_DAT_BYTES + 1)
                    finally:
                        await upload.close()
                    if len(raw) > MAX_DAT_BYTES:
                        payload, status = api_error_payload(f'DAT too large (max {MAX_DAT_BYTES} bytes)', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    elif not raw:
                        payload, status = api_error_payload('Empty DAT file', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        try:
                            result, reference_set = data.upload(
                                platform=platform, region=region, source=source, raw=raw,
                                uploader_id=getattr(user, 'id', None), replace=False, name=name,
                            )
                            if result == 'conflict':
                                payload, status = api_error_payload(
                                    'A set already exists for this platform and region. Confirm replacement before uploading.',
                                    code='conflict',
                                )
                                response = JSONResponse(payload, status_code=status)
                            else:
                                response = JSONResponse(reference_set, status_code=201)
                        except ValueError as exc:
                            from oneirodex.runtime_native.db_session import native_db as db
                            db.session.rollback()
                            payload, status = api_error_payload(str(exc), code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        except Exception:
                            from oneirodex.runtime_native.db_session import native_db as db
                            db.session.rollback()
                            payload, status = api_error_payload('Could not upload the reference set', code='internal')
                            response = JSONResponse(payload, status_code=status)
            else:
                try:
                    target_id = int(set_id or 0)
                    if not data.delete(target_id):
                        payload, status = api_error_payload('Not found', code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        response = JSONResponse(api_ok_payload({'id': target_id}))
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    payload, status = api_error_payload('Could not delete the reference set', code='internal')
                    response = JSONResponse(payload, status_code=status)

        from oneirodex.utils.security_headers import security_header_values
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    @router.post('/admin/reference_sets')
    @router.api_route('/api/admin/reference-sets', methods=['GET', 'HEAD', 'POST'])
    @router.api_route('/api/admin/reference-sets/{set_id}', methods=['DELETE'])
    async def reference_sets(request: Request, set_id: int | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            legacy_form = request.url.path == '/admin/reference_sets'
            parsed_form = None
            form = None
            csrf_response = None
            if request.method in ('POST', 'DELETE'):
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
                if csrf_response is None and not legacy_form:
                    csrf_response = csrf_error_response(
                        request, session_data, flask_app.config,
                    )
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            ) if csrf_response is None else None
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            user = auth.user if auth is not None else None
            is_admin = user is not None and bool(getattr(user, 'is_authenticated', True)) and (
                normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            response = None
            if (
                legacy_form and request.method in ('POST', 'DELETE')
                and is_admin and auth is not None
                and (auth.token is None or auth.has_scope('admin'))
            ):
                from .bounded_multipart import (
                    InvalidContentLength, RequestBodyTooLarge,
                    bounded_multipart_form,
                )

                try:
                    parsed_form = await bounded_multipart_form(
                        request, max_body_bytes=MAX_DAT_BYTES + 64 * 1024,
                        max_files=1, max_fields=10, max_part_size=64 * 1024,
                    )
                    csrf_response = csrf_error_response(
                        request, auth.session_data, flask_app.config,
                        token=str(parsed_form.get('csrf_token') or ''),
                    )
                except RequestBodyTooLarge:
                    payload, status = api_error_payload(
                        'DAT too large (max 32 MiB)', code='payload_too_large',
                    )
                    csrf_response = JSONResponse(payload, status_code=status)
                except InvalidContentLength:
                    payload, status = api_error_payload(
                        'Invalid request size.', code='bad_request',
                    )
                    csrf_response = JSONResponse(payload, status_code=status)
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
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
            elif request.method == 'POST':
                form = parsed_form
                if form is None:
                    from .bounded_multipart import (
                        InvalidContentLength, RequestBodyTooLarge,
                        bounded_multipart_form,
                    )

                    try:
                        form = await bounded_multipart_form(
                            request, max_body_bytes=MAX_DAT_BYTES + 64 * 1024,
                            max_files=1, max_fields=10, max_part_size=64 * 1024,
                        )
                    except RequestBodyTooLarge:
                        payload, status = api_error_payload(
                            'DAT too large (max 32 MiB)', code='payload_too_large',
                        )
                        response = JSONResponse(payload, status_code=status)
                    except InvalidContentLength:
                        payload, status = api_error_payload(
                            'Invalid request size.', code='bad_request',
                        )
                        response = JSONResponse(payload, status_code=status)
                if form is None:
                    form = {}
                if response is not None:
                    pass
                elif legacy_form and str(form.get('action') or 'upload').strip() == 'delete':
                    try:
                        target_id = int(form.get('set_id') or '0')
                        deleted = target_id > 0 and data.delete(target_id)
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        db.session.rollback()
                        deleted = False
                    message = 'Reference set deleted' if deleted else 'Reference set not found'
                    category = 'success' if deleted else 'error'
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append((category, message))
                    auth.session_data['_flashes'] = flashes
                    response = RedirectResponse(
                        '/admin/reference_sets', status_code=302,
                        headers={'Content-Type': 'text/html; charset=utf-8'},
                    )
                    _set_session_cookie(response, flask_app, auth)
                else:
                    upload = form.get('file')
                    if upload is None or not getattr(upload, 'filename', None):
                        payload, status = api_error_payload('DAT file required', code='bad_request')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        platform = str(form.get('library_platform') or '').strip()
                        region = str(form.get('region') or 'USA').strip()
                        source = str(form.get('source') or 'nointro').strip()
                        if any(len(value) > 64 or any(ord(char) < 32 for char in value) for value in (platform, region, source)):
                            payload, status = api_error_payload('Invalid platform, region, or source', code='bad_request')
                            response = JSONResponse(payload, status_code=status)
                        else:
                            try:
                                raw = await upload.read(MAX_DAT_BYTES + 1)
                            finally:
                                await upload.close()
                            if len(raw) > MAX_DAT_BYTES:
                                payload, status = api_error_payload('DAT too large (max 32 MiB)', code='bad_request')
                                response = JSONResponse(payload, status_code=status)
                            elif not raw:
                                payload, status = api_error_payload('Empty DAT file', code='bad_request')
                                response = JSONResponse(payload, status_code=status)
                            else:
                                try:
                                    result, reference_set = data.upload(
                                        platform=platform, region=region, source=source, raw=raw,
                                        uploader_id=getattr(user, 'id', None),
                                        replace=str(form.get('replace') or '') == 'true',
                                    )
                                    if result == 'conflict':
                                        payload, status = api_error_payload(
                                            'A set already exists for this platform and region. Confirm replacement before uploading.',
                                            code='conflict',
                                        )
                                        response = JSONResponse(payload, status_code=status)
                                    else:
                                        response = JSONResponse(api_ok_payload({'reference_set': reference_set}), status_code=201)
                                except ValueError:
                                    from oneirodex.runtime_native.db_session import native_db as db
                                    db.session.rollback()
                                    payload, status = api_error_payload(
                                        'Could not parse the DAT. Check its contents and selected platform.',
                                        code='bad_request',
                                    )
                                    response = JSONResponse(payload, status_code=status)
                                except Exception:
                                    from oneirodex.runtime_native.db_session import native_db as db
                                    import logging
                                    db.session.rollback()
                                    logging.getLogger(__name__).warning('Could not upload the reference set')
                                    payload, status = api_error_payload('Could not upload the reference set', code='internal')
                                    response = JSONResponse(payload, status_code=status)
            elif request.method == 'DELETE':
                try:
                    if not data.delete(int(set_id or 0)):
                        payload, status = api_error_payload('Reference set not found', code='not_found')
                        response = JSONResponse(payload, status_code=status)
                    else:
                        response = JSONResponse(api_ok_payload({'id': int(set_id or 0)}))
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    import logging
                    db.session.rollback()
                    logging.getLogger(__name__).warning('Could not delete the reference set')
                    payload, status = api_error_payload('Could not delete the reference set', code='internal')
                    response = JSONResponse(payload, status_code=status)
            else:
                try:
                    response = JSONResponse(api_ok_payload(data.read()))
                except Exception:
                    import logging
                    logging.getLogger(__name__).warning('Could not load reference sets')
                    payload, status = api_error_payload('Could not load reference sets', code='internal')
                    response = JSONResponse(payload, status_code=status)
            if (
                legacy_form
                and request.method == 'POST'
                and csrf_response is None
                and auth is not None
                and is_admin
                and (auth.token is None or auth.has_scope('admin'))
                and not isinstance(response, RedirectResponse)
            ):
                import json
                try:
                    body = json.loads(response.body or b'{}')
                except (TypeError, ValueError, UnicodeDecodeError):
                    body = {}
                reference_set = body.get('reference_set') if isinstance(body, dict) else None
                if response.status_code == 201:
                    message = f"Uploaded {reference_set.get('name') or 'reference set'}" if isinstance(reference_set, dict) else 'Reference set uploaded'
                    category = 'success'
                else:
                    message = body.get('message') if isinstance(body, dict) else None
                    message = message or 'Could not upload the reference set'
                    category = 'error'
                flashes = list(auth.session_data.get('_flashes') or [])
                flashes.append((category, message))
                auth.session_data['_flashes'] = flashes
                response = RedirectResponse(
                    '/admin/reference_sets', status_code=302,
                    headers={'Content-Type': 'text/html; charset=utf-8'},
                )
                _set_session_cookie(response, flask_app, auth)

            if parsed_form is not None:
                for value in parsed_form.values():
                    close_upload = getattr(value, 'close', None)
                    if callable(close_upload):
                        await close_upload()
            if form is not None and form is not parsed_form:
                close_form = getattr(form, 'close', None)
                if callable(close_form):
                    await close_form()

        from oneirodex.utils.security_headers import security_header_values

        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    return router


def mount_reference_sets_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_reference_sets_router(flask_app, **kwargs))
    return app
