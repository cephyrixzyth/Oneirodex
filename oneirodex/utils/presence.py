"""Unified household presence — online / away / in-game (Wave 14a)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import ClientDevice, Game, PlaySession, User, UserFriendship
from oneirodex.utils.client_presence import CLIENT_HEARTBEAT_TTL_SECONDS
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.playtime import HEARTBEAT_TTL_SECONDS as PLAY_TTL

AWAY_AFTER_SECONDS = 180


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def accepted_friend_ids(user_id: int) -> set[int]:
    rows = (
        db.session.execute(
            select(UserFriendship).where(
                or_(
                    UserFriendship.user_id == user_id,
                    UserFriendship.friend_user_id == user_id,
                ),
                UserFriendship.status == 'accepted',
            )
        )
        .scalars()
        .all()
    )
    out: set[int] = set()
    for row in rows:
        other = row.friend_user_id if row.user_id == user_id else row.user_id
        out.add(other)
    return out


def presence_for_user(user_id: int, *, viewer: User | None = None) -> dict[str, Any]:
    """Derive presence from companion/web heartbeat + active play sessions."""
    now = _utcnow()
    play_cutoff = now - timedelta(seconds=PLAY_TTL)
    device_cutoff = now - timedelta(seconds=CLIENT_HEARTBEAT_TTL_SECONDS)

    session = (
        db.session.execute(
            select(PlaySession)
            .where(
                PlaySession.user_id == user_id,
                PlaySession.status == 'active',
                PlaySession.last_heartbeat_at >= play_cutoff,
            )
            .order_by(PlaySession.last_heartbeat_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )

    game_uuid = None
    game_name = None
    if session is not None:
        game_uuid = session.game_uuid
        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if viewer is not None and game is not None and not user_can_access_game(viewer, game):
            game_uuid = None
            game_name = None
            session = None
        else:
            game_name = getattr(game, 'name', None) or 'Unknown game'

    device = (
        db.session.execute(
            select(ClientDevice)
            .where(
                ClientDevice.user_id == user_id,
                ClientDevice.last_seen_at >= device_cutoff,
            )
            .order_by(ClientDevice.last_seen_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    last_seen = _aware(getattr(device, 'last_seen_at', None)) if device else None

    if session is not None and game_uuid:
        status = 'in-game'
    elif device is not None and last_seen is not None:
        age = (now - last_seen).total_seconds()
        status = 'away' if age >= AWAY_AFTER_SECONDS else 'online'
    else:
        status = 'offline'

    return {
        'user_id': user_id,
        'status': status,
        'game_uuid': game_uuid,
        'game_name': game_name,
        'last_seen_at': last_seen.isoformat() if last_seen else None,
    }


def list_friend_presence(viewer: User) -> list[dict[str, Any]]:
    friend_ids = accepted_friend_ids(viewer.id)
    out = []
    for fid in sorted(friend_ids):
        user = db.session.get(User, fid)
        if not user or not user.state:
            continue
        row = presence_for_user(fid, viewer=viewer)
        row['name'] = user.name
        out.append(row)
    return out
