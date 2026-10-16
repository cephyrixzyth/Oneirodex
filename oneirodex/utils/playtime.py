"""Play session lifecycle helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, PlaySession, User, UserGameProgress
from oneirodex.utils.ambient_lighting import notify_play_session_started, notify_play_session_stopped
from oneirodex.utils.event_bus import event_bus
from oneirodex.utils.library_acl import user_can_access_game

HEARTBEAT_TTL_SECONDS = 120


def _utcnow():
    return datetime.now(timezone.utc)


def start_session(
    user_id: int, game_uuid: str, client: str | None = None, *, config=None,
) -> PlaySession:
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        raise ValueError('Game not found')
    user = db.session.get(User, user_id)
    if not user or not user_can_access_game(user, game):
        raise PermissionError('Forbidden')

    # End any stale active sessions for this user+game
    active = db.session.execute(
        select(PlaySession).filter_by(user_id=user_id, game_uuid=game_uuid, status='active')
    ).scalars().all()
    for session in active:
        end_session(session, orphan=True, config=config)

    now = _utcnow()
    session = PlaySession(
        user_id=user_id,
        game_uuid=game_uuid,
        started_at=now,
        last_heartbeat_at=now,
        client=(client or 'web')[:64],
        status='active',
        duration_seconds=0,
    )
    db.session.add(session)
    db.session.commit()
    try:
        event_bus.publish(
            'activity',
            action='started',
            session_id=session.id,
            user_id=user_id,
            game_uuid=game_uuid,
            game_name=getattr(game, 'name', None),
        )
    except Exception:
        pass
    notify_play_session_started(user, game, config=config)
    return session


def heartbeat_session(session: PlaySession) -> PlaySession:
    if session.status != 'active':
        raise ValueError('Session is not active')
    now = _utcnow()
    started = session.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    session.last_heartbeat_at = now
    session.duration_seconds = max(0, int((now - started).total_seconds()))
    db.session.commit()
    return session


def end_session(session: PlaySession, *, orphan: bool = False, config=None) -> PlaySession:
    if session.status != 'active':
        return session
    now = _utcnow()
    started = session.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    last = session.last_heartbeat_at or started
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    # Cap at last heartbeat to avoid counting long disconnected gaps
    end_at = min(now, last + timedelta(seconds=HEARTBEAT_TTL_SECONDS))
    session.ended_at = end_at
    session.duration_seconds = max(0, int((end_at - started).total_seconds()))
    session.status = 'orphaned' if orphan else 'ended'
    _accumulate_progress(session)
    db.session.commit()
    try:
        event_bus.publish(
            'activity',
            action='ended',
            session_id=session.id,
            user_id=session.user_id,
            game_uuid=session.game_uuid,
            orphan=orphan,
        )
    except Exception:
        pass
    notify_play_session_stopped(user_id=session.user_id, config=config)
    return session


def _accumulate_progress(session: PlaySession) -> None:
    row = db.session.execute(
        select(UserGameProgress).filter_by(user_id=session.user_id, game_uuid=session.game_uuid)
    ).scalars().first()
    if not row:
        row = UserGameProgress(
            user_id=session.user_id,
            game_uuid=session.game_uuid,
            total_seconds=0,
            session_count=0,
        )
        db.session.add(row)
    row.total_seconds = int(row.total_seconds or 0) + int(session.duration_seconds or 0)
    row.session_count = int(row.session_count or 0) + 1
    row.last_played_at = session.ended_at or _utcnow()


def compute_duration_seconds(started_at: datetime, ended_at: datetime) -> int:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    return max(0, int((ended_at - started_at).total_seconds()))
