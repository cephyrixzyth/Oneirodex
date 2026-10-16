"""Wishlist / game request queue APIs."""

from datetime import datetime, timezone

from flask import jsonify, request

from oneirodex.utils.api_response import api_error, api_ok
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, GameRequest, User
from oneirodex.schemas.wishlist import CreateWishlistRequestBody, ResolveWishlistRequestBody
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.notifications import notify_admins
from oneirodex.utils.rbac import can_request_games, is_librarian
from oneirodex.utils.validation import validate_body
from oneirodex.utils.api_tokens import require_api_token_scope

from . import apis_bp

VALID_RESOLVE_STATUSES = frozenset({'approved', 'rejected', 'fulfilled', 'pending'})

# Matches `GameRequest.title` (String(255)). The duplicate lookup and the insert
# must agree on it — see `create_request`.
_TITLE_MAX = 255


@apis_bp.route('/requests', methods=['GET'])
@login_required
def list_requests():
    if is_librarian(current_user) and request.args.get('all') == '1':
        rows = db.session.execute(
            select(GameRequest).order_by(GameRequest.created_at.desc()).limit(200)
        ).scalars().all()
    else:
        rows = db.session.execute(
            select(GameRequest)
            .filter_by(user_id=current_user.id)
            .order_by(GameRequest.created_at.desc())
            .limit(100)
        ).scalars().all()
    return jsonify({'requests': [r.to_dict() for r in rows]})


@apis_bp.route('/requests', methods=['POST'])
@login_required
@require_api_token_scope('write:library')
@validate_body(CreateWishlistRequestBody)
def create_request(body: CreateWishlistRequestBody):
    if not can_request_games(current_user):
        return api_error(
            'Wishlist requests are not available for this account',
            code='forbidden',
        )
    # Truncate before the duplicate lookup, not at insert time: the row stores
    # `title[:255]`, so searching on the full string never matched a stored long
    # title and every resubmit opened another pending row.
    title = body.title[:_TITLE_MAX]
    existing = db.session.execute(
        select(GameRequest).filter_by(user_id=current_user.id, title=title, status='pending')
    ).scalars().first()
    if existing:
        return jsonify(existing.to_dict())
    row = GameRequest(
        user_id=current_user.id,
        title=title,
        notes=(body.notes or '')[:4000] or None,
        status='pending',
    )
    db.session.add(row)
    db.session.commit()
    log_system_event(
        f'Wishlist request created: {row.title}',
        event_type='game',
        event_level='information',
    )
    return jsonify(row.to_dict()), 201


@apis_bp.route('/requests/<int:request_id>', methods=['DELETE'])
@login_required
@require_api_token_scope('write:library')
def cancel_request(request_id: int):
    """Owner may cancel their own pending request."""
    row = db.session.get(GameRequest, request_id)
    if not row:
        return api_error('Request not found', code='not_found')
    if row.user_id != current_user.id and not is_librarian(current_user):
        return api_error('That request belongs to someone else', code='forbidden')
    if row.status != 'pending' and not is_librarian(current_user):
        return api_error(
            'Only pending requests can be cancelled',
            code='bad_request',
        )
    db.session.delete(row)
    db.session.commit()
    return api_ok({'id': request_id})


@apis_bp.route('/requests/<int:request_id>', methods=['PATCH'])
@login_required
@validate_body(ResolveWishlistRequestBody)
def resolve_request(request_id: int, body: ResolveWishlistRequestBody):
    if not is_librarian(current_user):
        return api_error('Librarian or admin required', code='forbidden')
    row = db.session.get(GameRequest, request_id)
    if not row:
        return api_error('Request not found', code='not_found')
    status = body.status
    if status not in VALID_RESOLVE_STATUSES:
        return api_error('That status is not one this request can move to', code='bad_request')

    linked = (body.linked_game_uuid or '').strip() or None
    if linked:
        game = db.session.execute(select(Game).filter_by(uuid=linked)).scalars().first()
        if not game:
            return api_error('linked_game_uuid does not match a game', code='not_found')
        row.linked_game_uuid = linked
        if status == 'pending':
            status = 'fulfilled'

    row.status = status
    if status == 'pending':
        # Reopening. `pending` is a valid target, so the resolution stamps have
        # to come off with the status — otherwise the row reads as both pending
        # and resolved, and anything keyed on `resolved_at` counts it as closed.
        row.resolved_at = None
        row.resolved_by_user_id = None
    else:
        row.resolved_at = datetime.now(timezone.utc)
        row.resolved_by_user_id = current_user.id
    if body.notes is not None:
        # Librarian resolution note appended into notes field (lightweight)
        note = (body.notes or '').strip()
        if note:
            existing = row.notes or ''
            suffix = f'\n[staff] {note}'
            row.notes = (existing + suffix).strip()[:4000]
    db.session.commit()
    log_system_event(
        f'Wishlist request {row.id} → {status}',
        event_type='game',
        event_level='information',
    )
    if status == 'fulfilled':
        requester = db.session.get(User, row.user_id)
        try:
            notify_admins(
                kind='wishlist',
                title=f'Wishlist fulfilled: {row.title}',
                body=(
                    f'Fulfilled for {requester.name}.'
                    if requester else 'A wishlist request was fulfilled.'
                ),
                link=f'/game_details/{row.linked_game_uuid}' if row.linked_game_uuid else '/wishlist',
                payload={
                    'request_id': row.id,
                    'linked_game_uuid': row.linked_game_uuid,
                    'requester_name': requester.name if requester else None,
                },
            )
        except Exception:
            pass
    return jsonify(row.to_dict())
