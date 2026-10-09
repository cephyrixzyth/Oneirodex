"""Unmatched-folder edit surface: amend names, mark kind, fix duplicates,
single row and batch.

Split out of ``routes_apis/scan.py`` in the v11 cycle (H-D.4) as a pure move.
"""
# /oneirodex/routes_apis/scan.py

import os
from pathlib import Path

from oneirodex.utils.api_response import api_error, api_ok
from flask import current_app, request
from flask_login import login_required, current_user
from oneirodex import db
from oneirodex.models import UnmatchedFolder, DuplicateFixLog, Library, Game
from sqlalchemy import select
from oneirodex.utils.auth import admin_required, librarian_required
from oneirodex.utils.duplicate_check import (
    folder_basename,
)
from oneirodex.utils.game_name_parse import looks_like_patch_package, parse_game_label
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.security import get_allowed_base_directories, is_safe_path, is_safe_path_strict
from oneirodex.utils.event_logging import log_system_event
from oneirodex.routes_apis.scan_unmatched import UNMATCHED_BATCH_ID_CAP, VALID_DUPLICATE_FIX_ACTIONS
from oneirodex.routes_apis.scan_unmatched_rows import _effective_search_name, _soft_name
from . import apis_bp


def _parse_batch_ids(data: dict):
    raw_ids = data.get('ids')
    if raw_ids is None and isinstance(data.get('items'), list):
        raw_ids = [item.get('id') for item in data['items'] if isinstance(item, dict)]
    if not isinstance(raw_ids, list) or not raw_ids:
        return None, api_error('ids required (non-empty array)', code='bad_request')
    ids = []
    for value in raw_ids:
        text = str(value or '').strip()
        if text:
            ids.append(text)
    if not ids:
        return None, api_error('ids required (non-empty array)', code='bad_request')
    if len(ids) > UNMATCHED_BATCH_ID_CAP:
        return None, api_error(
            f'ids cap is {UNMATCHED_BATCH_ID_CAP}',
            code='bad_request',
            cap=UNMATCHED_BATCH_ID_CAP,
            requested=len(ids),
        )
    seen = set()
    unique = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)
    return unique, None


def _apply_soft_amend(folder: UnmatchedFolder, data: dict) -> dict:
    """Set soft search_name / display_name. Never touches folder_path / disk."""
    changed = {}
    if 'search_name' in data or 'name' in data:
        raw = data['search_name'] if 'search_name' in data else data.get('name')
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            folder.search_name = None
            changed['search_name'] = None
        else:
            folder.search_name = str(raw).strip()[:255]
            changed['search_name'] = folder.search_name
    if 'display_name' in data:
        raw = data.get('display_name')
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            folder.display_name = None
            changed['display_name'] = None
        else:
            folder.display_name = str(raw).strip()[:255]
            changed['display_name'] = folder.display_name
    return changed


def _fix_one_duplicate(folder: UnmatchedFolder, action: str, notes: str | None = None) -> dict:
    """Apply merge|keep|ignore; caller commits."""
    matched_uuid = getattr(folder, 'matched_game_uuid', None)
    match_reason = getattr(folder, 'match_reason', None)
    match_score = getattr(folder, 'match_score', None)
    folder_path = folder.folder_path
    folder_id = folder.id

    if action == 'merge':
        db.session.delete(folder)
        result_status = 'cleared'
    elif action == 'keep':
        folder.status = 'Unmatched'
        result_status = 'Unmatched'
    else:
        folder.status = 'Ignore'
        result_status = 'Ignore'

    fix_log = DuplicateFixLog(
        unmatched_folder_id=folder_id,
        folder_path=folder_path or '',
        matched_game_uuid=matched_uuid,
        match_reason=match_reason,
        match_score=match_score,
        action=action,
        actor_user_id=getattr(current_user, 'id', None),
        notes=notes,
    )
    db.session.add(fix_log)
    return {
        'ok': True,
        'id': folder_id,
        'action': action,
        'folder_id': folder_id,
        'folder_path': folder_path,
        'result_status': result_status,
        'matched_game_uuid': matched_uuid,
        'match_reason': match_reason,
        'match_score': match_score,
    }


@apis_bp.route('/unmatched_folders/<folder_id>/name', methods=['PATCH', 'POST'])
@login_required
@librarian_required
def amend_unmatched_folder_name(folder_id):
    """Soft-amend librarian search/display names. Does NOT rename disk folder_path."""
    data = request.get_json(silent=True) or {}
    if not any(k in data for k in ('search_name', 'display_name', 'name')):
        return api_error(
            'Provide search_name and/or display_name (name aliases search_name)',
            code='bad_request',
            disk_rename=False,
        )

    folder = db.session.get(UnmatchedFolder, folder_id)
    if not folder:
        return api_error('Unmatched folder not found', code='not_found')

    changed = _apply_soft_amend(folder, data)
    if not changed:
        return api_error(
            'Provide search_name and/or display_name (name aliases search_name)',
            code='bad_request',
            disk_rename=False,
        )

    db.session.commit()
    return api_ok({
        'id': folder.id,
        'folder_path': folder.folder_path,
        'folder_name': folder_basename(folder.folder_path) or None,
        'search_name': _soft_name(folder.search_name),
        'display_name': _soft_name(folder.display_name),
        'effective_search_name': _effective_search_name(folder),
        'changed': changed,
        'disk_rename': False,
        'note': 'Soft naming only; disk folder_path unchanged.',
    })


@apis_bp.route('/unmatched_folders/batch/clear', methods=['POST'])
@login_required
@librarian_required
def batch_clear_unmatched_folders():
    """Delete unmatched rows by id (DB only — no disk I/O). Partial success OK."""
    data = request.get_json(silent=True) or {}
    ids, err = _parse_batch_ids(data)
    if err:
        return err

    results = []
    cleared = 0
    for folder_id in ids:
        folder = db.session.get(UnmatchedFolder, folder_id)
        if not folder:
            results.append({'id': folder_id, 'ok': False, 'error': 'not_found'})
            continue
        try:
            db.session.delete(folder)
            db.session.commit()
            results.append({'id': folder_id, 'ok': True, 'result': 'cleared'})
            cleared += 1
        except Exception as exc:
            db.session.rollback()
            results.append({'id': folder_id, 'ok': False, 'error': str(exc)})

    return api_ok({
        'cleared': cleared,
        'failed': sum(1 for r in results if not r.get('ok')),
        'results': results,
        'disk_io': False,
    })


@apis_bp.route('/unmatched_folders/batch/mark_kind', methods=['POST'])
@login_required
@librarian_required
def batch_mark_unmatched_kind():
    """Batch mark_kind. Partial success OK. No disk I/O."""
    from oneirodex.utils.item_kind import ITEM_KINDS, normalize_item_kind
    from oneirodex.utils.software_identify import mark_unmatched_as_kind

    data = request.get_json(silent=True) or {}
    ids, err = _parse_batch_ids(data)
    if err:
        return err

    kind_raw = data.get('item_kind') or data.get('content_kind') or data.get('kind')
    if not kind_raw or not str(kind_raw).strip():
        return api_error(
            f'item_kind required. Choose one of: {sorted(ITEM_KINDS)}',
            code='bad_request',
            item_kinds=sorted(ITEM_KINDS),
        )
    folded = str(kind_raw).strip().lower()
    _aliases = {'app', 'utility', 'utilities', 'software', 'emu', 'experiences'}
    if folded not in ITEM_KINDS and folded not in _aliases:
        return api_error(
            f'Invalid item_kind. Choose one of: {sorted(ITEM_KINDS)}',
            code='bad_request',
            item_kinds=sorted(ITEM_KINDS),
        )
    kind = normalize_item_kind(kind_raw)

    results = []
    marked = 0
    for folder_id in ids:
        folder = db.session.get(UnmatchedFolder, folder_id)
        if not folder:
            results.append({'id': folder_id, 'ok': False, 'error': 'not_found'})
            continue
        try:
            game = mark_unmatched_as_kind(
                folder,
                item_kind=kind,
                name=(data.get('name') or None),
                steam_app_id=None,
                summary=(data.get('summary') or None),
            )
            db.session.commit()
            results.append({
                'id': folder_id,
                'ok': True,
                'game_uuid': game.uuid,
                'name': game.name,
                'item_kind': game.item_kind,
            })
            marked += 1
        except ValueError as exc:
            db.session.rollback()
            results.append({'id': folder_id, 'ok': False, 'error': str(exc)})
        except Exception as exc:
            db.session.rollback()
            results.append({'id': folder_id, 'ok': False, 'error': str(exc)})

    return api_ok({
        'item_kind': kind,
        'marked': marked,
        'failed': sum(1 for r in results if not r.get('ok')),
        'results': results,
        'disk_io': False,
    })


@apis_bp.route('/unmatched_folders/batch/fix', methods=['POST'])
@login_required
@librarian_required
def batch_fix_unmatched_duplicates():
    """Batch duplicate triage (merge|keep|ignore). Partial success OK. No disk I/O."""
    data = request.get_json(silent=True) or {}
    ids, err = _parse_batch_ids(data)
    if err:
        return err

    action = (data.get('action') or '').strip().lower()
    if action not in VALID_DUPLICATE_FIX_ACTIONS:
        return api_error(
            f"Invalid action. Choose one of: {sorted(VALID_DUPLICATE_FIX_ACTIONS)}",
            code='bad_request',
        )

    notes = (data.get('notes') or '')[:512] or None
    results = []
    fixed = 0
    for folder_id in ids:
        folder = db.session.get(UnmatchedFolder, folder_id)
        if not folder:
            results.append({'id': folder_id, 'ok': False, 'error': 'not_found'})
            continue
        try:
            result = _fix_one_duplicate(folder, action, notes=notes)
            db.session.commit()
            results.append(result)
            fixed += 1
        except Exception as exc:
            db.session.rollback()
            results.append({'id': folder_id, 'ok': False, 'error': str(exc)})

    log_system_event(
        f"Batch duplicate fix {action} by {getattr(current_user, 'name', 'admin')}: {fixed}/{len(ids)}",
        event_type='duplicate_fix',
        event_level='information',
        audit_user=getattr(current_user, 'id', None),
    )

    return api_ok({
        'action': action,
        'fixed': fixed,
        'failed': sum(1 for r in results if not r.get('ok')),
        'results': results,
        'disk_io': False,
    })


@apis_bp.route('/unmatched_folders/batch/amend', methods=['POST'])
@login_required
@librarian_required
def batch_amend_unmatched_names():
    """Batch soft-amend search_name/display_name. Partial success OK. No disk rename."""
    data = request.get_json(silent=True) or {}
    items = data.get('items')
    results = []
    amended = 0

    def _amend_one(folder_id: str, payload: dict):
        nonlocal amended
        folder = db.session.get(UnmatchedFolder, folder_id)
        if not folder:
            results.append({'id': folder_id, 'ok': False, 'error': 'not_found'})
            return
        if not any(k in payload for k in ('search_name', 'display_name', 'name')):
            results.append({'id': folder_id, 'ok': False, 'error': 'search_name_or_display_name_required'})
            return
        try:
            changed = _apply_soft_amend(folder, payload)
            db.session.commit()
            results.append({
                'id': folder_id,
                'ok': True,
                'search_name': _soft_name(folder.search_name),
                'display_name': _soft_name(folder.display_name),
                'changed': changed,
            })
            amended += 1
        except Exception as exc:
            db.session.rollback()
            results.append({'id': folder_id, 'ok': False, 'error': str(exc)})

    if isinstance(items, list) and items:
        if len(items) > UNMATCHED_BATCH_ID_CAP:
            return api_error(
                f'ids cap is {UNMATCHED_BATCH_ID_CAP}',
                code='bad_request',
                cap=UNMATCHED_BATCH_ID_CAP,
                requested=len(items),
            )
        for item in items:
            if not isinstance(item, dict):
                results.append({'id': None, 'ok': False, 'error': 'invalid_item'})
                continue
            folder_id = str(item.get('id') or '').strip()
            if not folder_id:
                results.append({'id': None, 'ok': False, 'error': 'id_required'})
                continue
            _amend_one(folder_id, item)
    else:
        ids, err = _parse_batch_ids(data)
        if err:
            return err
        if not any(k in data for k in ('search_name', 'display_name', 'name')):
            return api_error(
                'Provide search_name and/or display_name (or items[] with per-id fields)',
                code='bad_request',
                disk_rename=False,
            )
        for folder_id in ids:
            _amend_one(folder_id, data)

    return api_ok({
        'amended': amended,
        'failed': sum(1 for r in results if not r.get('ok')),
        'results': results,
        'disk_rename': False,
        'disk_io': False,
    })


@apis_bp.route('/unmatched_folders/<folder_id>/fix', methods=['POST'])
@login_required
@admin_required
def fix_duplicate_unmatched(folder_id):
    """
    Apply a duplicate triage action and persist a queryable fix log.

    Actions:
      merge  — keep library game; dismiss Duplicate row (clear unmatched entry)
      keep   — reclassify Duplicate → Unmatched for further review
      ignore — set status Ignore
    """
    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip().lower()
    if action not in VALID_DUPLICATE_FIX_ACTIONS:
        return api_error(
            f"Invalid action. Choose one of: {sorted(VALID_DUPLICATE_FIX_ACTIONS)}",
            code='bad_request',
        )

    folder = db.session.get(UnmatchedFolder, folder_id)
    if not folder:
        return api_error('Unmatched folder not found', code='not_found')

    notes = (data.get('notes') or '')[:512] or None
    matched_uuid = getattr(folder, 'matched_game_uuid', None) or data.get('matched_game_uuid')
    match_reason = getattr(folder, 'match_reason', None)
    match_score = getattr(folder, 'match_score', None)
    folder_path = folder.folder_path

    result = _fix_one_duplicate(folder, action, notes=notes)
    db.session.commit()

    log_system_event(
        f"Duplicate fix {action} by {getattr(current_user, 'name', 'admin')}: {folder_path}",
        event_type='duplicate_fix',
        event_level='information',
        audit_user=getattr(current_user, 'id', None),
    )

    fix_log = db.session.execute(
        select(DuplicateFixLog).filter_by(
            unmatched_folder_id=folder_id,
            action=action,
        ).order_by(DuplicateFixLog.created_at.desc())
    ).scalars().first()

    return api_ok({
        'action': action,
        'folder_id': folder_id,
        'folder_path': folder_path,
        'result_status': result['result_status'],
        'matched_game_uuid': matched_uuid,
        'match_reason': match_reason,
        'match_score': match_score,
        'fix_log_id': fix_log.id if fix_log else None,
    })


@apis_bp.route('/unmatched_folders/<folder_id>/mark_kind', methods=['POST'])
@login_required
@admin_required
def mark_unmatched_folder_kind(folder_id):
    """Catalog an Unmatched folder as Experience / Emulator / Tool (or Game).

    Body JSON:
      item_kind (required): game|experience|emulator|tool
      name (optional): display title override
      steam_app_id (optional): Steam AppID for register-only metadata link
      summary (optional)

    Creates a custom-range Game (igdb_id >= 2000000420) with item_kind set,
    clears the Unmatched row. Never queues DRM store downloads.
    """
    from oneirodex.utils.item_kind import ITEM_KINDS, normalize_item_kind
    from oneirodex.utils.software_identify import mark_unmatched_as_kind

    data = request.get_json(silent=True) or {}
    kind_raw = data.get('item_kind') or data.get('content_kind') or data.get('kind')
    if not kind_raw or not str(kind_raw).strip():
        return api_error(
            f'item_kind required. Choose one of: {sorted(ITEM_KINDS)}',
            code='bad_request',
            item_kinds=sorted(ITEM_KINDS),
        )
    folded = str(kind_raw).strip().lower()
    _aliases = {'app', 'utility', 'utilities', 'software', 'emu', 'experiences'}
    if folded not in ITEM_KINDS and folded not in _aliases:
        return api_error(
            f'Invalid item_kind. Choose one of: {sorted(ITEM_KINDS)}',
            code='bad_request',
            item_kinds=sorted(ITEM_KINDS),
        )
    kind = normalize_item_kind(kind_raw)

    folder = db.session.get(UnmatchedFolder, folder_id)
    if not folder:
        return api_error('Unmatched folder not found', code='not_found')

    steam_app_id = data.get('steam_app_id')
    try:
        steam_app_id = int(steam_app_id) if steam_app_id is not None else None
    except (TypeError, ValueError):
        return api_error('steam_app_id must be an integer', code='bad_request')

    try:
        game = mark_unmatched_as_kind(
            folder,
            item_kind=kind,
            name=(data.get('name') or None),
            steam_app_id=steam_app_id,
            summary=(data.get('summary') or None),
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc), code='bad_request')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('scan match update failed: %s', exc)
        return api_error('Could not update the match', code='internal')

    log_system_event(
        f"Marked unmatched as {kind}: {game.name} ({game.uuid})",
        event_type='identify',
        event_level='information',
        audit_user=getattr(current_user, 'id', None),
    )
    return api_ok({
        'game_uuid': game.uuid,
        'name': game.name,
        'item_kind': game.item_kind,
        'content_kind': game.item_kind,
        'igdb_id': game.igdb_id,
        'steam_app_id': game.steam_app_id,
        'full_disk_path': game.full_disk_path,
    })


@apis_bp.route('/unmatched_folders/<folder_id>/retry_match', methods=['POST'])
@login_required
@librarian_required
def retry_unmatched_folder_match(folder_id):
    """Re-run the current metadata matching pipeline for one existing row."""
    folder = db.session.get(UnmatchedFolder, folder_id)
    if not folder:
        return api_error('Unmatched folder not found', code='not_found')
    if folder.status != 'Unmatched':
        return api_error('Only Unmatched folders can be retried', code='bad_request')

    library = db.session.get(Library, folder.library_uuid) if folder.library_uuid else None
    raw_path = (folder.folder_path or '').strip()
    path = Path(raw_path)
    if not library or not raw_path or not path.is_dir() or path.is_symlink():
        return api_error('The folder or its library is unavailable', code='bad_request')
    safe, _ = is_safe_path(raw_path, get_allowed_base_directories(current_app))
    if not safe:
        return api_error('The folder is outside the configured library paths', code='bad_request')

    parsed = parse_game_label(path.name)
    if looks_like_patch_package(path.name) or parsed.get('is_bare_update_package'):
        return api_error('This folder is an update package; use Place update instead', code='bad_request')
    search_name = _soft_name(folder.search_name) or parsed.get('cleaned_name') or path.name
    # Prefer the cleaned title on retries too, so legacy rows with numeric store
    # IDs or scene noise use the same query the scanner would use today.
    search_name = parse_game_label(search_name).get('cleaned_name') or search_name

    try:
        from oneirodex.utils.services.scan_identify import retrieve_and_save_game

        game = retrieve_and_save_game(
            search_name,
            raw_path,
            library_uuid=library.uuid,
            defer_enrichment=True,
        )
        if isinstance(game, Game):
            db.session.delete(folder)
            db.session.commit()
            return api_ok({
                'matched': True,
                'game_uuid': game.uuid,
                'name': game.name,
                'search_name': search_name,
            })
        db.session.commit()
        return api_ok({'matched': False, 'search_name': search_name})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('unmatched retry failed for row %s: %s', folder_id, exc)
        return api_error('Could not retry metadata matching', code='internal')


@apis_bp.route('/unmatched_folders/<folder_id>/place_update', methods=['POST'])
@login_required
@librarian_required
def place_unmatched_update(folder_id):
    """Move a confirmed patch folder under its game's Updates directory."""
    data = request.get_json(silent=True) or {}
    folder = db.session.get(UnmatchedFolder, folder_id)
    if not folder:
        return api_error('Unmatched folder not found', code='not_found')
    if folder.status != 'Unmatched':
        return api_error('Only Unmatched folders can be placed as updates', code='bad_request')

    library = db.session.get(Library, folder.library_uuid) if folder.library_uuid else None
    library_root_value = (getattr(library, 'last_scan_folder', None) or '').strip() if library else ''
    library_root = Path(library_root_value) if library_root_value else None
    source = Path((folder.folder_path or '').strip())
    if library_root is None or not source.is_dir() or source.is_symlink():
        return api_error('The folder or its scan root is unavailable', code='bad_request')

    allowed_bases = get_allowed_base_directories(current_app)
    source_safe, _ = is_safe_path_strict(str(source), allowed_bases)
    root_safe, _ = is_safe_path(str(library_root), allowed_bases)
    if not source_safe or not root_safe:
        return api_error('The folder is outside the configured library paths', code='bad_request')
    try:
        source.resolve(strict=True).relative_to(library_root.resolve(strict=True))
    except (OSError, ValueError):
        return api_error('The folder is outside this library scan root', code='bad_request')

    parsed = parse_game_label(source.name)
    if not (looks_like_patch_package(source.name) or parsed.get('is_bare_update_package')):
        return api_error('This folder is not recognized as a standalone update package', code='bad_request')
    requested_root_name = str(data.get('game_root_name') or parsed.get('cleaned_name') or '').strip()
    if not requested_root_name:
        return api_error('A game folder name is required', code='bad_request')
    from oneirodex.utils.disk_rename import sanitize_fs_name

    game_root_name = sanitize_fs_name(requested_root_name)
    if game_root_name in {'.', '..'}:
        return api_error('Invalid game folder name', code='bad_request')

    existing_game = db.session.execute(
        select(Game).filter_by(library_uuid=library.uuid, name=game_root_name).order_by(Game.uuid)
    ).scalars().first()
    if existing_game and existing_game.full_disk_path:
        game_root = Path(existing_game.full_disk_path)
        game_root_safe, _ = is_safe_path(str(game_root), allowed_bases)
        if not game_root_safe or not game_root.is_dir() or game_root.is_symlink():
            return api_error('The matching game folder is unavailable', code='bad_request')
        try:
            game_root.resolve(strict=True).relative_to(library_root.resolve(strict=True))
        except (OSError, ValueError):
            return api_error('The matching game folder is outside this library scan root', code='bad_request')
        created_game_root = False
    else:
        game_root = library_root / game_root_name
        game_root_safe, _ = is_safe_path_strict(str(game_root), allowed_bases)
        if not game_root_safe:
            return api_error('The destination is outside the configured library paths', code='bad_request')
        if game_root.is_symlink() or (game_root.exists() and not game_root.is_dir()):
            return api_error('The destination game folder is not a usable directory', code='conflict')
        created_game_root = not game_root.exists()

    settings = global_settings_row()
    update_folder_name = sanitize_fs_name(getattr(settings, 'update_folder_name', None) or 'updates')
    updates_root = game_root / update_folder_name
    destination = updates_root / source.name
    if destination.exists():
        return api_error('An update with that folder name already exists', code='conflict')
    for candidate in (updates_root, destination):
        candidate_safe, _ = is_safe_path_strict(str(candidate), allowed_bases)
        if not candidate_safe:
            return api_error('The destination is outside the configured library paths', code='bad_request')

    moved = False
    try:
        game_root.mkdir(parents=True, exist_ok=True)
        updates_root.mkdir(parents=True, exist_ok=True)
        os.rename(source, destination)
        moved = True
        if existing_game:
            from oneirodex.utils.scanning import process_game_updates

            process_game_updates(
                existing_game.name,
                str(game_root),
                str(updates_root),
                library.uuid,
                update_folder_name,
            )
        db.session.delete(folder)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        if moved and destination.exists() and not source.exists():
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                os.rename(destination, source)
            except OSError:
                current_app.logger.exception('Could not restore update folder after failed placement')
        current_app.logger.warning('update placement failed for row %s: %s', folder_id, exc)
        return api_error('Could not place the update folder', code='internal')

    return api_ok({
        'placed': True,
        'game_root_name': game_root_name,
        'created_game_root': created_game_root,
        'matched_game_uuid': existing_game.uuid if existing_game else None,
    })
