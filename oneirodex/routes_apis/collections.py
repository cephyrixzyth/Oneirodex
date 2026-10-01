"""Collections and announcements APIs."""

from flask import jsonify, request

from oneirodex.utils.api_response import api_error, api_ok
from flask_login import current_user, login_required
from sqlalchemy import func, select

from oneirodex import db
from oneirodex.models import Announcement, Game, GameCollection, GameCollectionItem
from oneirodex.schemas.collections import (
    AddCollectionItemBody,
    CreateAnnouncementBody,
    CreateCollectionBody,
    ReorderCollectionItemsBody,
)
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.validation import validate_body

from . import apis_bp
from oneirodex.utils.rbac import is_admin


def _can_edit_collection(collection: GameCollection) -> bool:
    return (
        collection.owner_user_id == current_user.id
        or is_admin(current_user)
    )


def _collection_payload(collection: GameCollection, *, include_items=False, item_count=None):
    data = collection.to_dict(include_items=include_items)
    data['can_edit'] = _can_edit_collection(collection)
    if item_count is not None:
        data['item_count'] = int(item_count)
    elif include_items:
        data['item_count'] = len(data.get('items') or [])
    return data


def _item_counts_by_collection_id(collection_ids: list[int]) -> dict[int, int]:
    if not collection_ids:
        return {}
    rows = db.session.execute(
        select(
            GameCollectionItem.collection_id,
            func.count(GameCollectionItem.id),
        )
        .where(GameCollectionItem.collection_id.in_(collection_ids))
        .group_by(GameCollectionItem.collection_id)
    ).all()
    return {collection_id: int(count) for collection_id, count in rows}


@apis_bp.route('/collections', methods=['GET'])
@login_required
def list_collections():
    query = select(GameCollection).order_by(GameCollection.created_at.desc())
    rows = db.session.execute(query).scalars().all()
    visible = [
        c for c in rows
        if c.is_public or c.owner_user_id == current_user.id or is_admin(current_user)
    ]
    counts = _item_counts_by_collection_id([c.id for c in visible])
    return jsonify({
        'collections': [
            _collection_payload(c, item_count=counts.get(c.id, 0))
            for c in visible
        ],
    })


@apis_bp.route('/collections', methods=['POST'])
@login_required
@validate_body(CreateCollectionBody)
def create_collection(body: CreateCollectionBody):
    collection = GameCollection(
        name=body.name[:120],
        description=(body.description or '')[:4000] or None,
        owner_user_id=current_user.id,
        is_public=bool(body.is_public),
        is_system=False,
    )
    db.session.add(collection)
    db.session.commit()
    return jsonify(_collection_payload(collection, item_count=0)), 201


def _editable_collection(collection_uuid: str):
    """Load a collection for a write, or the response that refuses the write.

    Five handlers opened with this identical pair of guards — look up by uuid,
    404 if absent, 403 if the caller may not edit it. Returns
    ``(collection, None)`` on success and ``(None, response)`` otherwise, so a
    handler starts with two lines instead of six and the refusal wording cannot
    drift between them.
    """
    collection = db.session.execute(
        select(GameCollection).filter_by(uuid=collection_uuid)
    ).scalars().first()
    if not collection:
        return None, api_error('Collection not found', code='not_found')
    if not _can_edit_collection(collection):
        return None, api_error('That collection belongs to someone else', code='forbidden')
    return collection, None


def _is_collection_owner_or_admin(collection: GameCollection) -> bool:
    return collection.owner_user_id == current_user.id or is_admin(current_user)


def _filtered_collection_payload(collection: GameCollection):
    """Build detail payload; non-owner viewers only see accessible games."""
    payload = _collection_payload(collection, include_items=True)
    if _is_collection_owner_or_admin(collection):
        return payload
    filtered = [
        item.to_dict()
        for item in collection.items
        if user_can_access_game(current_user, item.game)
    ]
    payload['items'] = filtered
    payload['item_count'] = len(filtered)
    return payload


@apis_bp.route('/collections/<collection_uuid>', methods=['GET'])
@login_required
def get_collection(collection_uuid: str):
    collection = db.session.execute(
        select(GameCollection).filter_by(uuid=collection_uuid)
    ).scalars().first()
    if not collection:
        return api_error('Collection not found', code='not_found')
    if not collection.is_public and not _is_collection_owner_or_admin(collection):
        return api_error('That collection is private', code='forbidden')
    return jsonify(_filtered_collection_payload(collection))


@apis_bp.route('/collections/<collection_uuid>', methods=['PATCH'])
@login_required
def update_collection(collection_uuid: str):
    collection, refusal = _editable_collection(collection_uuid)
    if refusal is not None:
        return refusal
    if collection.is_system:
        return api_error('System collections cannot be edited', code='bad_request')

    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return api_error('A name is required', code='bad_request')
        collection.name = name[:120]
    if 'description' in data:
        raw = data.get('description')
        if raw is None:
            collection.description = None
        else:
            collection.description = (str(raw).strip()[:4000] or None)
    if 'is_public' in data:
        collection.is_public = bool(data.get('is_public'))

    db.session.commit()
    return jsonify(_collection_payload(collection, include_items=True))


@apis_bp.route('/collections/<collection_uuid>', methods=['DELETE'])
@login_required
def delete_collection(collection_uuid: str):
    collection, refusal = _editable_collection(collection_uuid)
    if refusal is not None:
        return refusal
    if collection.is_system:
        return api_error('System collections cannot be deleted', code='bad_request')
    uuid = collection.uuid
    db.session.delete(collection)
    db.session.commit()
    return api_ok({'uuid': uuid})


@apis_bp.route('/collections/<collection_uuid>/items', methods=['POST'])
@login_required
@validate_body(AddCollectionItemBody)
def add_collection_item(collection_uuid: str, body: AddCollectionItemBody):
    collection, refusal = _editable_collection(collection_uuid)
    if refusal is not None:
        return refusal
    game_uuid = body.game_uuid
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        return api_error('Game not found', code='not_found')
    if not user_can_access_game(current_user, game):
        return api_error('You do not have access to that game', code='forbidden')
    existing = db.session.execute(
        select(GameCollectionItem).filter_by(collection_id=collection.id, game_uuid=game_uuid)
    ).scalars().first()
    if existing:
        return jsonify(existing.to_dict())
    position = len(collection.items)
    item = GameCollectionItem(collection_id=collection.id, game_uuid=game_uuid, position=position)
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@apis_bp.route('/collections/<collection_uuid>/items/<game_uuid>', methods=['DELETE'])
@login_required
def remove_collection_item(collection_uuid: str, game_uuid: str):
    collection, refusal = _editable_collection(collection_uuid)
    if refusal is not None:
        return refusal
    item = db.session.execute(
        select(GameCollectionItem).filter_by(
            collection_id=collection.id,
            game_uuid=game_uuid,
        )
    ).scalars().first()
    if not item:
        return api_error('That game is not in the collection', code='not_found')
    db.session.delete(item)
    db.session.commit()
    return api_ok({'game_uuid': game_uuid})


@apis_bp.route('/collections/<collection_uuid>/items/order', methods=['PUT'])
@login_required
@validate_body(ReorderCollectionItemsBody)
def reorder_collection_items(collection_uuid: str, body: ReorderCollectionItemsBody):
    collection, refusal = _editable_collection(collection_uuid)
    if refusal is not None:
        return refusal

    normalized = [str(uuid).strip() for uuid in body.game_uuids if uuid is not None]
    if len(normalized) != len(set(normalized)):
        return api_error('game_uuids must list each collection item exactly once', code='bad_request')
    current_uuids = {item.game_uuid for item in collection.items}
    if set(normalized) != current_uuids:
        return api_error('game_uuids must list each collection item exactly once', code='bad_request')

    by_uuid = {item.game_uuid: item for item in collection.items}
    for position, game_uuid in enumerate(normalized):
        by_uuid[game_uuid].position = position
    db.session.commit()
    db.session.refresh(collection)
    return jsonify(_collection_payload(collection, include_items=True))


@apis_bp.route('/announcements', methods=['GET'])
@login_required
def list_announcements():
    include_drafts = (
        request.args.get('include_drafts') == '1'
        and is_admin(current_user)
    )
    query = select(Announcement).order_by(Announcement.created_at.desc()).limit(50)
    if not include_drafts:
        query = query.filter_by(published=True)
    rows = db.session.execute(query).scalars().all()
    items = [a.to_dict() for a in rows]
    return jsonify({'announcements': items, 'empty': len(items) == 0})


@apis_bp.route('/announcements', methods=['POST'])
@login_required
@validate_body(CreateAnnouncementBody)
def create_announcement(body: CreateAnnouncementBody):
    if not is_admin(current_user):
        return api_error('Admin required', code='forbidden')
    row = Announcement(
        title=body.title[:200],
        body=body.body[:20000],
        published=bool(body.published),
        author_user_id=current_user.id,
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(row.to_dict()), 201


@apis_bp.route('/news/gaming', methods=['GET'])
@login_required
def gaming_news_feed():
    """Best-effort top gaming headlines from public RSS feeds."""
    from flask import current_app

    from oneirodex.utils.gaming_news import fetch_gaming_headlines

    limit = request.args.get('limit', 12, type=int) or 12
    try:
        items = fetch_gaming_headlines(limit=max(1, min(limit, 30)))
    except Exception as exc:
        current_app.logger.warning('gaming news feed failed: %s', exc)
        items = []
    # The configured sites travel with the headlines so the reader can turn
    # one off without first having to receive an article from it — a site that
    # is quiet today would otherwise be invisible and unfilterable.
    from oneirodex.utils.gaming_news import feed_urls, source_name

    sources = sorted({source_name(url) for url in feed_urls()})
    return jsonify({'items': items, 'sources': sources, 'empty': len(items) == 0})


@apis_bp.route('/news/free-games', methods=['GET'])
@login_required
def free_games_feed():
    """Active free / giveaway offers (Wave 18)."""
    from flask import current_app

    from oneirodex.utils.free_games import connected_stores_for_user, list_active_offers

    if not bool(current_app.config.get('ENABLE_FREE_GAMES', True)):
        return jsonify({
            'items': [],
            'enabled': False,
            'connected_stores': [],
            'empty': True,
        })

    store = (request.args.get('store') or '').strip() or None
    limit = request.args.get('limit', 40, type=int) or 40
    try:
        connected = connected_stores_for_user(current_user.id)
        items = list_active_offers(
            store=store,
            limit=max(1, min(limit, 100)),
            connected_stores=connected,
        )
    except Exception as exc:
        current_app.logger.warning('free-games feed failed: %s', exc)
        return jsonify({
            'items': [],
            'enabled': True,
            'connected_stores': [],
            'empty': True,
        })
    return jsonify({
        'items': items,
        'enabled': True,
        'connected_stores': sorted(connected),
        'empty': len(items) == 0,
    })


@apis_bp.route('/news/free-games/<int:offer_id>/claim-assist', methods=['POST'])
@login_required
def free_games_claim_assist(offer_id: int):
    """
    Avenue B: when the store is connected, register the title + Steam live sync.
    Does not silently redeem DRM — member still uses Claim / Open in app (avenue A).
    """
    from flask import current_app
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import FreeGameOffer
    from oneirodex.utils.free_games import claim_assist_for_user

    if not bool(current_app.config.get('ENABLE_FREE_GAMES', True)):
        return api_error('Free games are switched off', code='forbidden')

    offer = db.session.execute(
        select(FreeGameOffer).where(FreeGameOffer.id == offer_id)
    ).scalars().first()
    if offer is None:
        return api_error('Offer not found', code='not_found')

    result = claim_assist_for_user(current_user.id, offer)
    if not result.get('ok'):
        # The helper's failure shape is `{ok: False, error: <sentence>}` and
        # carries nothing else, so nothing is lost re-reporting it as a 400.
        return api_error(
            result.get('error') or 'Ownership assist is not available',
            code='bad_request',
        )
    return api_ok(result)
