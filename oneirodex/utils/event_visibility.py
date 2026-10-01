"""Which bus events one viewer's live stream may carry.

The SSE streams used to send every event to every signed-in member: anyone,
a child included, saw each member's play sessions and the names of games in
libraries they cannot open. The REST presence API already filtered by
friendship and library access; this applies the same rules per event.
"""
from __future__ import annotations

from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, User
from oneirodex.utils.rbac import normalize_role


def event_visible_to(event, viewer_id: int | None) -> bool:
    """True when ``event`` may be sent to the member ``viewer_id``."""
    if viewer_id is None:
        return False
    payload = getattr(event, 'payload', None) or {}
    owner_id = payload.get('user_id')
    game_uuid = payload.get('game_uuid')
    if owner_id is None and not game_uuid:
        return True  # not about a member or a game: scan progress, ops, hello
    viewer = db.session.get(User, viewer_id)
    if viewer is None or not viewer.is_active:
        return False  # a stream opened before the account was disabled gets nothing more
    is_admin = normalize_role(getattr(viewer, 'role', None)) == 'admin'

    if game_uuid:
        from oneirodex.utils.library_acl import user_can_access_game

        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if game is not None and not user_can_access_game(viewer, game):
            return False

    if owner_id is not None and owner_id != viewer_id and getattr(event, 'type', None) != 'activity':
        return is_admin  # one member's downloads and the like: theirs and admins' only
    if getattr(event, 'type', None) == 'activity' and owner_id is not None and owner_id != viewer_id:
        if is_admin:
            return True
        from oneirodex.models import UserPreference
        from oneirodex.utils.presence import accepted_friend_ids

        if owner_id not in accepted_friend_ids(viewer_id):
            return False
        prefs = db.session.execute(
            select(UserPreference).filter_by(user_id=owner_id)
        ).scalars().first()
        if prefs is not None and getattr(prefs, 'share_activity', True) is False:
            return False
    return True
