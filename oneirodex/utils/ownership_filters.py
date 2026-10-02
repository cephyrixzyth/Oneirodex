"""Per-member ownership predicates appended to an already ACL-scoped query.

Absence from a partial register means unrecorded, never proof of non-ownership.
"""
from sqlalchemy import and_, false, select

from oneirodex.models import Game, UserOwnedTitle
from oneirodex.utils.store_capabilities import provider_capabilities

_PROVIDERS = frozenset(p['id'] for p in provider_capabilities())


def apply_ownership_filters(query, args, *, user=None):
    getlist = getattr(args, 'getlist', None)
    raw = getlist('store') if callable(getlist) else [args.get('store', '')]
    stores = {part.strip().lower() for value in raw for part in str(value or '').split(',') if part.strip()}
    state = str(args.get('ownership') or '').strip().lower()
    mode = str(args.get('store_match') or 'any').strip().lower()
    if not stores and not state and mode == 'any':
        return query
    if (stores - _PROVIDERS or mode not in {'any', 'all'}
            or state not in {'', 'owned', 'unrecorded'}
            or not getattr(user, 'is_authenticated', False)):
        return query.filter(false())
    base = select(UserOwnedTitle.id).where(
        UserOwnedTitle.user_id == user.id,
        UserOwnedTitle.matched_game_uuid == Game.uuid,
    ).correlate(Game)
    if stores and mode == 'all':
        recorded = and_(*(base.where(UserOwnedTitle.store == store).exists() for store in sorted(stores)))
    elif stores:
        recorded = base.where(UserOwnedTitle.store.in_(sorted(stores))).exists()
    else:
        recorded = base.exists()
    # For multiple stores, unrecorded means no register entry in ANY selection;
    # it never means merely missing one of the selected stores.
    if state == 'unrecorded':
        recorded = base.where(UserOwnedTitle.store.in_(sorted(stores))).exists() if stores else base.exists()
        return query.filter(~recorded)
    return query.filter(recorded)
