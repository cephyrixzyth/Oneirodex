"""Native FastAPI routes for unmatched maintenance and bad-match feedback."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .request_auth import request_auth_context


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


class ScanUnmatchedFeedbackData:
    """Persistence adapter. Tests replace this with an isolated fake."""

    def reclassify_duplicates(self):
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game, UnmatchedFolder
        from oneirodex.utils.duplicate_check import (
            normalize_rom_region, same_duplicate_scope, should_mark_as_duplicate,
        )
        from oneirodex.utils.rom_language import rom_language_fields_from_path
        from oneirodex.utils.scan_match_settings import resolve_scan_match_policy

        rows = db.session.execute(
            select(UnmatchedFolder).options(joinedload(UnmatchedFolder.library))
            .filter_by(status='Duplicate')
        ).scalars().unique().all()
        uuids = [row.matched_game_uuid for row in rows if getattr(row, 'matched_game_uuid', None)]
        games = {}
        if uuids:
            for game in db.session.execute(
                select(Game).options(joinedload(Game.library)).filter(Game.uuid.in_(uuids))
            ).scalars().unique().all():
                games[game.uuid] = game
        threshold = resolve_scan_match_policy().get('dupe_title_threshold')
        changed, kept = [], []
        for folder in rows:
            matched = games.get(getattr(folder, 'matched_game_uuid', None))
            scope = {
                'new_platform': getattr(getattr(folder, 'library', None), 'platform', None),
                'new_library_uuid': folder.library_uuid,
                'new_rom_region': normalize_rom_region(
                    rom_language_fields_from_path(folder.folder_path).get('rom_region')
                ),
            }
            if matched is not None and should_mark_as_duplicate(
                matched, folder.folder_path, title_threshold=threshold, **scope,
            ):
                kept.append(folder.folder_path)
                continue
            folder.status = 'Unmatched'
            if matched is None or not same_duplicate_scope(matched, **scope):
                folder.match_reason = 'cross_system'
                folder.matched_game_uuid = None
                folder.match_score = None
            changed.append(folder.folder_path)
        db.session.commit()
        return {
            'reclassified_to_unmatched': changed,
            'kept_as_duplicate': kept,
            'changed_count': len(changed),
            'kept_count': len(kept),
        }

    def backfill_suggested_kind(self, *, limit, dry_run):
        from oneirodex.utils.match_proposal import backfill_unmatched_suggested_kind

        return backfill_unmatched_suggested_kind(limit=limit, dry_run=dry_run)

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.rollback()

    def unmatched_folder(self, folder_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import UnmatchedFolder

        return db.session.get(UnmatchedFolder, folder_id)

    def commit(self):
        from oneirodex.runtime_native.db_session import native_db as db

        db.session.commit()

    def log_bad_match(self, folder_path, reason, actor_id):
        from oneirodex.utils.event_logging import log_system_event

        log_system_event(
            f'Bad match flagged on {folder_path}: {reason}',
            event_type='admin_action', event_level='information', audit_user=actor_id,
        )


def create_scan_unmatched_feedback_router(
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
    options = dict(
        flask_app=flask_app,
        data=data_access if data_access is not None else ScanUnmatchedFeedbackData(),
        find_user=find_user, find_token=find_token,
        commit_token_touch=commit_token_touch, load_user_id=load_user_id,
        login_manager=login_manager, database_scope=database_scope,
    )

    @router.post('/api/unmatched_folders/reclassify_duplicates')
    async def reclassify_duplicates(request: Request):
        return await _run(request, **options, privilege='admin', handler=_reclassify)

    @router.post('/api/unmatched_folders/backfill_suggested_kind')
    async def backfill_suggested_kind(request: Request):
        return await _run(request, **options, privilege='admin', handler=_backfill)

    @router.api_route('/api/unmatched/bad_match_reasons', methods=['GET', 'HEAD'])
    async def bad_match_reasons(request: Request):
        return await _run(request, **options, privilege='librarian', handler=_reasons)

    @router.post('/api/unmatched/{folder_id:str}/bad_match')
    async def flag_bad_match(folder_id: str, request: Request):
        return await _run(
            request, **options, privilege='librarian', handler=_flag_bad_match,
            folder_id=folder_id,
        )

    return router


def mount_scan_unmatched_feedback_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_scan_unmatched_feedback_router(flask_app, **kwargs))
    return app


async def _run(
    request, *, flask_app, data, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, database_scope, privilege, handler, folder_id=None,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config, find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch, load_user_id=load_user_id,
            login_manager=login_manager,
        )
        response = None
        if request.method not in ('GET', 'HEAD'):
            from .csrf_compat import csrf_error_response

            response = csrf_error_response(request, auth.session_data, flask_app.config)
        if response is None and auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth)
        if response is None:
            response = _privilege_gate(flask_app, request, login_manager, auth, privilege)
        if response is None:
            try:
                response = await handler(request, data, auth, folder_id=folder_id)
            except Exception:
                rollback = getattr(data, 'rollback', None)
                if callable(rollback):
                    try:
                        rollback()
                    except Exception:
                        pass
                response = _error(500, 'internal', 'An error occurred while processing your request')
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response


async def _reclassify(_request, data, _auth, **_):
    # Legacy contract is a plain JSON object (not the standard api_ok envelope).
    return JSONResponse(data.reclassify_duplicates())


async def _backfill(request, data, _auth, **_):
    body = await _json_dict(request)
    result = data.backfill_suggested_kind(
        limit=body.get('limit'), dry_run=bool(body.get('dry_run', False)),
    )
    if result.get('ok', True):
        return _ok({**result, 'status': 'ok'})
    return _error(
        500, 'internal', 'Could not backfill suggested kinds',
        body_status='error', body_error=result.get('error') or 'commit_failed',
        scanned=result.get('scanned'), updated=result.get('updated'),
        skipped_no_sidecar=result.get('skipped_no_sidecar'),
        skipped_empty_hint=result.get('skipped_empty_hint'),
        dry_run=result.get('dry_run'), committed=result.get('committed'),
    )


async def _reasons(_request, _data, _auth, **_):
    return _ok({'reasons': [{'id': key, 'label': label} for key, label in BAD_MATCH_REASONS.items()]})


async def _flag_bad_match(request, data, auth, *, folder_id, **_):
    row = data.unmatched_folder(folder_id)
    if row is None:
        return _error(404, 'not_found', 'Folder not found')
    body = await _json_dict(request)
    raw_reason = body.get('reason')
    if raw_reason in (None, '', False):
        row.bad_match_reason = None
        row.bad_match_note = None
        row.bad_match_at = None
        row.bad_match_by_user_id = None
        data.commit()
        return _ok({'cleared': True})
    reason = str(raw_reason).strip().lower()
    if reason not in BAD_MATCH_REASONS:
        return _error(400, 'bad_request', f"reason must be one of: {', '.join(sorted(BAD_MATCH_REASONS))}")
    raw_note = body.get('note') or ''
    note = (raw_note.strip() if isinstance(raw_note, str) else str(raw_note).strip())[:500]
    if reason == 'other' and not note:
        return _error(400, 'bad_request', 'A note is required when the reason is "other"')
    row.bad_match_reason = reason
    row.bad_match_note = note or None
    row.bad_match_at = datetime.now(timezone.utc)
    row.bad_match_by_user_id = getattr(auth.user, 'id', None)
    data.commit()
    data.log_bad_match(row.folder_path, reason, getattr(auth.user, 'id', None))
    return _ok({
        'folder_id': folder_id, 'reason': reason,
        'label': BAD_MATCH_REASONS[reason], 'note': row.bad_match_note,
    })


async def _json_dict(request):
    if not request.headers.get('content-type', '').lower().startswith('application/json'):
        return {}
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _privilege_gate(flask_app, request, login_manager, auth, privilege):
    from oneirodex.utils.role_catalog import normalize_role

    role = normalize_role(getattr(auth.user, 'role', None) or '')
    if role == 'admin' and auth.token is not None and not auth.has_scope('admin'):
        return _error(403, 'forbidden', 'This token does not have the admin scope')
    if privilege == 'admin' and role != 'admin':
        from .oidc_status import _login_redirect

        return _login_redirect(
            flask_app, request, login_manager, auth,
            message='You must be an admin to access this page.',
            category='danger', include_next=False,
        )
    if privilege == 'librarian' and role not in ('admin', 'librarian'):
        return _error(403, 'forbidden', 'Librarian or admin required')
    return None


def _login_redirect(flask_app, request, login_manager, auth):
    from .oidc_status import _login_redirect as redirect

    return redirect(
        flask_app, request, login_manager, auth,
        message=getattr(login_manager, 'login_message', None),
        category=getattr(login_manager, 'login_message_category', 'message'),
        include_next=True,
    )


def _ok(payload=None):
    from oneirodex.utils.api_contract import api_ok_payload

    return JSONResponse(api_ok_payload(payload))


def _error(status, code, message, **fields):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status, **fields)
    return JSONResponse(payload, status_code=resolved)
