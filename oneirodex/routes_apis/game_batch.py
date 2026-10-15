"""Member Library multi-select batch routes: favorite, status, wishlist,
freshness check, refresh images. Honest caps per batch (not DRM queues).

Split out of ``routes_apis/game.py`` in the v11 cycle (H-D.4) as a pure move;
registered on ``apis_bp`` when ``game`` is imported.
"""
# /oneirodex/routes_apis/game.py
from datetime import datetime, timezone

from flask import current_app, jsonify, request
from flask_login import login_required, current_user
from oneirodex import db
from oneirodex.models import (
    Game,
    GameRequest,
    get_status_info,
    user_favorites,
    user_game_status,
)
from oneirodex.schemas.game import BatchFavoriteBody
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.play_status import PLAY_STATUS_VALUES
from oneirodex.utils.background import run_in_background
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.rbac import can_request_games, librarian_required
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.scanning import refresh_images_in_background
from oneirodex.utils.validation import validate_batch_body
from oneirodex.utils.api_tokens import require_api_token_scope
from sqlalchemy import and_, delete, select
from . import apis_bp


# Member Library multi-select caps (honest limits — not DRM queues).
BATCH_FAVORITE_MAX = 100
BATCH_STATUS_MAX = 100
BATCH_FRESHNESS_MAX = 50
BATCH_WISHLIST_MAX = 50
BATCH_REFRESH_IMAGES_MAX = 20
FRESHNESS_STALE_SECONDS = 86400
# INSP-4/21: `null` (Won't play) was missing here, so the multi-select bar
# could set four of the five statuses and silently refused the fifth.
BATCH_STATUS_VALUES = PLAY_STATUS_VALUES


def _normalize_batch_uuids(raw, *, max_size: int) -> tuple[list[str] | None, dict | None, int]:
    """Return (uuids, error_response_dict, http_status). Dedupes, preserves order."""
    if not isinstance(raw, list):
        return None, {'ok': False, 'error': 'uuids must be a list', 'updated': [], 'skipped': [], 'errors': []}, 400
    if len(raw) > max_size:
        return None, {
            'ok': False,
            'error': f'uuids exceeds limit of {max_size}',
            'limit': max_size,
            'requested': len(raw),
            'updated': [],
            'skipped': [],
            'errors': [],
        }, 400
    seen: set[str] = set()
    uuids: list[str] = []
    for item in raw:
        uid = (str(item) if item is not None else '').strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        uuids.append(uid)
    return uuids, None, 200


@apis_bp.route('/games/batch/favorite', methods=['POST'])
@login_required
@require_api_token_scope('write:library')
@validate_batch_body(BatchFavoriteBody, limit=BATCH_FAVORITE_MAX)
def games_batch_favorite(body: BatchFavoriteBody):
    """Set favorite on/off for many library titles (member multi-select).

    Body JSON:
      uuids (list, required, max 100)
      favorite (bool, required) — true = add, false = remove

    Partial success: ``{ ok, updated, skipped, errors, limit }``.
    Skips not-found / forbidden / already-set; does not invent download queues.
    """
    uuids, err, status = _normalize_batch_uuids(body.uuids, max_size=BATCH_FAVORITE_MAX)
    if err is not None:
        return jsonify(err), status
    favorite = body.favorite

    if not uuids:
        return api_ok({
            'updated': [],
            'skipped': [],
            'errors': [],
            'limit': BATCH_FAVORITE_MAX,
            'favorite': favorite,
            'requested': 0,
        })

    games = {
        g.uuid: g
        for g in db.session.execute(select(Game).filter(Game.uuid.in_(uuids))).scalars().all()
    }
    already = set(
        db.session.execute(
            select(user_favorites.c.game_uuid).where(
                user_favorites.c.user_id == current_user.id,
                user_favorites.c.game_uuid.in_(uuids),
            )
        ).scalars().all()
    )

    updated = []
    skipped = []
    errors = []
    for uid in uuids:
        game = games.get(uid)
        if not game:
            skipped.append({'uuid': uid, 'reason': 'not_found'})
            continue
        if not user_can_access_game(current_user, game):
            skipped.append({'uuid': uid, 'reason': 'forbidden'})
            continue
        is_fav = uid in already
        if favorite and is_fav:
            skipped.append({'uuid': uid, 'reason': 'already_set'})
            continue
        if not favorite and not is_fav:
            skipped.append({'uuid': uid, 'reason': 'already_set'})
            continue
        try:
            if favorite:
                current_user.favorites.append(game)
                already.add(uid)
            else:
                current_user.favorites.remove(game)
                already.discard(uid)
            updated.append({'uuid': uid, 'favorite': favorite})
        except Exception as exc:
            errors.append({'uuid': uid, 'error': str(exc)})

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('batch commit failed: %s', exc)
        return api_error(
            'Could not save the change', code='internal',
            updated=[], skipped=skipped, errors=errors, limit=BATCH_FAVORITE_MAX,
        )

    # Deliberately not api_ok: `ok` here answers "did every item succeed",
    # not "did the request succeed". The SPA reads `data.ok !== false`
    # (api/batchActions.ts) to flag a partial batch, and api_ok would stamp it
    # True and hide the failures. Recorded in the envelope baseline on purpose.
    return jsonify({
        'ok': len(errors) == 0,
        'updated': updated,
        'skipped': skipped,
        'errors': errors,
        'limit': BATCH_FAVORITE_MAX,
        'favorite': favorite,
        'requested': len(uuids),
        'count': len(updated),
    })


@apis_bp.route('/games/batch/status', methods=['POST'])
@login_required
@require_api_token_scope('write:library')
def games_batch_status():
    """Set or clear play status for many library titles (member multi-select).

    Body JSON:
      uuids (list[str], required, max 100)
      status (str, required) — ``unplayed`` | ``unfinished`` | ``beaten`` |
        ``completed`` | ``''`` (empty clears, same as ``set_game_status``)

    AuthZ: ``user_can_access_game`` per title. Partial success shape matches
    batch favorite. Not a DRM download queue.
    """
    data = request.get_json(silent=True) or {}
    uuids, err, status_code = _normalize_batch_uuids(data.get('uuids'), max_size=BATCH_STATUS_MAX)
    if err is not None:
        return jsonify(err), status_code
    if 'status' not in data:
        return api_error(
            'status required', code='bad_request',
            updated=[], skipped=[], errors=[], limit=BATCH_STATUS_MAX,
        )
    status = data.get('status')
    if status is None:
        status = ''
    if not isinstance(status, str):
        return api_error(
            'status must be a string', code='bad_request',
            updated=[], skipped=[], errors=[], limit=BATCH_STATUS_MAX,
        )
    status = status.strip()
    if status not in BATCH_STATUS_VALUES:
        return api_error(
            'Invalid status value', code='bad_request',
            updated=[], skipped=[], errors=[], limit=BATCH_STATUS_MAX,
        )

    clear = status == ''
    status_out = None if clear else status
    status_info = get_status_info(status_out)

    if not uuids:
        return api_ok({
            'updated': [],
            'skipped': [],
            'errors': [],
            'limit': BATCH_STATUS_MAX,
            'status': status_out,
            'status_info': status_info,
            'requested': 0,
            'count': 0,
        })

    games = {
        g.uuid: g
        for g in db.session.execute(select(Game).filter(Game.uuid.in_(uuids))).scalars().all()
    }
    existing_rows = {
        row[0]: row[1]
        for row in db.session.execute(
            select(user_game_status.c.game_uuid, user_game_status.c.status).where(
                and_(
                    user_game_status.c.user_id == current_user.id,
                    user_game_status.c.game_uuid.in_(uuids),
                )
            )
        ).all()
    }

    updated = []
    skipped = []
    errors = []
    now = datetime.now(timezone.utc)

    for uid in uuids:
        game = games.get(uid)
        if not game:
            skipped.append({'uuid': uid, 'reason': 'not_found'})
            continue
        if not user_can_access_game(current_user, game):
            skipped.append({'uuid': uid, 'reason': 'forbidden'})
            continue
        current = existing_rows.get(uid)
        if clear and current is None:
            skipped.append({'uuid': uid, 'reason': 'already_set'})
            continue
        if not clear and current == status:
            skipped.append({'uuid': uid, 'reason': 'already_set'})
            continue
        try:
            if clear:
                db.session.execute(
                    delete(user_game_status).where(
                        and_(
                            user_game_status.c.user_id == current_user.id,
                            user_game_status.c.game_uuid == uid,
                        )
                    )
                )
                existing_rows.pop(uid, None)
            elif current is not None:
                db.session.execute(
                    user_game_status.update().where(
                        and_(
                            user_game_status.c.user_id == current_user.id,
                            user_game_status.c.game_uuid == uid,
                        )
                    ).values(status=status, updated_at=now)
                )
                existing_rows[uid] = status
            else:
                db.session.execute(
                    user_game_status.insert().values(
                        user_id=current_user.id,
                        game_uuid=uid,
                        status=status,
                        updated_at=now,
                    )
                )
                existing_rows[uid] = status
            updated.append({'uuid': uid, 'status': status_out})
        except Exception as exc:
            errors.append({'uuid': uid, 'error': str(exc)})

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('batch status commit failed: %s', exc)
        return api_error(
            'Could not save the play status', code='internal',
            updated=[], skipped=skipped, errors=errors,
            limit=BATCH_STATUS_MAX, status=status_out,
        )

    # Deliberately not api_ok: `ok` here answers "did every item succeed",
    # not "did the request succeed". The SPA reads `data.ok !== false`
    # (api/batchActions.ts) to flag a partial batch, and api_ok would stamp it
    # True and hide the failures. Recorded in the envelope baseline on purpose.
    return jsonify({
        'ok': len(errors) == 0,
        'updated': updated,
        'skipped': skipped,
        'errors': errors,
        'limit': BATCH_STATUS_MAX,
        'status': status_out,
        'status_info': status_info,
        'requested': len(uuids),
        'count': len(updated),
    })


@apis_bp.route('/games/batch/wishlist', methods=['POST'])
@login_required
@require_api_token_scope('write:library')
def games_batch_wishlist():
    """Queue wishlist / request rows for selected library titles (by UUID).

    Body JSON:
      uuids (list[str], required, max 50)
      action (str, optional): ``add`` (default) or ``remove`` pending linked requests

    Creates ``GameRequest`` rows with ``title`` from ``Game.name`` and
    ``linked_game_uuid`` set to the source title. Honors ``can_request_games``
    (403 for child / unavailable accounts). Skips pending duplicates by title
    or linked UUID. Cap 50 — not a DRM download queue.

    Canonical path: ``POST /api/games/batch/wishlist`` (not ``/api/requests/batch``).
    """
    if not can_request_games(current_user):
        # Same refusal as `POST /api/requests` (routes_apis/wishlist.py), so it
        # has to read the same on the wire — a member hitting this from Library
        # multi-select and from a game page is being told one thing.
        return api_error(
            'Wishlist requests are not available for this account',
            code='forbidden',
            updated=[],
            skipped=[],
            errors=[],
            limit=BATCH_WISHLIST_MAX,
        )

    data = request.get_json(silent=True) or {}
    action = str(data.get('action') or 'add').strip().lower()
    if action not in ('add', 'remove'):
        return api_error('action must be add or remove', code='bad_request')
    uuids, err, status_code = _normalize_batch_uuids(data.get('uuids'), max_size=BATCH_WISHLIST_MAX)
    if err is not None:
        return jsonify(err), status_code

    if not uuids:
        return api_ok({
            'updated': [],
            'skipped': [],
            'errors': [],
            'limit': BATCH_WISHLIST_MAX,
            'requested': 0,
            'count': 0,
            'action': action,
        })

    games = {
        g.uuid: g
        for g in db.session.execute(select(Game).filter(Game.uuid.in_(uuids))).scalars().all()
    }
    pending_rows = db.session.execute(
        select(GameRequest).filter_by(user_id=current_user.id, status='pending')
    ).scalars().all()
    pending_titles = {(r.title or '').strip().lower() for r in pending_rows if r.title}
    pending_linked = {r.linked_game_uuid for r in pending_rows if r.linked_game_uuid}
    pending_by_linked = {
        r.linked_game_uuid: r for r in pending_rows if r.linked_game_uuid
    }

    updated = []
    skipped = []
    errors = []

    if action == 'remove':
        for uid in uuids:
            row = pending_by_linked.get(uid)
            if not row:
                skipped.append({'uuid': uid, 'reason': 'not_pending'})
                continue
            try:
                db.session.delete(row)
                updated.append({'uuid': uid, 'id': row.id})
            except Exception as exc:  # pragma: no cover - defensive
                current_app.logger.warning('wishlist batch remove failed: %s', exc)
                errors.append({'uuid': uid, 'error': 'delete_failed'})
        if updated:
            db.session.commit()
        return api_ok({
            'updated': updated,
            'skipped': skipped,
            'errors': errors,
            'limit': BATCH_WISHLIST_MAX,
            'requested': len(uuids),
            'count': len(updated),
            'action': 'remove',
        })

    for uid in uuids:
        game = games.get(uid)
        if not game:
            skipped.append({'uuid': uid, 'reason': 'not_found'})
            continue
        if not user_can_access_game(current_user, game):
            skipped.append({'uuid': uid, 'reason': 'forbidden'})
            continue
        title = (game.name or '').strip()
        if not title:
            skipped.append({'uuid': uid, 'reason': 'unavailable'})
            continue
        title_key = title.lower()
        if uid in pending_linked or title_key in pending_titles:
            skipped.append({'uuid': uid, 'reason': 'already_pending'})
            continue
        try:
            row = GameRequest(
                user_id=current_user.id,
                title=title[:255],
                notes=None,
                status='pending',
                linked_game_uuid=uid,
            )
            db.session.add(row)
            db.session.flush()
            pending_titles.add(title_key)
            pending_linked.add(uid)
            updated.append({
                'uuid': uid,
                'request_id': row.id,
                'title': row.title,
                'status': row.status,
            })
        except Exception as exc:
            errors.append({'uuid': uid, 'error': str(exc)})

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('batch commit failed: %s', exc)
        return api_error(
            'Could not save the change', code='internal',
            updated=[], skipped=skipped, errors=errors, limit=BATCH_WISHLIST_MAX,
        )

    if updated:
        try:
            log_system_event(
                f'Wishlist batch: {len(updated)} request(s) created',
                event_type='game',
                event_level='information',
            )
        except Exception:
            pass

    # Deliberately not api_ok: `ok` here answers "did every item succeed",
    # not "did the request succeed". The SPA reads `data.ok !== false`
    # (api/batchActions.ts) to flag a partial batch, and api_ok would stamp it
    # True and hide the failures. Recorded in the envelope baseline on purpose.
    return jsonify({
        'ok': len(errors) == 0,
        'updated': updated,
        'skipped': skipped,
        'errors': errors,
        'limit': BATCH_WISHLIST_MAX,
        'requested': len(uuids),
        'count': len(updated),
    })


@apis_bp.route('/games/batch/freshness/check', methods=['POST'])
@login_required
@require_api_token_scope('write:library')
def games_batch_freshness_check():
    """On-demand freshness re-probe for selected titles (member multi-select).

    Body JSON:
      uuids (list[str], required, max 50)
      only_stale (bool, default true) — skip games checked in the last 24h
        (same semantics as admin ``POST /api/admin/freshness/refresh``)

    AuthZ: only titles the caller can see. Does not replace admin bulk refresh.
    Partial success: ``{ ok, updated, skipped, errors, limit }``.
    """
    from oneirodex.utils.freshness import check_and_store_freshness

    data = request.get_json(silent=True) or {}
    uuids, err, status = _normalize_batch_uuids(data.get('uuids'), max_size=BATCH_FRESHNESS_MAX)
    if err is not None:
        return jsonify(err), status
    only_stale = bool(data.get('only_stale', True))

    if not uuids:
        return api_ok({
            'updated': [],
            'skipped': [],
            'errors': [],
            'limit': BATCH_FRESHNESS_MAX,
            'only_stale': only_stale,
            'requested': 0,
        })

    games = {
        g.uuid: g
        for g in db.session.execute(select(Game).filter(Game.uuid.in_(uuids))).scalars().all()
    }
    updated = []
    skipped = []
    errors = []
    now = datetime.now(timezone.utc)

    for uid in uuids:
        game = games.get(uid)
        if not game:
            skipped.append({'uuid': uid, 'reason': 'not_found'})
            continue
        if not user_can_access_game(current_user, game):
            skipped.append({'uuid': uid, 'reason': 'forbidden'})
            continue
        if only_stale and game.freshness_checked_at and game.freshness_status:
            checked = game.freshness_checked_at
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            if (now - checked).total_seconds() < FRESHNESS_STALE_SECONDS:
                skipped.append({'uuid': uid, 'reason': 'fresh'})
                continue
        try:
            _ = list(game.updates or [])
            _ = list(game.extras or [])
            _ = list(game.urls or [])
            public = check_and_store_freshness(game, commit=False, db_session=db.session)
            updated.append({
                'uuid': uid,
                'name': game.name,
                'status': public.get('status'),
                'confidence': public.get('confidence'),
            })
        except Exception as exc:
            errors.append({'uuid': uid, 'name': getattr(game, 'name', None), 'error': str(exc)})

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('batch commit failed: %s', exc)
        return api_error(
            'Could not save the change', code='internal',
            updated=[], skipped=skipped, errors=errors, limit=BATCH_FRESHNESS_MAX,
        )

    # Deliberately not api_ok: `ok` here answers "did every item succeed",
    # not "did the request succeed". The SPA reads `data.ok !== false`
    # (api/batchActions.ts) to flag a partial batch, and api_ok would stamp it
    # True and hide the failures. Recorded in the envelope baseline on purpose.
    return jsonify({
        'ok': len(errors) == 0,
        'updated': updated,
        'skipped': skipped,
        'errors': errors,
        'limit': BATCH_FRESHNESS_MAX,
        'only_stale': only_stale,
        'requested': len(uuids),
        'count': len(updated),
    })


@apis_bp.route('/games/batch/refresh_images', methods=['POST'])
@login_required
@librarian_required
def games_batch_refresh_images():
    """Enqueue IGDB image refresh for selected titles (multi-select).

    Body JSON:
      uuids (list[str], required, max 20)

    Queues the same ``refresh_images_in_background`` path as
    ``POST /refresh_game_images/<uuid>``. AuthZ: librarian+ and
    ``user_can_access_game`` per title. Partial success shape matches
    other batch routes.
    """
    data = request.get_json(silent=True) or {}
    uuids, err, status = _normalize_batch_uuids(data.get('uuids'), max_size=BATCH_REFRESH_IMAGES_MAX)
    if err is not None:
        return jsonify(err), status

    if not uuids:
        return api_ok({
            'queued': [],
            'skipped': [],
            'errors': [],
            'limit': BATCH_REFRESH_IMAGES_MAX,
            'requested': 0,
            'count': 0,
        })

    games = {
        g.uuid: g
        for g in db.session.execute(select(Game).filter(Game.uuid.in_(uuids))).scalars().all()
    }
    queued = []
    skipped = []
    errors = []

    for uid in uuids:
        game = games.get(uid)
        if not game:
            skipped.append({'uuid': uid, 'reason': 'not_found'})
            continue
        if not user_can_access_game(current_user, game):
            skipped.append({'uuid': uid, 'reason': 'forbidden'})
            continue
        if not getattr(game, 'igdb_id', None):
            skipped.append({'uuid': uid, 'reason': 'no_igdb_id', 'name': game.name})
            continue
        try:
            # One worker per game, each with its own app context and session
            # (utils/background.py). Sharing the request's session here was the
            # worst of the six sites: a batch queues up to
            # BATCH_REFRESH_IMAGES_MAX threads onto one Session at once.
            run_in_background(
                current_app._get_current_object(),
                refresh_images_in_background,
                uid,
                name=f'oneirodex-refresh-images-{str(uid)[:8]}',
            )
            queued.append({'uuid': uid, 'name': game.name, 'status': 'queued'})
        except Exception as exc:
            errors.append({'uuid': uid, 'name': getattr(game, 'name', None), 'error': str(exc)})

    # Deliberately not api_ok: `ok` here answers "did every item succeed",
    # not "did the request succeed". The SPA reads `data.ok !== false`
    # (api/batchActions.ts) to flag a partial batch, and api_ok would stamp it
    # True and hide the failures. Recorded in the envelope baseline on purpose.
    return jsonify({
        'ok': len(errors) == 0,
        'queued': queued,
        'skipped': skipped,
        'errors': errors,
        'limit': BATCH_REFRESH_IMAGES_MAX,
        'requested': len(uuids),
        'count': len(queued),
    }), 202
