"""Unmatched-folder read surface: list, duplicates, export, fix logs,
reclassify/backfill maintenance, bad-match feedback.

Split out of ``routes_apis/scan.py`` in the v11 cycle (H-D.4) as a pure move.
The list filters and the query builder live here because list + export share
them; single-row and batch edits are in ``scan_unmatched_edit``.
"""
# /oneirodex/routes_apis/scan.py
import csv
import io

from oneirodex.utils.api_response import api_error, api_ok
from flask import jsonify, request, Response
from flask_login import login_required, current_user
from oneirodex import db
from oneirodex.models import UnmatchedFolder, Library, Game, DuplicateFixLog
from sqlalchemy import String, cast, exists, or_, select
from oneirodex.utils.auth import admin_required, librarian_required
from oneirodex.utils.duplicate_check import (
    normalize_rom_region,
    same_duplicate_scope,
    should_mark_as_duplicate,
)
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.scan_match_settings import resolve_scan_match_policy
from oneirodex.utils.scan_unmatched_rows import _duplicate_compare_payload, _prefetch_matched_game_maps, _rom_language_fields_from_path, _unmatched_list_row
from . import apis_bp


VALID_UNMATCHED_EXPORT_STATUSES = {'all', 'Unmatched', 'Duplicate', 'Ignore', 'Pending'}
VALID_DUPLICATE_FIX_ACTIONS = {'merge', 'keep', 'ignore'}
UNMATCHED_BATCH_ID_CAP = 100
_MATCH_REASON_CODES = {
    'same_path',
    'title_vs_folder',
    'title_vs_library_name',
    'title_below_threshold',
    'cross_system',
    'region_mismatch',
}

UNMATCHED_LIST_DEFAULT_LIMIT = 150
UNMATCHED_LIST_MAX_LIMIT = 500


def _parse_unmatched_list_filters():
    """Query params shared by list + export. Returns (filters_dict, error_response)."""
    status = (request.args.get('status') or 'all').strip()
    if status not in VALID_UNMATCHED_EXPORT_STATUSES:
        return None, api_error(
            f"Invalid status. Choose one of: {sorted(VALID_UNMATCHED_EXPORT_STATUSES)}",
            code='bad_request',
        )
    try:
        limit = int(request.args.get('limit') or UNMATCHED_LIST_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = UNMATCHED_LIST_DEFAULT_LIMIT
    try:
        offset = int(request.args.get('offset') or 0)
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(limit, UNMATCHED_LIST_MAX_LIMIT))
    offset = max(0, offset)
    # The peel trail is on by default: it is what the Unmatched row's "Name
    # transform trail" expander renders, and the only caller never asked for it
    # opt-in, so making it opt-in silently emptied that expander for every row.
    # The list is paginated now (150 rows, 500 ceiling), so the CPU that made it
    # worth skipping across an unbounded list is bounded. `include=none` (or
    # `transforms=0`) is the opt-out for a caller that only wants the columns.
    include_raw = (request.args.get('include') or '').strip().lower()
    transforms_raw = (request.args.get('transforms') or '').strip().lower()
    include_transforms = True
    if include_raw in {'none', 'minimal', 'columns'} or transforms_raw in {'0', 'false', 'no'}:
        include_transforms = False
    if include_raw in {'transforms', '1', 'true', 'yes', 'full'} or transforms_raw in {
        '1', 'true', 'yes',
    }:
        include_transforms = True
    return {
        'status': status,
        'q': (request.args.get('q') or request.args.get('name') or '').strip(),
        'why': (request.args.get('why') or request.args.get('reason') or '').strip(),
        'suggested_kind': (request.args.get('suggested_kind') or '').strip().lower(),
        'library_uuid': (request.args.get('library_uuid') or '').strip(),
        'platform': (request.args.get('platform') or request.args.get('system') or '').strip(),
        'rom_region': (request.args.get('rom_region') or request.args.get('region') or '').strip(),
        'limit': limit,
        'offset': offset,
        'include_transforms': include_transforms,
        'paginate': (request.args.get('paginate') or '0').strip().lower() in {'1', 'true', 'yes'},
    }, None


def _apply_unmatched_filters(query, filters: dict):
    status = filters.get('status') or 'all'
    if status != 'all':
        query = query.filter(UnmatchedFolder.status == status)

    library_uuid = filters.get('library_uuid') or ''
    if library_uuid:
        query = query.filter(UnmatchedFolder.library_uuid == library_uuid)

    platform = filters.get('platform') or ''
    if platform:
        from oneirodex.platform import LibraryPlatform

        platform_enum = None
        key = platform.strip()
        try:
            platform_enum = LibraryPlatform[key]
        except KeyError:
            for member in LibraryPlatform:
                if member.name == key or member.value == key:
                    platform_enum = member
                    break
        if platform_enum is not None:
            query = query.filter(Library.platform == platform_enum)
        else:
            # Unknown platform token → empty result rather than ignoring the filter.
            query = query.filter(Library.platform == None)  # noqa: E711

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
            cast(Library.platform, String).ilike(pattern),
            cast(UnmatchedFolder.status, String).ilike(pattern),
            UnmatchedFolder.suggested_kind.ilike(pattern),
            UnmatchedFolder.match_reason.ilike(pattern),
            UnmatchedFolder.suggested_candidate_name.ilike(pattern),
            exists(select(1).where(
                Game.uuid == UnmatchedFolder.matched_game_uuid,
                or_(Game.name.ilike(pattern), Game.full_disk_path.ilike(pattern)),
            )),
        ))

    why = filters.get('why') or ''
    if why:
        why_folded = why.strip()
        why_lower = why_folded.lower()
        status_aliases = {s.lower(): s for s in ('Unmatched', 'Duplicate', 'Ignore', 'Pending')}
        if why_lower in status_aliases:
            query = query.filter(UnmatchedFolder.status == status_aliases[why_lower])
        elif why_lower in _MATCH_REASON_CODES:
            query = query.filter(UnmatchedFolder.match_reason == why_lower)
        elif why_lower in ('title', 'titles'):
            query = query.filter(UnmatchedFolder.match_reason.ilike('title%'))
        else:
            query = query.filter(UnmatchedFolder.match_reason.ilike(f'%{why_folded}%'))

    return query


def _query_unmatched_rows(filters: dict, *, paginate: bool | None = None):
    query = (
        select(UnmatchedFolder, Library.name.label('library_name'), Library.platform)
        .join(Library)
        .order_by(UnmatchedFolder.status.desc(), UnmatchedFolder.folder_path.asc())
    )
    query = _apply_unmatched_filters(query, filters)
    use_page = filters.get('paginate', True) if paginate is None else paginate
    if use_page:
        limit = filters.get('limit') or UNMATCHED_LIST_DEFAULT_LIMIT
        offset = filters.get('offset') or 0
        query = query.limit(limit).offset(offset)
    return db.session.execute(query).all()


def _count_unmatched_rows(filters: dict) -> int:
    from sqlalchemy import func

    query = (
        select(func.count(UnmatchedFolder.id))
        .select_from(UnmatchedFolder)
        .join(Library)
    )
    query = _apply_unmatched_filters(query, filters)
    return int(db.session.execute(query).scalar() or 0)


@apis_bp.route('/unmatched_folders', methods=['GET'])
@login_required
@admin_required
def unmatched_folders():
    filters, err = _parse_unmatched_list_filters()
    if err:
        return err

    # rom_region is path-derived (not a column), so it must be applied after
    # row peel. When both region + paginate are set, fetch the full filtered
    # set first, then slice — SQL limit/offset before peel under-fills pages
    # and lies about total.
    region_filter = normalize_rom_region(filters.get('rom_region') or '')
    paginate = bool(filters.get('paginate'))
    limit = filters.get('limit') or UNMATCHED_LIST_DEFAULT_LIMIT
    offset = filters.get('offset') or 0

    query_filters = dict(filters)
    if region_filter and paginate:
        query_filters['paginate'] = False

    rows = _query_unmatched_rows(query_filters)
    folders = [folder for folder, _library_name, _platform in rows]
    games_by_uuid, cover_by_uuid = _prefetch_matched_game_maps(folders)
    include_transforms = bool(filters.get('include_transforms'))

    unmatched_data = [
        _unmatched_list_row(
            folder,
            library_name,
            platform,
            games_by_uuid=games_by_uuid,
            cover_by_uuid=cover_by_uuid,
            include_transforms=include_transforms,
        )
        for folder, library_name, platform in rows
    ]

    if region_filter:
        unmatched_data = [
            row for row in unmatched_data
            if normalize_rom_region(row.get('rom_region')) == region_filter
        ]

    if paginate:
        if region_filter:
            total = len(unmatched_data)
            unmatched_data = unmatched_data[offset:offset + limit]
        else:
            total = _count_unmatched_rows(filters)
        return jsonify({
            'items': unmatched_data,
            'total': total,
            'limit': limit,
            'offset': offset,
            'count': len(unmatched_data),
        })

    return jsonify(unmatched_data)


@apis_bp.route('/unmatched_folders/duplicates', methods=['GET'])
@login_required
@admin_required
def list_duplicate_candidates():
    """List Duplicate unmatched rows with compare fields for admin UI glance."""
    from sqlalchemy.orm import joinedload

    rows = db.session.execute(
        select(UnmatchedFolder)
        .options(joinedload(UnmatchedFolder.library))
        .filter_by(status='Duplicate')
        .order_by(UnmatchedFolder.failed_time.desc())
    ).scalars().unique().all()

    games_by_uuid = {}
    uuids = [r.matched_game_uuid for r in rows if getattr(r, 'matched_game_uuid', None)]
    if uuids:
        for game in db.session.execute(
            select(Game).options(joinedload(Game.library)).filter(Game.uuid.in_(uuids))
        ).scalars().unique().all():
            games_by_uuid[game.uuid] = game

    payload = []
    for folder in rows:
        matched = games_by_uuid.get(getattr(folder, 'matched_game_uuid', None))
        # Never scan the whole Game table — that made this endpoint unusable on
        # large libraries. Rows without matched_game_uuid stay without candidates.
        if matched is not None:
            folder_region = normalize_rom_region(
                _rom_language_fields_from_path(folder.folder_path).get('rom_region')
            )
            if not same_duplicate_scope(
                matched,
                new_platform=getattr(getattr(folder, 'library', None), 'platform', None),
                new_library_uuid=folder.library_uuid,
                new_rom_region=folder_region,
            ):
                # Stale cross-system Duplicate — still return the row but without
                # pretending it is a same-system hit.
                matched = None
        payload.append(_duplicate_compare_payload(folder, matched))
    return jsonify({'duplicates': payload, 'count': len(payload)})


@apis_bp.route('/unmatched_folders/fix_logs', methods=['GET'])
@login_required
@admin_required
def list_duplicate_fix_logs():
    """Queryable how-matched / how-fixed history for admin/dev feedback."""
    limit = request.args.get('limit', 100, type=int) or 100
    limit = max(1, min(limit, 500))
    rows = db.session.execute(
        select(DuplicateFixLog).order_by(DuplicateFixLog.created_at.desc()).limit(limit)
    ).scalars().all()
    return jsonify({
        'logs': [
            {
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
            }
            for row in rows
        ],
        'count': len(rows),
    })


@apis_bp.route('/unmatched_folders/export', methods=['GET'])
@login_required
@admin_required
def export_unmatched_folders():
    """Export unmatched/duplicate/ignored folders as CSV or JSON for offline triage."""
    filters, err = _parse_unmatched_list_filters()
    if err:
        return err

    fmt = (request.args.get('format', 'csv') or 'csv').lower()
    if fmt not in ('csv', 'json'):
        return api_error("Invalid format. Choose 'csv' or 'json'.", code='bad_request')

    filters['paginate'] = False
    rows = _query_unmatched_rows(filters, paginate=False)
    folders = [folder for folder, _ln, _pl in rows]
    games_by_uuid, cover_by_uuid = _prefetch_matched_game_maps(folders)

    export_rows = [
        _unmatched_list_row(
            folder,
            library_name,
            platform,
            games_by_uuid=games_by_uuid,
            cover_by_uuid=cover_by_uuid,
            include_transforms=True,
        )
        for folder, library_name, platform in rows
    ]

    # Same rom_region peel filter as the list endpoint (path-derived).
    region_filter = normalize_rom_region(filters.get('rom_region') or '')
    if region_filter:
        export_rows = [
            row for row in export_rows
            if normalize_rom_region(row.get('rom_region')) == region_filter
        ]

    status = filters['status']
    filename_status = status if status != 'all' else 'all'

    if fmt == 'json':
        response = jsonify(export_rows)
        response.headers['Content-Disposition'] = (
            f'attachment; filename="unmatched_folders_{filename_status}.json"'
        )
        return response

    buffer = io.StringIO()
    fieldnames = [
        'id', 'folder_path', 'folder_name', 'search_name', 'display_name',
        'status', 'library_uuid', 'library_name', 'platform_name',
        'matched_game_uuid', 'match_reason', 'match_score',
        'matched_game_name', 'matched_game_path', 'matched_game_cover_url', 'matched_game_igdb_id',
        'matched_game_size_bytes', 'matched_game_date_identified', 'matched_game_date_created',
        'size_bytes', 'folder_size_bytes', 'folder_mtime', 'mtime', 'modified_at', 'failed_time',
        'rom_region', 'rom_languages',
        'suggested_kind', 'suggested_kind_label', 'suggested_candidate_name',
        'why_unmatched', 'unmatched_reason',
    ]
    flat_rows = []
    for row in export_rows:
        flat = dict(row)
        mg = flat.pop('matched_game', None) or {}
        flat['matched_game_name'] = mg.get('name')
        flat['matched_game_path'] = mg.get('path')
        flat['matched_game_cover_url'] = mg.get('cover_url')
        flat['matched_game_igdb_id'] = mg.get('igdb_id')
        flat['matched_game_size_bytes'] = mg.get('size_bytes')
        flat['matched_game_date_identified'] = mg.get('date_identified')
        flat['matched_game_date_created'] = mg.get('date_created')
        flat_rows.append(flat)

    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(flat_rows)

    return Response(
        buffer.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="unmatched_folders_{filename_status}.csv"'
        },
    )


@apis_bp.route('/unmatched_folders/reclassify_duplicates', methods=['POST'])
@login_required
@admin_required
def reclassify_duplicate_unmatched():
    """Downgrade false 'Duplicate' rows to Unmatched.

    False means: folder titles differ, OR the matched hit is a different
    system/region (cross-system copies are not duplicates).
    """
    from sqlalchemy.orm import joinedload

    rows = db.session.execute(
        select(UnmatchedFolder)
        .options(joinedload(UnmatchedFolder.library))
        .filter_by(status='Duplicate')
    ).scalars().unique().all()
    changed = []
    kept = []
    uuids = [r.matched_game_uuid for r in rows if getattr(r, 'matched_game_uuid', None)]
    games_by_uuid = {}
    if uuids:
        for game in db.session.execute(
            select(Game).options(joinedload(Game.library)).filter(Game.uuid.in_(uuids))
        ).scalars().unique().all():
            games_by_uuid[game.uuid] = game
    dupe_thr = resolve_scan_match_policy().get('dupe_title_threshold')
    for folder in rows:
        matched = games_by_uuid.get(getattr(folder, 'matched_game_uuid', None))
        folder_region = normalize_rom_region(
            _rom_language_fields_from_path(folder.folder_path).get('rom_region')
        )
        scope_kwargs = {
            'new_platform': getattr(getattr(folder, 'library', None), 'platform', None),
            'new_library_uuid': folder.library_uuid,
            'new_rom_region': folder_region,
        }
        is_true = False
        if matched is not None and should_mark_as_duplicate(
            matched,
            folder.folder_path,
            title_threshold=dupe_thr,
            **scope_kwargs,
        ):
            is_true = True
        if is_true:
            kept.append(folder.folder_path)
            continue
        folder.status = 'Unmatched'
        if matched is None or not same_duplicate_scope(matched, **scope_kwargs):
            folder.match_reason = 'cross_system'
            folder.matched_game_uuid = None
            folder.match_score = None
        changed.append(folder.folder_path)
    db.session.commit()
    return jsonify({
        'reclassified_to_unmatched': changed,
        'kept_as_duplicate': kept,
        'changed_count': len(changed),
        'kept_count': len(kept),
    })


@apis_bp.route('/unmatched_folders/backfill_suggested_kind', methods=['POST'])
@login_required
@admin_required
def backfill_unmatched_suggested_kind_route():
    """One-shot: denormalize suggested_kind from on-disk proposal sidecars.

    Body (optional JSON):
      dry_run (bool) — count would-update without writing
      limit (int) — max null-hint rows to consider

    Idempotent; only reads sidecars for rows with null suggested_kind.
    """
    from oneirodex.utils.match_proposal import backfill_unmatched_suggested_kind

    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get('dry_run', False))
    limit = data.get('limit')
    result = backfill_unmatched_suggested_kind(limit=limit, dry_run=dry_run)
    if result.get('ok', True):
        return api_ok({**result, 'status': 'ok'})
    return api_error(
        'Could not backfill suggested kinds',
        code='internal',
        status=500,
        body_status='error',
        body_error=result.get('error') or 'commit_failed',
        scanned=result.get('scanned'),
        updated=result.get('updated'),
        skipped_no_sidecar=result.get('skipped_no_sidecar'),
        skipped_empty_hint=result.get('skipped_empty_hint'),
        dry_run=result.get('dry_run'),
        committed=result.get('committed'),
    )


# UX-C5 — why an operator says a proposed match is wrong. A controlled list
# keeps the feedback aggregatable; 'other' carries a free-text note so the
# vocabulary can grow from real usage instead of guesswork.
BAD_MATCH_REASONS = {
    'wrong_game': 'Wrong game entirely',
    'wrong_edition': 'Right game, wrong edition/version',
    'wrong_platform': 'Right game, wrong platform',
    'wrong_region': 'Right game, wrong region',
    'is_dlc_or_update': 'This is DLC / an update, not the base game',
    'is_not_a_game': 'Not a game (tool, emulator, extras)',
    'duplicate_of_other': 'Duplicate of another entry',
    'other': 'Other',
}


@apis_bp.route('/unmatched/bad_match_reasons', methods=['GET'])
@login_required
@librarian_required
def unmatched_bad_match_reasons():
    """Vocabulary for the Bad match picker, so the UI never hardcodes it."""
    return api_ok({
        'reasons': [{'id': key, 'label': label} for key, label in BAD_MATCH_REASONS.items()],
    })


@apis_bp.route('/unmatched/<folder_id>/bad_match', methods=['POST'])
@login_required
@librarian_required
def unmatched_flag_bad_match(folder_id: str):
    """Record that a proposed match is wrong, with a reason.

    Deliberately does **not** delete the row or touch the library: this is
    feedback about the match, not a destructive triage action. Post with
    ``{"reason": null}`` to clear a flag set by mistake.
    """
    row = db.session.get(UnmatchedFolder, folder_id)
    if row is None:
        return api_error('Folder not found', code='not_found')

    data = request.get_json(silent=True) or {}
    raw_reason = data.get('reason')

    if raw_reason in (None, '', False):
        row.bad_match_reason = None
        row.bad_match_note = None
        row.bad_match_at = None
        row.bad_match_by_user_id = None
        db.session.commit()
        return api_ok({'cleared': True})

    reason = str(raw_reason).strip().lower()
    if reason not in BAD_MATCH_REASONS:
        return api_error(
            f"reason must be one of: {', '.join(sorted(BAD_MATCH_REASONS))}",
            code='bad_request',
        )

    note = (data.get('note') or '').strip()[:500]
    # 'other' without a note is not feedback, it is a shrug.
    if reason == 'other' and not note:
        return api_error('A note is required when the reason is "other"', code='bad_request')

    from datetime import datetime, timezone

    row.bad_match_reason = reason
    row.bad_match_note = note or None
    row.bad_match_at = datetime.now(timezone.utc)
    row.bad_match_by_user_id = getattr(current_user, 'id', None)
    db.session.commit()

    log_system_event(
        f'Bad match flagged on {row.folder_path}: {reason}',
        event_type='admin_action',
        event_level='information',
        audit_user=getattr(current_user, 'id', None),
    )

    return api_ok({
        'folder_id': folder_id,
        'reason': reason,
        'label': BAD_MATCH_REASONS[reason],
        'note': row.bad_match_note,
    })
