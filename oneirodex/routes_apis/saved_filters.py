"""Named filters and the tree behind them (INSP-3, v11 H-I).

A member's own rows only. There is no admin view of someone else's filters and
no sharing surface: a saved filter says what a person is looking for, which is
theirs, and INSP-29's smart collections are the same row with a tile rather
than a second, more public thing.
"""

from __future__ import annotations

from flask import current_app
from flask_login import current_user, login_required
from sqlalchemy import func, select

from oneirodex import db
from oneirodex.models import Game, SavedFilter
from oneirodex.schemas.saved_filters import (
    FilterPreviewBody,
    SavedFilterCreateBody,
    SavedFilterUpdateBody,
)
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.filter_tree import (
    FilterTreeError,
    compile_filter_tree,
    describe_fields,
    parse_filter_tree,
)
from oneirodex.utils.library_acl import apply_game_access_filters
from oneirodex.utils.api_tokens import require_api_token_scope
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _own(filter_id: int) -> SavedFilter | None:
    return (
        db.session.execute(
            select(SavedFilter).filter_by(id=filter_id, user_id=current_user.id)
        )
        .scalars()
        .first()
    )


def _bad_tree(exc: FilterTreeError):
    # The path is the point: a builder can highlight the offending row instead
    # of saying "invalid filter" over a form with fifteen of them.
    return api_error(str(exc), code='bad_request', detail={'path': exc.path})


@apis_bp.route('/filters/fields', methods=['GET'])
@login_required
def saved_filter_fields():
    """What a builder may offer. The single source is ``filter_tree.FIELDS``."""
    return api_ok({'fields': describe_fields()})


@apis_bp.route('/filters/saved', methods=['GET'])
@login_required
def list_saved_filters():
    rows = (
        db.session.execute(
            select(SavedFilter)
            .filter_by(user_id=current_user.id)
            .order_by(SavedFilter.name)
        )
        .scalars()
        .all()
    )
    return api_ok({'filters': [row.to_dict() for row in rows]})


@apis_bp.route('/filters/saved', methods=['POST'])
@login_required
@require_api_token_scope('write:library')
@validate_body(SavedFilterCreateBody)
def create_saved_filter(body: SavedFilterCreateBody):
    try:
        tree = parse_filter_tree(body.tree)
    except FilterTreeError as exc:
        return _bad_tree(exc)

    existing = (
        db.session.execute(
            select(SavedFilter).filter_by(user_id=current_user.id, name=body.name)
        )
        .scalars()
        .first()
    )
    if existing:
        return api_error(f'You already have a filter called "{body.name}".', code='conflict')

    row = SavedFilter(
        user_id=current_user.id,
        name=body.name,
        tree=tree,
        is_collection=body.is_collection,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.warning('saved filter create failed: %s', exc)
        return api_error("Couldn't save that filter.", code='internal')
    return api_ok({'filter': row.to_dict()}, status=201)


@apis_bp.route('/filters/saved/<int:filter_id>', methods=['PUT'])
@login_required
@require_api_token_scope('write:library')
@validate_body(SavedFilterUpdateBody)
def update_saved_filter(filter_id: int, body: SavedFilterUpdateBody):
    row = _own(filter_id)
    if not row:
        return api_error('Filter not found', code='not_found')

    if body.tree is not None:
        try:
            row.tree = parse_filter_tree(body.tree)
        except FilterTreeError as exc:
            return _bad_tree(exc)
    if body.name is not None and body.name != row.name:
        clash = (
            db.session.execute(
                select(SavedFilter).filter_by(user_id=current_user.id, name=body.name)
            )
            .scalars()
            .first()
        )
        if clash:
            return api_error(f'You already have a filter called "{body.name}".', code='conflict')
        row.name = body.name
    if body.is_collection is not None:
        row.is_collection = body.is_collection

    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.warning('saved filter update failed for %s: %s', filter_id, exc)
        return api_error("Couldn't save that filter.", code='internal')
    return api_ok({'filter': row.to_dict()})


@apis_bp.route('/filters/saved/<int:filter_id>', methods=['DELETE'])
@login_required
@require_api_token_scope('write:library')
def delete_saved_filter(filter_id: int):
    row = _own(filter_id)
    if not row:
        return api_error('Filter not found', code='not_found')
    db.session.delete(row)
    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.warning('saved filter delete failed for %s: %s', filter_id, exc)
        return api_error("Couldn't delete that filter.", code='internal')
    return api_ok({'deleted': filter_id})


@apis_bp.route('/filters/preview', methods=['POST'])
@login_required
@validate_body(FilterPreviewBody)
def preview_filter(body: FilterPreviewBody):
    """How many titles this tree matches, for the builder to show as it is built.

    Counted through the member's own access filters, so the number is the one
    they would get on Browse rather than a household total they cannot reach.
    A malformed tree comes back as a 400 naming the part that is wrong, which
    is also why there is no separate validate route: this one already answers
    that question, and it answers it with a count attached.
    """
    try:
        clause = compile_filter_tree(body.tree, user=current_user)
    except FilterTreeError as exc:
        return _bad_tree(exc)

    base = apply_game_access_filters(select(Game).filter(clause), current_user)
    count = db.session.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    sample = []
    if body.limit:
        rows = db.session.execute(base.order_by(Game.name).limit(body.limit)).scalars().all()
        sample = [{'uuid': g.uuid, 'name': g.name} for g in rows]
    return api_ok({'count': int(count), 'sample': sample})
