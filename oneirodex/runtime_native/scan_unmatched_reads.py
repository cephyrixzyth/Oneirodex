"""Native read-only API for unmatched-folder administration."""
from __future__ import annotations

import csv
import io
from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .request_auth import request_auth_context


VALID_UNMATCHED_EXPORT_STATUSES = {'all', 'Unmatched', 'Duplicate', 'Ignore', 'Pending'}
MATCH_REASON_CODES = {
    'same_path', 'title_vs_folder', 'title_vs_library_name', 'title_below_threshold',
    'cross_system', 'region_mismatch',
}
DEFAULT_LIMIT = 150
MAX_LIMIT = 500
CSV_FIELDS = [
    'id', 'folder_path', 'folder_name', 'search_name', 'display_name',
    'status', 'library_uuid', 'library_name', 'platform_name',
    'matched_game_uuid', 'match_reason', 'match_score',
    'matched_game_name', 'matched_game_path', 'matched_game_cover_url', 'matched_game_igdb_id',
    'matched_game_size_bytes', 'matched_game_date_identified', 'matched_game_date_created',
    'size_bytes', 'folder_size_bytes', 'folder_mtime', 'mtime', 'modified_at', 'failed_time',
    'rom_region', 'rom_languages', 'suggested_kind', 'suggested_kind_label',
    'suggested_candidate_name', 'why_unmatched', 'unmatched_reason',
]


class ScanUnmatchedReadsData:
    """Database and row-projection adapter. Tests replace all methods with fakes."""

    def query_unmatched(self, filters, *, paginate=None):
        from sqlalchemy import or_, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library, UnmatchedFolder

        query = (
            select(UnmatchedFolder, Library.name.label('library_name'), Library.platform)
            .join(Library)
            .order_by(UnmatchedFolder.status.desc(), UnmatchedFolder.folder_path.asc())
        )
        query = self._apply_filters(query, filters)
        use_page = filters.get('paginate', True) if paginate is None else paginate
        if use_page:
            query = query.limit(filters.get('limit') or DEFAULT_LIMIT).offset(filters.get('offset') or 0)
        return db.session.execute(query).all()

    def count_unmatched(self, filters):
        from sqlalchemy import func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Library, UnmatchedFolder

        query = select(func.count(UnmatchedFolder.id)).select_from(UnmatchedFolder).join(Library)
        query = self._apply_filters(query, filters)
        return int(db.session.execute(query).scalar() or 0)

    @staticmethod
    def _apply_filters(query, filters):
        from sqlalchemy import or_
        from oneirodex.models import Library, UnmatchedFolder

        status = filters.get('status') or 'all'
        if status != 'all':
            query = query.filter(UnmatchedFolder.status == status)
        library_uuid = filters.get('library_uuid') or ''
        if library_uuid:
            query = query.filter(UnmatchedFolder.library_uuid == library_uuid)
        platform = filters.get('platform') or ''
        if platform:
            from oneirodex.platform import LibraryPlatform

            key = platform.strip()
            platform_enum = None
            try:
                platform_enum = LibraryPlatform[key]
            except KeyError:
                for member in LibraryPlatform:
                    if member.name == key or member.value == key:
                        platform_enum = member
                        break
            query = query.filter(Library.platform == platform_enum if platform_enum is not None else Library.platform == None)  # noqa: E711
        suggested_kind = filters.get('suggested_kind') or ''
        if suggested_kind:
            query = query.filter(UnmatchedFolder.suggested_kind == suggested_kind)
        q = filters.get('q') or ''
        if q:
            pattern = f'%{q}%'
            query = query.filter(or_(
                UnmatchedFolder.folder_path.ilike(pattern),
                UnmatchedFolder.search_name.ilike(pattern),
                UnmatchedFolder.display_name.ilike(pattern),
                Library.name.ilike(pattern),
            ))
        why = filters.get('why') or ''
        if why:
            folded = why.strip()
            lower = folded.lower()
            statuses = {s.lower(): s for s in ('Unmatched', 'Duplicate', 'Ignore', 'Pending')}
            if lower in statuses:
                query = query.filter(UnmatchedFolder.status == statuses[lower])
            elif lower in MATCH_REASON_CODES:
                query = query.filter(UnmatchedFolder.match_reason == lower)
            elif lower in ('title', 'titles'):
                query = query.filter(UnmatchedFolder.match_reason.ilike('title%'))
            else:
                query = query.filter(UnmatchedFolder.match_reason.ilike(f'%{folded}%'))
        return query

    def prefetch_matched_game_maps(self, folders):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, Image

        uuids = list({getattr(row, 'matched_game_uuid', None) for row in folders
                      if getattr(row, 'matched_game_uuid', None)})
        games, covers = {}, {}
        if uuids:
            for game in db.session.execute(select(Game).filter(Game.uuid.in_(uuids))).scalars().all():
                games[game.uuid] = game
            for image in db.session.execute(
                select(Image).filter(Image.game_uuid.in_(uuids), Image.image_type == 'cover')
            ).scalars().all():
                covers.setdefault(image.game_uuid, image)
        return games, covers

    def list_payloads(self, flask_app, rows, include_transforms):
        # Reuse the established row projection so the admin SPA keeps all of
        # its region, transform, cover, and suggested-kind fields unchanged.
        # Load this helper file directly: importing the routes_apis package
        # would register every legacy Flask API module as a side effect.
        project_row = _row_projection_module()._unmatched_list_row

        folders = [folder for folder, _name, _platform in rows]
        games, covers = self.prefetch_matched_game_maps(folders)
        return [
            project_row(
                folder, library_name, platform, games_by_uuid=games,
                cover_by_uuid=covers, include_transforms=include_transforms,
                app=flask_app,
            )
            for folder, library_name, platform in rows
        ]

    def duplicate_payloads(self, flask_app):
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, UnmatchedFolder
        from oneirodex.utils.duplicate_check import normalize_rom_region, same_duplicate_scope
        row_module = _row_projection_module()

        rows = db.session.execute(
            select(UnmatchedFolder).options(joinedload(UnmatchedFolder.library))
            .filter_by(status='Duplicate').order_by(UnmatchedFolder.failed_time.desc())
        ).scalars().unique().all()
        uuids = [row.matched_game_uuid for row in rows if getattr(row, 'matched_game_uuid', None)]
        games = {}
        if uuids:
            for game in db.session.execute(
                select(Game).options(joinedload(Game.library)).filter(Game.uuid.in_(uuids))
            ).scalars().unique().all():
                games[game.uuid] = game
        payload = []
        for folder in rows:
            matched = games.get(getattr(folder, 'matched_game_uuid', None))
            if matched is not None:
                region = normalize_rom_region(
                    row_module._rom_language_fields_from_path(folder.folder_path).get('rom_region')
                )
                if not same_duplicate_scope(
                    matched,
                    new_platform=getattr(getattr(folder, 'library', None), 'platform', None),
                    new_library_uuid=folder.library_uuid,
                    new_rom_region=region,
                ):
                    matched = None
            payload.append(row_module._duplicate_compare_payload(folder, matched, app=flask_app))
        return payload

    def fix_log_payloads(self, limit):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import DuplicateFixLog

        rows = db.session.execute(
            select(DuplicateFixLog).order_by(DuplicateFixLog.created_at.desc()).limit(limit)
        ).scalars().all()
        return [{
            'id': row.id,
            'unmatched_folder_id': row.unmatched_folder_id,
            'folder_path': row.folder_path,
            'matched_game_uuid': row.matched_game_uuid,
            'match_reason': row.match_reason,
            'match_score': row.match_score,
            'action': row.action,
            'actor_user_id': row.actor_user_id,
            'notes': row.notes,
            'created_at': row.created_at.isoformat() if row.created_at else None,
        } for row in rows]


def create_scan_unmatched_reads_router(
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
    data = data_access if data_access is not None else ScanUnmatchedReadsData()
    options = dict(
        flask_app=flask_app, data=data, find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager, database_scope=database_scope,
    )

    @router.api_route('/api/unmatched_folders', methods=['GET', 'HEAD'])
    async def unmatched_folders(request: Request):
        return await _run(request, **options, handler=_list_rows)

    @router.api_route('/api/unmatched_folders/duplicates', methods=['GET', 'HEAD'])
    async def duplicate_candidates(request: Request):
        return await _run(request, **options, handler=_duplicates)

    @router.api_route('/api/unmatched_folders/fix_logs', methods=['GET', 'HEAD'])
    async def duplicate_fix_logs(request: Request):
        return await _run(request, **options, handler=_fix_logs)

    @router.api_route('/api/unmatched_folders/export', methods=['GET', 'HEAD'])
    async def export_unmatched(request: Request):
        return await _run(request, **options, handler=_export)

    return router


def mount_scan_unmatched_read_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_scan_unmatched_reads_router(flask_app, **kwargs))
    return app


def _row_projection_module():
    """Load shared row projections without importing the legacy route package."""
    from oneirodex.utils import scan_unmatched_rows

    return scan_unmatched_rows


async def _run(
    request, *, flask_app, data, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, database_scope, handler,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        if auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        else:
            role = _normalized_role(auth.user)
            if role == 'admin' and auth.token is not None and not auth.has_scope('admin'):
                response = _error(403, 'forbidden', 'This token does not have the admin scope')
            elif role != 'admin':
                response = _admin_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            else:
                try:
                    response = await handler(request, flask_app, data)
                except Exception:
                    response = _error(500, 'internal', 'An error occurred while processing your request')
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        _finish(response, flask_app, request)
        return response


async def _list_rows(request, flask_app, data):
    filters, error = _parse_filters(request)
    if error:
        return error
    from oneirodex.utils.duplicate_check import normalize_rom_region

    region = normalize_rom_region(filters.get('rom_region') or '')
    paginate = bool(filters.get('paginate'))
    limit, offset = filters['limit'], filters['offset']
    query_filters = dict(filters)
    if region and paginate:
        query_filters['paginate'] = False
    rows = data.query_unmatched(query_filters)
    result = data.list_payloads(flask_app, rows, filters['include_transforms'])
    if region:
        result = [row for row in result if normalize_rom_region(row.get('rom_region')) == region]
    if paginate:
        if region:
            total = len(result)
            result = result[offset:offset + limit]
        else:
            total = data.count_unmatched(filters)
        return JSONResponse({
            'items': result, 'total': total, 'limit': limit,
            'offset': offset, 'count': len(result),
        })
    return JSONResponse(result)


async def _duplicates(_request, flask_app, data):
    payload = data.duplicate_payloads(flask_app)
    return JSONResponse({'duplicates': payload, 'count': len(payload)})


async def _fix_logs(request, _flask_app, data):
    raw = _query_first(request, 'limit')
    try:
        limit = int(raw) if raw is not None else 100
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit or 100, 500))
    logs = data.fix_log_payloads(limit)
    return JSONResponse({'logs': logs, 'count': len(logs)})


async def _export(request, flask_app, data):
    filters, error = _parse_filters(request)
    if error:
        return error
    fmt = (_query_first(request, 'format', 'csv') or 'csv').lower()
    if fmt not in ('csv', 'json'):
        return _error(400, 'bad_request', "Invalid format. Choose 'csv' or 'json'.")
    filters['paginate'] = False
    rows = data.query_unmatched(filters, paginate=False)
    export_rows = data.list_payloads(flask_app, rows, True)
    from oneirodex.utils.duplicate_check import normalize_rom_region

    region = normalize_rom_region(filters.get('rom_region') or '')
    if region:
        export_rows = [row for row in export_rows if normalize_rom_region(row.get('rom_region')) == region]
    status = filters['status']
    filename_status = status if status != 'all' else 'all'
    if fmt == 'json':
        return JSONResponse(
            export_rows,
            headers={'Content-Disposition': f'attachment; filename="unmatched_folders_{filename_status}.json"'},
        )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, extrasaction='ignore')
    writer.writeheader()
    for row in export_rows:
        flat = dict(row)
        matched = flat.pop('matched_game', None) or {}
        flat['matched_game_name'] = matched.get('name')
        flat['matched_game_path'] = matched.get('path')
        flat['matched_game_cover_url'] = matched.get('cover_url')
        flat['matched_game_igdb_id'] = matched.get('igdb_id')
        flat['matched_game_size_bytes'] = matched.get('size_bytes')
        flat['matched_game_date_identified'] = matched.get('date_identified')
        flat['matched_game_date_created'] = matched.get('date_created')
        writer.writerow(flat)
    return Response(
        buffer.getvalue(), media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="unmatched_folders_{filename_status}.csv"'},
    )


def _parse_filters(request):
    status = (_query_first(request, 'status') or 'all').strip()
    if status not in VALID_UNMATCHED_EXPORT_STATUSES:
        statuses = sorted(VALID_UNMATCHED_EXPORT_STATUSES)
        return None, _error(400, 'bad_request', f'Invalid status. Choose one of: {statuses}')
    try:
        limit = int(_query_first(request, 'limit') or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(_query_first(request, 'offset') or 0)
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    include_raw = (_query_first(request, 'include') or '').strip().lower()
    transforms_raw = (_query_first(request, 'transforms') or '').strip().lower()
    include_transforms = True
    if include_raw in {'none', 'minimal', 'columns'} or transforms_raw in {'0', 'false', 'no'}:
        include_transforms = False
    if include_raw in {'transforms', '1', 'true', 'yes', 'full'} or transforms_raw in {'1', 'true', 'yes'}:
        include_transforms = True
    return {
        'status': status,
        'q': (_query_first(request, 'q') or _query_first(request, 'name') or '').strip(),
        'why': (_query_first(request, 'why') or _query_first(request, 'reason') or '').strip(),
        'suggested_kind': (_query_first(request, 'suggested_kind') or '').strip().lower(),
        'library_uuid': (_query_first(request, 'library_uuid') or '').strip(),
        'platform': (_query_first(request, 'platform') or _query_first(request, 'system') or '').strip(),
        'rom_region': (_query_first(request, 'rom_region') or _query_first(request, 'region') or '').strip(),
        'limit': limit, 'offset': offset, 'include_transforms': include_transforms,
        'paginate': (_query_first(request, 'paginate') or '0').strip().lower() in {'1', 'true', 'yes'},
    }, None


def _query_first(request, key, default=None):
    values = request.query_params.getlist(key)
    return values[0] if values else default


def _normalized_role(user):
    from oneirodex.utils.role_catalog import normalize_role

    return normalize_role(getattr(user, 'role', None) or '')


def _login_redirect(flask_app, request, login_manager, auth):
    from .oidc_status import _login_redirect as login_redirect

    return login_redirect(
        flask_app, request, login_manager, auth,
        message=getattr(login_manager, 'login_message', None),
        category=getattr(login_manager, 'login_message_category', 'message'),
        include_next=True,
    )


def _admin_redirect(flask_app, request, login_manager, auth, *, message, category, include_next):
    from .oidc_status import _login_redirect as login_redirect

    return login_redirect(
        flask_app, request, login_manager, auth,
        message=message, category=category, include_next=include_next,
    )


def _error(status, code, message, **fields):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, **fields)
    return JSONResponse(payload, status_code=resolved)


def _finish(response, flask_app, request):
    from oneirodex.utils.security_headers import security_header_values

    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    if request.method == 'HEAD':
        response.body = b''
