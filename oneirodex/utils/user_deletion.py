"""Shared account-deletion relation handling for Flask and native routes."""
from __future__ import annotations

import re

from sqlalchemy import delete, or_, select, update


def anonymize_user_audit_events(session, user) -> None:
    """Keep useful audit history while removing direct identifiers for a user."""
    from oneirodex.models import SystemEvents

    identifiers = [value for value in (user.name, user.email, user.user_id) if value]
    predicates = [SystemEvents.audit_user == user.id]
    predicates.extend(
        SystemEvents.event_text.contains(value, autoescape=True)
        for value in identifiers
    )
    events = session.execute(
        select(SystemEvents).where(or_(*predicates)).with_for_update()
    ).scalars()
    for event in events:
        text = event.event_text
        for value in identifiers:
            text = re.sub(re.escape(value), '[deleted account]', text, flags=re.IGNORECASE)
        event.event_text = text
        if event.audit_user == user.id:
            event.audit_user = None


def delete_user_owned_rows(session, user) -> None:
    """Delete private rows and anonymize references to retained audit records."""
    from oneirodex.models import (
        DownloadRequest,
        DuplicateFixLog,
        InviteToken,
        Newsletter,
        UserAttractModeSettings,
        user_favorites,
        user_game_status,
    )

    # These tables have no ORM ownership cascade or database ON DELETE action.
    session.execute(delete(user_favorites).where(user_favorites.c.user_id == user.id))
    session.execute(delete(user_game_status).where(user_game_status.c.user_id == user.id))
    session.execute(delete(DownloadRequest).where(DownloadRequest.user_id == user.id))
    session.execute(delete(Newsletter).where(Newsletter.sender_id == user.id))
    session.execute(delete(InviteToken).where(InviteToken.creator_user_id == user.user_id))
    session.execute(
        update(InviteToken).where(InviteToken.used_by == user.user_id).values(used_by=None)
    )
    session.execute(
        delete(UserAttractModeSettings).where(
            UserAttractModeSettings.user_id == user.user_id
        )
    )
    session.execute(
        update(DuplicateFixLog)
        .where(DuplicateFixLog.actor_user_id == user.id)
        .values(actor_user_id=None)
    )
