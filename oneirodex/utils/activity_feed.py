"""Activity / now-playing helpers from play sessions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, PlaySession, User
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.presence import accepted_friend_ids


def list_recent_activity(
    *,
    limit: int = 25,
    active_within_minutes: int = 15,
    viewer: User | None = None,
    friends_only: bool = False,
) -> list[dict[str, Any]]:
    """Return recent play sessions for an activity feed (no private paths).

    When ``viewer`` is set, sessions for games the viewer cannot access are omitted.
    When ``friends_only`` is set, only the viewer and accepted friends appear.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    friend_ids: set[int] | None = None
    if friends_only and viewer is not None:
        friend_ids = accepted_friend_ids(viewer.id)
        friend_ids.add(viewer.id)
    rows = list(
        db.session.execute(
            select(PlaySession)
            .where(PlaySession.started_at >= cutoff)
            .order_by(PlaySession.started_at.desc())
            .limit(max(1, min(limit * 3, 300))),
        ).scalars().all(),
    )
    active_cutoff = datetime.now(timezone.utc) - timedelta(minutes=active_within_minutes)
    out: list[dict[str, Any]] = []
    for session in rows:
        if friend_ids is not None and session.user_id not in friend_ids:
            continue
        game = db.session.execute(
            select(Game).filter_by(uuid=session.game_uuid),
        ).scalars().first() if getattr(session, 'game_uuid', None) else None
        if viewer is not None and (not game or not user_can_access_game(viewer, game)):
            continue
        user = db.session.get(User, session.user_id) if getattr(session, 'user_id', None) else None
        ended = getattr(session, 'ended_at', None)
        last = getattr(session, 'last_heartbeat_at', None) or ended or session.started_at
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        is_active = ended is None and last is not None and last >= active_cutoff
        out.append({
            'session_id': session.id,
            'game_uuid': session.game_uuid,
            'game_name': getattr(game, 'name', None) or 'Unknown game',
            'user': getattr(user, 'name', None) or 'player',
            'user_id': getattr(user, 'id', None) or session.user_id,
            'started_at': session.started_at.isoformat() if session.started_at else None,
            'ended_at': ended.isoformat() if ended else None,
            'client': getattr(session, 'client', None) or 'unknown',
            'is_playing': is_active,
        })
        if len(out) >= max(1, min(limit, 100)):
            break
    return out


def list_now_playing(
    *,
    active_within_minutes: int = 15,
    viewer: User | None = None,
    friends_only: bool = False,
) -> list[dict[str, Any]]:
    return [
        row
        for row in list_recent_activity(
            limit=50,
            active_within_minutes=active_within_minutes,
            viewer=viewer,
            friends_only=friends_only,
        )
        if row['is_playing']
    ]
