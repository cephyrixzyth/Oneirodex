"""Admin library tools: rename preview/apply, match proposals, library doctor."""

from __future__ import annotations

import json
import os

from oneirodex.utils.api_response import api_error, api_ok
from flask import jsonify, request, current_app, session
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from oneirodex import db
from oneirodex.models import AllowedFileType, Game, Library, UnmatchedFolder
from oneirodex.schemas.library_tools import (
    ApplyRenamesBody,
    ApproveProposalBody,
    CheckFreshnessBody,
    DoctorDryRunBody,
    LinkExistingGameBody,
    ManualScanListBody,
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
from oneirodex.utils.functions import (
    load_scanning_filter_patterns,
    load_skip_dir_patterns,
    load_skip_dir_regex_patterns,
)
from oneirodex.utils.gamenames import get_game_names_from_files, get_game_names_from_folder
from oneirodex.utils.library_roots import resolve_scan_path
from oneirodex.utils.services.scan_orchestration import resolve_scan_mode_for_path
from oneirodex.utils.validation import validate_body
from oneirodex.utils.event_logging import log_system_event

from . import apis_bp


def _allowed_bases():
    return get_allowed_base_directories(current_app)


@apis_bp.route('/library_tools/manual_identify/preview', methods=['GET'])
@login_required
@admin_required
def manual_identify_preview():
    """List candidate games for the manual identify workflow without starting a scan.

    This deliberately does not use the legacy ManualScan form handler: when a
    scan is already running that handler queues a real scan. Results here are
    read-only and are submitted to the existing add/identify form only after an
    administrator chooses a row.
    """
    library_uuid = (request.args.get('library_uuid') or '').strip()
    library = db.session.get(Library, library_uuid) if library_uuid else None
    if not library:
        return api_error('Choose a valid library', code='bad_request')

    folder_path, root_error = resolve_scan_path(
        request.args.get('folder') or '', request.args.get('root') or '', current_app,
    )
    if root_error:
        return api_error('The selected scan location is unavailable', code='bad_request')
    safe, err = is_safe_path(folder_path, _allowed_bases())
    if not safe:
        return api_error(err or 'Unsafe path', code='forbidden')
    if not os.path.isdir(folder_path) or not os.access(folder_path, os.R_OK):
        return api_error('The selected folder does not exist or cannot be read', code='bad_request')

    mode = resolve_scan_mode_for_path(folder_path, request.args.get('scan_mode') or 'auto')
    insensitive, sensitive = load_scanning_filter_patterns()
    if mode == 'folders':
        games = get_game_names_from_folder(
            folder_path,
            insensitive,
            sensitive,
            scan_depth=getattr(library, 'scan_depth', 1) or 1,
            skip_dir_patterns=load_skip_dir_patterns(),
            skip_dir_regexes=load_skip_dir_regex_patterns(),
        )
    else:
        extensions = [
            row.value for row in db.session.execute(
                select(AllowedFileType).order_by(AllowedFileType.value.asc())
            ).scalars().all()
        ]
        if not extensions:
            return api_error('No supported game file types are configured', code='unprocessable')
        games = get_game_names_from_files(folder_path, extensions, insensitive, sensitive)

    response = api_ok({
        'library_uuid': library.uuid,
        'library_name': library.name,
        'folder': os.path.normpath(folder_path),
        'scan_mode': mode,
        'games': games,
        'count': len(games),
        'read_only': True,
    })
    response[0].headers['Cache-Control'] = 'no-store'
    return response


@apis_bp.route('/library_tools/manual_identify/list', methods=['POST'])
@login_required
@admin_required
@validate_body(ManualScanListBody)
def manual_identify_list_or_queue(body: ManualScanListBody):
    """Preserve ManualScan's two modes and ask before busy-scan queue/force."""
    library = db.session.get(Library, body.library_uuid)
    if not library:
        return api_error('Choose a valid library', code='bad_request')
    folder_path, root_error = resolve_scan_path(body.folder or '', body.root or '', current_app)
    if root_error:
        return api_error('The selected scan location is unavailable', code='bad_request')
    safe, _path_error = is_safe_path(folder_path, _allowed_bases())
    if not safe:
        return api_error('The selected folder is outside configured storage roots', code='forbidden')
    if not os.path.isdir(folder_path) or not os.access(folder_path, os.R_OK):
        return api_error('The selected folder does not exist or cannot be read', code='bad_request')

    from oneirodex.utils.scan_queue import is_scan_busy, start_or_queue_scan
    mode = resolve_scan_mode_for_path(folder_path, body.scan_mode)
    if is_scan_busy():
        if body.queue_policy == 'inspect':
            response = api_ok({
                'action': 'conflict',
                'message': 'Another scan is already running.',
                'read_only': True,
            })
            response[0].headers['Cache-Control'] = 'no-store'
            return response
        result = start_or_queue_scan(
            folder_path=folder_path,
            library_uuid=library.uuid,
            scan_mode=mode,
            remove_missing=False,
            download_missing_images=False,
            force_updates_extras_scan=body.force_updates_extras_scan,
            fetch_hltb=body.fetch_hltb,
            force_hltb_refetch=body.force_hltb_refetch,
            schedule=None,
            queue_policy=body.queue_policy,
            allow_force=True,
            app=current_app._get_current_object(),
        )
        if result.get('status') not in ('started', 'queued'):
            return api_error(result.get('message') or 'Manual scan could not be queued', code='conflict', status=409)
        response = api_ok({
            'action': result['status'],
            'message': result.get('message') or 'Manual scan queued.',
            'job_id': result.get('job_id'),
            'position': result.get('position'),
            'read_only': False,
        })
        response[0].headers['Cache-Control'] = 'no-store'
        return response

    from oneirodex.utils.global_settings import global_settings_row
    from oneirodex.utils.local_metadata import check_library_write_permissions
    settings = global_settings_row()
    if settings and settings.write_local_metadata:
        all_ok, failed_paths = check_library_write_permissions(folder_path)
        if not all_ok:
            return api_error(
                'Review local metadata write permissions before identifying this folder.',
                code='unprocessable',
                detail={'failed_count': len(failed_paths)},
            )

    insensitive, sensitive = load_scanning_filter_patterns()
    if mode == 'folders':
        games = get_game_names_from_folder(
            folder_path,
            insensitive,
            sensitive,
            scan_depth=getattr(library, 'scan_depth', 1) or 1,
            skip_dir_patterns=load_skip_dir_patterns(),
            skip_dir_regexes=load_skip_dir_regex_patterns(),
        )
    else:
        extensions = [
            row.value for row in db.session.execute(
                select(AllowedFileType).order_by(AllowedFileType.value.asc())
            ).scalars().all()
        ]
        if not extensions:
            return api_error('No supported game file types are configured', code='unprocessable')
        games = get_game_names_from_files(folder_path, extensions, insensitive, sensitive)
    session['selected_library_uuid'] = library.uuid
    session['game_paths'] = {row['name']: row['full_path'] for row in games}
    session['force_updates_extras_scan'] = body.force_updates_extras_scan
    session['fetch_hltb'] = body.fetch_hltb
    session['force_hltb_refetch'] = body.force_hltb_refetch
    response = api_ok({
        'action': 'preview',
        'library_uuid': library.uuid,
        'library_name': library.name,
        'folder': os.path.normpath(folder_path),
        'scan_mode': mode,
        'games': games,
        'count': len(games),
        'read_only': True,
    })
    response[0].headers['Cache-Control'] = 'no-store'
    return response


@apis_bp.route('/library_tools/link_existing_game', methods=['POST'])
@login_required
@admin_required
@validate_body(LinkExistingGameBody)
def link_existing_game_api(body: LinkExistingGameBody):
    """Link a scanned folder to an existing game with the classic route's semantics."""
    safe, error = is_safe_path(body.full_disk_path, _allowed_bases())
    if not safe:
        return api_error(error or 'Unsafe path', code='forbidden')
    if not os.path.isdir(body.full_disk_path) or not os.access(body.full_disk_path, os.R_OK):
        return api_error('The selected folder does not exist or cannot be read', code='bad_request')

    game = db.session.get(Game, body.game_uuid)
    if not game:
        return api_error('Selected game could not be found', code='not_found')
    try:
        game.full_disk_path = body.full_disk_path
        from oneirodex.utils.library_health import mark_game_path_ok

        mark_game_path_ok(game)
        try:
            from oneirodex.utils.rom_language import apply_rom_language_fields

            apply_rom_language_fields(game, body.full_disk_path)
        except Exception:
            pass
        unmatched = db.session.execute(
            select(UnmatchedFolder).filter_by(folder_path=body.full_disk_path)
        ).scalars().first()
        if unmatched:
            db.session.delete(unmatched)
        db.session.commit()
        log_system_event(
            f"Admin {current_user.name} linked existing game '{game.name}' (UUID: {game.uuid}) to folder" +
            (' (removed from unmatched list)' if unmatched else ''),
            event_type='game',
            event_level='information',
        )
    except SQLAlchemyError as exc:
        db.session.rollback()
        log_system_event(
            f"Database error linking game '{body.game_uuid}' by admin {current_user.name}: {str(exc)[:200]}",
            event_type='error',
            event_level='error',
        )
        return api_error('Unable to link this folder to the selected game', code='internal')

    return api_ok({
        'game_uuid': game.uuid,
        'game_name': game.name,
        'full_disk_path': game.full_disk_path,
        'library_uuid': body.library_uuid,
        'from_unmatched': body.from_unmatched,
        'removed_from_unmatched': bool(unmatched),
    })


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
        current_app.logger.warning('Proposal cleanup failed (%s)', type(exc).__name__)
        return api_error('Could not clear proposal files', code='internal')
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
