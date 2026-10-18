"""Native FastAPI read for the member-visible library catalogue."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .request_auth import request_auth_context


class LibraryReadData:
    def library(self, library_uuid: str):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library

        return db.session.execute(
            select(Library).filter_by(uuid=library_uuid)
        ).scalars().first()

    def can_access(self, user, library_uuid: str) -> bool:
        from oneirodex.utils.library_acl import user_can_access_library

        return bool(user_can_access_library(user, library_uuid))

    @staticmethod
    def public_fields(library) -> dict:
        from oneirodex.utils.library_watch import (
            is_library_watch_enabled, library_watch_effective,
        )

        raw = (getattr(library, 'image_url', None) or '').strip()
        if not raw:
            image_url = '/static/newstyle/default_library.jpg'
        elif raw.startswith(('/', 'http://', 'https://')):
            image_url = raw
        elif '/' not in raw and '\\' not in raw:
            image_url = f'/static/library/images/{raw}'
        else:
            image_url = f"/static/{raw.lstrip('/')}"
        group = (getattr(library, 'group_name', None) or '').strip() or None
        return {
            'uuid': library.uuid,
            'name': library.name,
            'platform': library.platform.name if library.platform else None,
            'scan_depth': int(getattr(library, 'scan_depth', 1) or 1),
            'last_scan_folder': getattr(library, 'last_scan_folder', None),
            'group_name': group,
            'image_url': image_url,
            'watch_enabled': getattr(library, 'watch_enabled', None),
            'watch_effective': library_watch_effective(library),
            'watch_global_enabled': is_library_watch_enabled(),
        }

    @classmethod
    def watch_fields(cls, library) -> dict:
        values = cls.public_fields(library)
        return {
            'uuid': values['uuid'], 'name': values['name'],
            'watch_enabled': values['watch_enabled'],
            'watch_effective': values['watch_effective'],
            'watch_global_enabled': values['watch_global_enabled'],
        }

    def update_watch(self, library, value):
        from oneirodex.runtime_native.db_session import native_db as db

        library.watch_enabled = value
        db.session.commit()

    def reorder(self, order):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library

        for index, library_uuid in enumerate(order):
            library = db.session.get(Library, library_uuid)
            if library is not None:
                library.display_order = index
        db.session.commit()

    def batch_edit(self, payload, user):
        import logging

        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library, LibraryPlatform
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        from oneirodex.utils.event_logging import log_system_event
        from oneirodex.utils.library_batch import LIBRARY_BATCH_UUID_CAP, parse_library_uuids

        uuids, error = parse_library_uuids(payload)
        if error:
            return _batch_rejection(error[0], error[1])
        if len(uuids) > LIBRARY_BATCH_UUID_CAP:
            body, status = api_error_payload(
                f'No more than {LIBRARY_BATCH_UUID_CAP} libraries may be selected',
                code='bad_request', status=400, body_status='rejected',
            )
            return body, status

        item_map = {}
        raw_items = payload.get('items')
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict):
                    key = str(item.get('uuid') or item.get('library_uuid') or '').strip()
                    if key:
                        item_map[key] = item

        fields = ('scan_depth', 'watch_enabled', 'platform', 'group_name')
        if not any(field in payload for field in fields) and not item_map:
            body, status = api_error_payload(
                'Provide scan_depth and/or watch_enabled and/or platform and/or group_name (or items[])',
                code='bad_request', body_status='rejected',
            )
            return body, status

        results, updated, skipped, failed = [], 0, 0, 0
        for library_uuid in uuids:
            library = db.session.execute(
                select(Library).filter_by(uuid=library_uuid)
            ).scalars().first()
            if library is None:
                results.append({'uuid': library_uuid, 'ok': False, 'error': 'not_found'})
                failed += 1
                continue
            patch = {field: payload[field] for field in fields if field in payload}
            for field in fields:
                if library_uuid in item_map and field in item_map[library_uuid]:
                    patch[field] = item_map[library_uuid][field]
            if not patch:
                results.append({
                    'uuid': library_uuid, 'name': library.name, 'ok': False,
                    'error': 'no_fields', 'status': 'skipped',
                })
                skipped += 1
                continue

            changed = []
            try:
                for field, value in patch.items():
                    if field == 'scan_depth':
                        value = int(value)
                        if value not in (1, 2):
                            raise ValueError('scan_depth must be 1 or 2')
                    elif field == 'watch_enabled':
                        value = parse_watch_value(value)
                    elif field == 'platform':
                        raw = str(value or '').strip()
                        try:
                            value = LibraryPlatform[raw]
                        except KeyError:
                            value = LibraryPlatform(raw)
                    elif field == 'group_name':
                        value = (str(value).strip()[:80] or None) if value is not None else None
                    current = getattr(library, field, None)
                    if field == 'group_name':
                        current = (current or '').strip() or None
                    if current != value:
                        setattr(library, field, value)
                        changed.append(field)
                if not changed:
                    results.append({
                        'uuid': library_uuid, 'name': library.name, 'ok': True,
                        'status': 'unchanged', 'changed': [],
                        **self.public_fields(library),
                    })
                    skipped += 1
                    continue
                db.session.commit()
                updated += 1
                results.append({
                    'uuid': library_uuid, 'ok': True, 'status': 'updated',
                    'changed': changed, **self.public_fields(library),
                })
            except (TypeError, ValueError) as exc:
                db.session.rollback()
                results.append({
                    'uuid': library_uuid, 'name': library.name,
                    'ok': False, 'error': str(exc),
                })
                failed += 1
            except Exception:  # noqa: BLE001 — do not expose DB exception details
                db.session.rollback()
                logging.getLogger(__name__).warning('batch library edit failed')
                results.append({
                    'uuid': library_uuid, 'name': library.name,
                    'ok': False, 'error': 'Could not update library',
                })
                failed += 1
        if updated:
            log_system_event(
                f'Batch library edit by {getattr(user, "name", "admin")}: '
                f'updated={updated} skipped={skipped} failed={failed}',
                event_type='library', event_level='information',
                audit_user=getattr(user, 'id', None),
            )
        return api_ok_payload({
            'updated': updated, 'skipped': skipped, 'failed': failed,
            'count': len(uuids), 'results': results,
        }), 200

    @staticmethod
    def rollback():
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def list_for_user(self, user) -> list[dict]:
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, IgdbPlatformRelease, Library, ReferenceSet, UnmatchedFolder
        from oneirodex.utils.library_acl import filter_libraries
        from oneirodex.utils.library_watch import (
            is_library_watch_enabled, library_watch_effective,
        )
        from oneirodex.utils.platform_release_projection import platform_release_totals

        libraries = filter_libraries(
            db.session.execute(select(Library).order_by(Library.name.asc())).scalars().all(),
            user,
        )
        game_counts = {
            uuid: int(count or 0)
            for uuid, count in db.session.execute(
                select(Game.library_uuid, func.count(Game.id)).group_by(Game.library_uuid)
            ).all()
        }
        unmatched_counts = {
            uuid: int(count or 0)
            for uuid, count in db.session.execute(
                select(UnmatchedFolder.library_uuid, func.count(UnmatchedFolder.id))
                .where(UnmatchedFolder.status.in_(('Pending', 'Unmatched')))
                .group_by(UnmatchedFolder.library_uuid)
            ).all()
            if uuid
        }
        release_totals = platform_release_totals(
            db.session, IgdbPlatformRelease, ReferenceSet
        )

        def image_url(raw):
            text = (raw or '').strip()
            if not text:
                return '/static/newstyle/default_library.jpg'
            if text.startswith(('/', 'http://', 'https://')):
                return text
            if '/' not in text and '\\' not in text:
                return f'/static/library/images/{text}'
            return f"/static/{text.lstrip('/')}"

        return [{
            'uuid': library.uuid,
            'name': library.name,
            'platform': library.platform.value if library.platform else '',
            'platform_key': library.platform.name if library.platform else '',
            'game_count': game_counts.get(library.uuid, 0),
            'unmatched_count': unmatched_counts.get(library.uuid, 0),
            'platform_total': release_totals.get(
                library.platform.name if library.platform else '',
            ),
            'group_name': (getattr(library, 'group_name', None) or '').strip() or None,
            'image_url': image_url(getattr(library, 'image_url', None)),
            'last_scan_folder': library.last_scan_folder or '',
            'watch_enabled': getattr(library, 'watch_enabled', None),
            'watch_effective': library_watch_effective(library),
            'watch_global_enabled': is_library_watch_enabled(),
        } for library in libraries]


def create_library_reads_router(
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
    data = data_access or LibraryReadData()

    @router.api_route('/api/get_libraries', methods=['GET', 'HEAD'])
    def get_libraries(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = (
                _login_redirect(flask_app, request, login_manager, auth)
                if auth.user is None else JSONResponse(data.list_for_user(auth.user))
            )
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    def library_response(request: Request, library_uuid: str, *, watch=False):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None and not data.can_access(auth.user, library_uuid):
                from oneirodex.utils.api_contract import api_error_payload

                payload, status = api_error_payload('Forbidden', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            if response is None:
                library = data.library(library_uuid)
                if library is None:
                    from oneirodex.utils.api_contract import api_error_payload

                    payload, status = api_error_payload(
                        'Library not found', code='not_found',
                    )
                    response = JSONResponse(payload, status_code=status)
                else:
                    payload = data.watch_fields(library) if watch else data.public_fields(library)
                    response = JSONResponse(payload)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/library/{library_uuid}', methods=['GET', 'HEAD'])
    def get_library(library_uuid: str, request: Request):
        return library_response(request, library_uuid)

    @router.api_route('/api/admin/libraries/{library_uuid}', methods=['GET', 'HEAD'])
    def admin_library_detail(library_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = _login_redirect(flask_app, request, login_manager, auth) if auth.user is None else None
            if response is None:
                from oneirodex.utils.role_catalog import normalize_role

                if (
                    normalize_role(getattr(auth.user, 'role', None)) != 'admin'
                    or (auth.token is not None and not auth.has_scope('admin'))
                ):
                    response = _api_error('Admin required', 'forbidden')
            if response is None:
                library = data.library(library_uuid)
                if library is None:
                    response = _api_error('Library not found.', 'not_found')
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload(data.public_fields(library)))
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/library/{library_uuid}/watch', methods=['GET', 'HEAD'])
    def get_library_watch(library_uuid: str, request: Request):
        return library_response(request, library_uuid, watch=True)

    @router.put('/api/library/{library_uuid}/watch')
    async def update_library_watch(library_uuid: str, request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None and not data.can_access(auth.user, library_uuid):
                from oneirodex.utils.api_contract import api_error_payload

                payload, status = api_error_payload('Forbidden', code='forbidden')
                response = JSONResponse(payload, status_code=status)
            if response is None:
                from oneirodex.utils.role_catalog import role_at_least

                if (
                    not role_at_least(getattr(auth.user, 'role', None), 'librarian')
                    or (auth.token is not None and not auth.has_scope('admin'))
                ):
                    response = _api_error('Librarian or admin required', 'forbidden')
            if response is None:
                library = data.library(library_uuid)
                if library is None:
                    response = _api_error('Library not found', 'not_found')
                else:
                    payload = await _json_object(request)
                    if 'watch_enabled' not in payload:
                        response = _api_error(
                            'watch_enabled required (true|false|null)', 'bad_request',
                        )
                    else:
                        try:
                            raw = payload.get('watch_enabled')
                            if raw is None or (
                                isinstance(raw, str)
                                and raw.strip().lower() in ('', 'null', 'none', 'default', 'follow', 'global')
                            ):
                                value = None
                            elif isinstance(raw, bool):
                                value = raw
                            elif isinstance(raw, (int, float)):
                                value = bool(raw)
                            elif str(raw).strip().lower() in ('1', 'true', 'yes', 'on', 'enabled'):
                                value = True
                            elif str(raw).strip().lower() in ('0', 'false', 'no', 'off', 'disabled'):
                                value = False
                            else:
                                raise ValueError
                        except (TypeError, ValueError):
                            response = _api_error('Invalid watch_enabled', 'bad_request')
                        if response is None:
                            data.update_watch(library, value)
                            response = JSONResponse(data.watch_fields(library))
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/reorder_libraries')
    async def reorder_libraries(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                from oneirodex.utils.role_catalog import normalize_role

                if (
                    normalize_role(getattr(auth.user, 'role', None)) != 'admin'
                    or (auth.token is not None and not auth.has_scope('admin'))
                ):
                    response = _api_error('Admin required', 'forbidden')
            if response is None:
                try:
                    payload = await request.json()
                except Exception:  # noqa: BLE001 — malformed JSON must not become a no-op success
                    payload = None
                if not isinstance(payload, dict):
                    response = _api_error('Invalid JSON payload', 'bad_request')
                else:
                    order = payload.get('order') if isinstance(payload.get('order'), list) else []
                    try:
                        data.reorder(order)
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({'status': 'success'}))
                    except Exception:  # noqa: BLE001 — preserve the legacy safe failure
                        data.rollback()
                        flask_app.logger.warning('library reorder failed')
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Could not update the library', code='internal',
                            body_status='error',
                        )
                        response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/admin/libraries/batch/edit')
    async def batch_edit_libraries(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = None
            if auth.token is None:
                from .csrf_compat import csrf_error_response

                response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            if response is None:
                from oneirodex.utils.role_catalog import normalize_role

                if (
                    normalize_role(getattr(auth.user, 'role', None)) != 'admin'
                    or (auth.token is not None and not auth.has_scope('admin'))
                ):
                    response = _api_error('Admin required', 'forbidden')
            if response is None:
                body, status = data.batch_edit(await _json_object(request), auth.user)
                response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


def mount_library_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_library_reads_router(flask_app, **kwargs))
    return app


def _batch_rejection(payload, http_status):
    """Wrap the shared library-batch refusal in the API error envelope."""
    from oneirodex.utils.api_contract import api_error_payload

    message = payload.get('message') or payload.get('error') or 'Rejected'
    token = payload.get('error')
    extras = {
        key: value for key, value in payload.items()
        if key not in ('ok', 'error', 'message', 'status', 'success', 'error_code')
    }
    if token and token != message:
        extras['body_error'] = token
    code = {
        400: 'bad_request',
        403: 'forbidden',
        404: 'not_found',
        409: 'conflict',
        500: 'internal',
    }.get(http_status, 'bad_request')
    return api_error_payload(
        message,
        code=code,
        status=http_status,
        body_status=payload.get('status', 'rejected'),
        **extras,
    )


async def _json_object(request):
    try:
        value = await request.json()
    except Exception:  # noqa: BLE001 — match Flask's silent JSON parsing
        return {}
    return value if isinstance(value, dict) else {}


def _api_error(message, code):
    from oneirodex.utils.api_contract import api_error_payload

    payload, status = api_error_payload(message, code=code)
    return JSONResponse(payload, status_code=status)


def parse_watch_value(raw):
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ('', 'null', 'none', 'default', 'follow', 'global'):
        return None
    if text in ('1', 'true', 'yes', 'on', 'enabled'):
        return True
    if text in ('0', 'false', 'no', 'off', 'disabled'):
        return False
    raise ValueError(f'Invalid watch_enabled: {raw!r}')
