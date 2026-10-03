"""Admin library tools: rename preview/apply, match proposals, library doctor."""

from __future__ import annotations

import json
import os

from oneirodex.utils.api_response import api_error, api_ok
from flask import jsonify, request, current_app
from flask_login import login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, Library
from oneirodex.schemas.library_tools import (
    ApplyRenamesBody,
    ApproveProposalBody,
    CheckFreshnessBody,
    DoctorDryRunBody,
    ScanRootsBody,
    WriteProposalsBody,
)
from oneirodex.utils.auth import admin_required
from oneirodex.utils.security import is_safe_path, get_allowed_base_directories
from oneirodex.utils.disk_rename import apply_rename_plan, build_rename_plan, validate_plan_for_game
from oneirodex.utils.path_repoint import _moved as path_moved, repoint_paths
from oneirodex.utils.match_proposal import (
    resolve_proposal_path,
    remove_proposal_files,
)
from oneirodex.utils.library_doctor import doctor_dry_run, doctor_write_proposals, iter_game_folders
from oneirodex.utils.propose_leaf_libraries import propose_leaf_libraries
from oneirodex.utils.import_leaf_libraries import preview_from_csv, preview_from_json
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _allowed_bases():
    return get_allowed_base_directories(current_app)


@apis_bp.route('/library_tools/propose_leaf_libraries', methods=['GET', 'POST'])
@login_required
@admin_required
def propose_leaf_libraries_api():
    """Propose candidate leaf libraries under a console/tree root (never creates).

    Body/query: ``root`` (or ``path``) — absolute path under allowed bases.
    Returns ``{status, root, candidates:[{path, suggested_name, platform,
    scan_mode, scan_depth, reason}], count}``. Does **not** insert Library rows.
    """
    data = request.get_json(silent=True) or {}
    root = (
        data.get('root')
        or data.get('path')
        or request.args.get('root')
        or request.args.get('path')
        or ''
    )
    root = str(root).strip()
    if not root:
        return api_error('root path required', code='bad_request')

    safe, err = is_safe_path(root, _allowed_bases())
    if not safe:
        return api_error(err or 'Unsafe path', code='forbidden')

    if not os.path.isdir(root):
        return api_error('root is not a directory', code='bad_request')

    candidates = propose_leaf_libraries(root)
    return api_ok({
                'root': os.path.normpath(root),
        'candidates': candidates,
        'count': len(candidates),
        'auto_create': False,
    })


@apis_bp.route('/library_tools/import_leaf_libraries/preview', methods=['POST'])
@login_required
@admin_required
def import_leaf_libraries_preview_api():
    """Preview/validate CSV or JSON leaf library definitions (never creates).

    Accepts:
      - JSON body: array of rows, or ``{candidates|items|libraries|rows: [...]}``
      - multipart ``file`` upload (``.json`` / ``.csv``, UTF-8)

    Each row: ``path``, ``suggested_name``/``name``, ``platform``, ``scan_mode``,
    ``scan_depth`` (same shape as propose-from-tree candidates).

    Returns ``{status, auto_create:false, candidates, errors, count, error_count,
    create_hint}``. Create selected rows client-side via existing
    ``POST /admin/library/add`` + ``POST /api/admin/libraries/scan`` (propose UI).
    """
    bases = _allowed_bases()
    upload = request.files.get('file')
    if upload and upload.filename:
        filename = (upload.filename or '').lower()
        raw = upload.read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            return api_error(
                'File must be UTF-8 text',
                code='bad_request',
                auto_create=False,
            )
        if filename.endswith('.csv') or (request.form.get('format') or '').lower() == 'csv':
            result = preview_from_csv(text, allowed_bases=bases)
        else:
            result = preview_from_json(text, allowed_bases=bases)
        return jsonify(result)

    data = request.get_json(silent=True)
    if data is None:
        # Allow raw CSV text under form field `csv` / `text`
        csv_text = request.form.get('csv') or request.form.get('text')
        if csv_text:
            result = preview_from_csv(csv_text, allowed_bases=bases)
            return jsonify(result)
        return api_error(
            'JSON body or file upload required',
            code='bad_request',
            auto_create=False,
        )

    result = preview_from_json(data, allowed_bases=bases)
    return jsonify(result)


@apis_bp.route('/library_tools/rename/preview', methods=['POST'])
@login_required
@admin_required
def rename_preview():
    data = request.get_json(silent=True) or {}
    game_uuid = data.get('game_uuid')
    template = data.get('template') or '{title}'
    rename_root = bool(data.get('rename_root', True))
    rename_media = bool(data.get('rename_top_level_media', False))
    move_bucket = bool(data.get('move_letter_bucket', False))
    title = data.get('title')
    year = data.get('year')

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none() if game_uuid else None
    if not game:
        return api_error('Game not found', code='not_found')

    root = game.full_disk_path
    safe, err = is_safe_path(root, _allowed_bases())
    if not safe:
        return api_error(err or 'Unsafe path', code='forbidden')

    plan = build_rename_plan(
        root,
        title=title or game.name,
        year=year,
        template=template,
        rename_root=rename_root,
        rename_top_level_media=rename_media,
        move_letter_bucket=move_bucket,
    )
    return api_ok({'plan': plan, 'game_uuid': game.uuid})


@apis_bp.route('/library_tools/rename/apply', methods=['POST'])
@login_required
@admin_required
def rename_apply():
    data = request.get_json(silent=True) or {}
    game_uuid = data.get('game_uuid')
    plan = data.get('plan') or []
    if not isinstance(plan, list) or not plan:
        return api_error('No rename operations selected', code='bad_request')

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalar_one_or_none() if game_uuid else None
    if not game:
        return api_error('Game not found', code='not_found')

    problems = validate_plan_for_game(plan, game.full_disk_path or '')
    if problems:
        return api_error(
            'That rename plan does not match this game. Preview it again and retry.',
            code='bad_request',
            problems=problems,
        )

    results = apply_rename_plan(plan, _allowed_bases())
    root_moves = [r for r in results if r.get('ok') and r.get('kind') == 'root_folder']
    if root_moves:
        for result in root_moves:
            repoint_paths(result['from_path'], result['to_path'])
            # The game being renamed is repointed even when its stored path is
            # spelled differently from the plan's (doubled slash, odd case) and
            # so escaped the prefix query above.
            moved = path_moved(game.full_disk_path, result['from_path'], result['to_path'])
            if moved is not None:
                game.full_disk_path = moved
        try:
            from oneirodex.utils.rom_language import apply_rom_language_fields

            apply_rom_language_fields(game, game.full_disk_path)
        except Exception:
            pass
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return api_error(
                f'Disk renamed but DB update failed: {exc}',
                code='internal',
                results=results,
            )

    return api_ok({'results': results, 'full_disk_path': game.full_disk_path})


@apis_bp.route('/library_tools/proposals', methods=['GET'])
@login_required
@admin_required
def list_proposals():
    """Scan library games for oneirodex.proposal.json files."""
    libraries = db.session.execute(select(Library)).scalars().all()
    found = []
    for library in libraries:
        games = db.session.execute(select(Game).filter_by(library_uuid=library.uuid)).scalars().all()
        for game in games:
            proposal_path = resolve_proposal_path(game.full_disk_path or '')
            if proposal_path:
                try:
                    with open(proposal_path, encoding='utf-8') as handle:
                        payload = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    payload = None
                found.append({
                    'game_uuid': game.uuid,
                    'game_name': game.name,
                    'path': game.full_disk_path,
                    'proposal': (payload or {}).get('proposal'),
                    'library_uuid': library.uuid,
                    'library_name': library.name,
                })
    return api_ok({'proposals': found})


@apis_bp.route('/library_tools/proposals/approve', methods=['POST'])
@login_required
@admin_required
@validate_body(ApproveProposalBody)
def approve_proposal(body: ApproveProposalBody):
    """
    Approve a proposal by IGDB ID for an on-disk folder path.
    Clears the proposal sidecar and returns identify hint for import.
    """
    path = body.path
    igdb_id = body.igdb_id
    if not igdb_id:
        return api_error('path and igdb_id required', code='bad_request')
    safe, err = is_safe_path(path, _allowed_bases())
    if not safe:
        return api_error(err or 'Unsafe path', code='forbidden')
    try:
        remove_proposal_files(path)
    except OSError as exc:
        return api_error(str(exc), code='internal')
    return api_ok({
                'message': 'Proposal cleared. Complete import via Add Game / Identify with this IGDB ID.',
        'path': path,
        'igdb_id': igdb_id,
        'identify_hint': f"/add_game_manual?full_disk_path={path}&igdb_id={igdb_id}",
    })


@apis_bp.route('/library_tools/proposals/scan_roots', methods=['POST'])
@login_required
@admin_required
@validate_body(ScanRootsBody)
def scan_roots_for_proposals(body: ScanRootsBody):
    roots = body.roots

    found = []
    for root in roots:
        safe, err = is_safe_path(root, _allowed_bases())
        if not safe:
            continue
        for folder in iter_game_folders(root):
            proposal_path = resolve_proposal_path(folder)
            if not proposal_path:
                continue
            try:
                with open(proposal_path, encoding='utf-8') as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                payload = None
            found.append({
                'path': folder,
                'proposal': (payload or {}).get('proposal'),
            })
    return api_ok({'proposals': found})


@apis_bp.route('/library_tools/doctor/dry_run', methods=['POST'])
@login_required
@admin_required
@validate_body(DoctorDryRunBody)
def library_doctor_dry_run(body: DoctorDryRunBody):
    roots = body.roots
    template = body.template or '{title}'
    limit = body.limit

    safe_roots = []
    for root in roots:
        ok, _ = is_safe_path(root, _allowed_bases())
        if ok:
            safe_roots.append(root)
    if not safe_roots:
        return api_error('No safe roots', code='forbidden')

    rows = doctor_dry_run(safe_roots, template=template, limit=limit)
    return api_ok({'rows': rows, 'count': len(rows)})


@apis_bp.route('/library_tools/doctor/write_proposals', methods=['POST'])
@login_required
@admin_required
@validate_body(WriteProposalsBody)
def library_doctor_write_proposals(body: WriteProposalsBody):
    rows = body.rows
    # Only allow writing under safe bases
    filtered = []
    for row in rows:
        path = row.get('path')
        if path and is_safe_path(path, _allowed_bases())[0]:
            filtered.append(row)
    results = doctor_write_proposals(filtered)
    return api_ok({'results': results})


@apis_bp.route('/library_tools/doctor/apply_renames', methods=['POST'])
@login_required
@admin_required
@validate_body(ApplyRenamesBody)
def library_doctor_apply_renames(body: ApplyRenamesBody):
    from oneirodex.utils.library_doctor import doctor_apply_renames
    rows = body.rows
    template = body.template or '{title}'
    filtered = []
    for row in rows:
        path = row.get('path')
        if path and is_safe_path(path, _allowed_bases())[0]:
            filtered.append(row)
    results = doctor_apply_renames(filtered, _allowed_bases(), template=template)
    # The doctor walks every folder, matched games included: a renamed folder
    # must take its game, update, extra and unmatched rows with it, or those
    # records point at a path that no longer exists.
    moved = 0
    for row in results:
        for item in row.get('results') or []:
            if item.get('ok') and item.get('kind') == 'root_folder':
                moved += repoint_paths(item['from_path'], item['to_path'])
    if moved:
        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            return api_error(
                f'Folders renamed but DB update failed: {exc}',
                code='internal',
                results=results,
            )
    return api_ok({'results': results, 'records_updated': moved})


@apis_bp.route('/library_tools/backfill_steam_metadata', methods=['POST'])
@login_required
@admin_required
def library_tools_backfill_steam_metadata():
    """Repair games that were identified via Steam but landed without content.

    Stage D used to persist only name/summary/cover, and the storesearch hit it
    matched on carries no description at all — so existing rows can have a Steam
    App ID and still show a blank summary with no genres or credits. This re-reads
    ``appdetails`` for those rows and fills the gaps (never overwrites).

    Body: ``library_uuid`` (optional scope), ``limit`` (default 100, max 500),
    ``only_incomplete`` (default true — skip rows that already have summary+genres),
    ``cascade`` (default true — see below).

    With ``cascade`` on, rows **without** a Steam App ID are repairable too. That
    matters because the Steam-only query could never reach a GOG-identified title
    or a console ROM, which are exactly the rows most likely to be bare.
    """
    from oneirodex.utils.steam_metadata import hydrate_game_from_steam

    data = request.get_json(silent=True) or {}
    limit = min(max(int(data.get('limit') or 100), 1), 500)
    only_incomplete = bool(data.get('only_incomplete', True))
    use_cascade = bool(data.get('cascade', True))

    query = select(Game)
    if not use_cascade:
        query = query.filter(Game.steam_app_id.isnot(None))
    if data.get('library_uuid'):
        query = query.filter(Game.library_uuid == data['library_uuid'])

    candidates = db.session.execute(query).scalars().all()

    updated, skipped, errors = [], 0, []
    for game in candidates:
        if len(updated) >= limit:
            break
        if only_incomplete and (game.summary or '').strip() and (game.genres or []):
            skipped += 1
            continue
        try:
            if game.steam_app_id:
                report = hydrate_game_from_steam(game)
            else:
                report = {}
            if use_cascade and not ((game.summary or '').strip() and (game.genres or [])):
                from oneirodex.utils.metadata_cascade import hydrate_game_from_cascade

                # A row that just went through hydrate_game_from_steam has had
                # Steam's appdetails applied already; asking the cascade to
                # search Steam by name again is a round trip per row, and a
                # backfill can run over hundreds of them.
                cascade_result = hydrate_game_from_cascade(
                    game, skip=('steam',) if game.steam_app_id else ()
                )
                for key, value in (cascade_result.get('applied') or {}).items():
                    # Union the two reports so the response says what actually
                    # changed, regardless of which path filled it.
                    if value and not report.get(key):
                        report[key] = value
        except Exception as exc:  # noqa: BLE001
            errors.append({'uuid': game.uuid, 'name': game.name, 'error': str(exc)})
            continue
        changed = any(
            bool(v) for v in report.values()
        ) if report else False
        if changed:
            updated.append({
                'uuid': game.uuid,
                'name': game.name,
                'filled': {k: v for k, v in report.items() if v},
            })
        else:
            skipped += 1

    if updated:
        db.session.commit()

    return api_ok({
        'scanned': len(candidates),
        'updated': len(updated),
        'skipped': skipped,
        'errors': errors,
        'games': updated[:50],
    })


@apis_bp.route('/library_tools/check_freshness', methods=['POST'])
@login_required
@admin_required
@validate_body(CheckFreshnessBody)
def library_tools_check_freshness(body: CheckFreshnessBody):
    """Check version / updates / DLC across a library (FEAT-D1).

    The same pass a scan runs when ``SCAN_CHECK_FRESHNESS`` is on, exposed so it
    can be run against an already-scanned library without a re-scan.

    Body: ``library_uuid`` (required), ``limit`` (default 50, max 500),
    ``only_missing`` (default true — spend the budget on unknowns).
    """
    from oneirodex.utils.freshness.service import check_library_freshness

    library_uuid = body.library_uuid

    library = db.session.execute(
        select(Library).filter_by(uuid=library_uuid)
    ).scalars().first()
    if not library:
        return api_error('Library not found', code='not_found')

    try:
        limit = min(max(int(body.limit or 50), 1), 500)
    except (TypeError, ValueError):
        return api_error('limit must be a number', code='bad_request')

    result = check_library_freshness(
        library_uuid,
        limit=limit,
        only_missing=bool(body.only_missing),
    )
    return api_ok(result)
