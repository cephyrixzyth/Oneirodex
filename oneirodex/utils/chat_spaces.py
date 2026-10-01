"""Spaces ("servers") holding text + voice channels (W23-SOCIAL-1).

Membership is the single source of truth for who may read a space channel and
who may join its voice room. Two flavours:

``household``
    Every non-child user is a member implicitly — no row required. This keeps
    the default family case zero-admin, matching how the flat channels behaved
    before spaces existed.
``invite``
    Membership requires an explicit ``ChatSpaceMember`` row, obtained via an
    invite token. Nothing is implicit.

Child safety is checked on the space **and** the channel — a child needs both.

Native first-party model. Not Discord, no bridging, no bots.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import delete, select

from oneirodex import db
from oneirodex.models import (
    ChatChannel,
    ChatChannelMember,
    ChatSpace,
    ChatSpaceInvite,
    ChatSpaceMember,
    User,
)
from oneirodex.utils.rbac import normalize_role

HOUSEHOLD_SLUG = 'household'
SPACE_VISIBILITIES = frozenset({'household', 'invite'})
SPACE_ROLES = frozenset({'owner', 'moderator', 'member'})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def ensure_household_space() -> ChatSpace:
    """Get (or create) the default household space that adopts legacy channels."""
    space = db.session.execute(
        select(ChatSpace).where(ChatSpace.slug == HOUSEHOLD_SLUG)
    ).scalars().first()
    if space:
        return space
    space = ChatSpace(
        name='Household',
        slug=HOUSEHOLD_SLUG,
        description='Default space for household channels.',
        visibility='household',
        is_child_safe=True,
        display_order=0,
    )
    db.session.add(space)
    db.session.commit()
    return space


def get_space_member(space_id: int, user_id: int) -> ChatSpaceMember | None:
    return db.session.execute(
        select(ChatSpaceMember).where(
            ChatSpaceMember.space_id == space_id,
            ChatSpaceMember.user_id == user_id,
        )
    ).scalars().first()


def user_is_space_member(user, space: ChatSpace | None) -> bool:
    """True when ``user`` may see ``space`` at all.

    Household spaces are open to every non-child user; invite spaces need a row.
    Children additionally require the space to be child-safe — checked here so
    no caller can forget it.
    """
    if space is None or getattr(user, 'id', None) is None:
        return False
    if space.archived_at is not None:
        return False

    role = normalize_role(getattr(user, 'role', None))
    is_child = role == 'child'
    if is_child and not space.is_child_safe:
        return False

    if space.visibility == 'household':
        return True
    return get_space_member(space.id, user.id) is not None


def user_can_access_channel(user, channel: ChatChannel | None) -> bool:
    """Space channels resolve through space membership; DMs are handled by callers.

    Returns False for DMs — their access is per-thread ``ChatChannelMember``
    membership, which ``oneirodex.utils.chat`` owns.
    """
    if channel is None or channel.space_id is None:
        return False
    role = normalize_role(getattr(user, 'role', None))
    if role == 'child' and not channel.is_child_safe:
        return False
    space = db.session.get(ChatSpace, channel.space_id)
    return user_is_space_member(user, space)


def spaces_for_user(user) -> list[ChatSpace]:
    """Every non-archived space the user may see, in display order."""
    rows = db.session.execute(
        select(ChatSpace)
        .where(ChatSpace.archived_at.is_(None))
        .order_by(ChatSpace.display_order.asc(), ChatSpace.id.asc())
    ).scalars().all()
    return [space for space in rows if user_is_space_member(user, space)]


def channels_for_space(user, space: ChatSpace, *, kind: str | None = None) -> list[ChatChannel]:
    """Channels in a space the user may see. ``kind`` filters channel|voice."""
    if not user_is_space_member(user, space):
        return []
    query = (
        select(ChatChannel)
        .where(
            ChatChannel.space_id == space.id,
            ChatChannel.archived_at.is_(None),
        )
        .order_by(ChatChannel.display_order.asc(), ChatChannel.id.asc())
    )
    if kind:
        query = query.where(ChatChannel.kind == kind)
    rows = db.session.execute(query).scalars().all()
    role = normalize_role(getattr(user, 'role', None))
    if role == 'child':
        rows = [c for c in rows if c.is_child_safe]
    return rows


def add_space_member(space: ChatSpace, user_id: int, *, role: str = 'member') -> ChatSpaceMember:
    """Idempotent — returns the existing row when already a member."""
    existing = get_space_member(space.id, user_id)
    if existing:
        return existing
    member = ChatSpaceMember(
        space_id=space.id,
        user_id=user_id,
        role=role if role in SPACE_ROLES else 'member',
    )
    db.session.add(member)
    db.session.commit()
    return member


def remove_space_member(space: ChatSpace, user_id: int) -> bool:
    member = get_space_member(space.id, user_id)
    if not member:
        return False
    db.session.delete(member)
    # Their channel memberships in this space go too, so nothing keyed on a
    # membership row (mentions, unread counts) reaches them afterwards.
    channel_ids = select(ChatChannel.id).where(ChatChannel.space_id == space.id)
    db.session.execute(
        delete(ChatChannelMember).where(
            ChatChannelMember.user_id == user_id,
            ChatChannelMember.channel_id.in_(channel_ids),
        )
    )
    db.session.commit()
    return True


def create_space(
    *,
    name: str,
    created_by_user_id: int | None = None,
    visibility: str = 'household',
    description: str | None = None,
    is_child_safe: bool = True,
    slug: str | None = None,
) -> ChatSpace:
    """Admin-only at the route layer; this helper does not itself check role."""
    label = (name or '').strip()
    if not label:
        raise ValueError('Space name is required')
    if visibility not in SPACE_VISIBILITIES:
        raise ValueError('visibility must be household or invite')

    space = ChatSpace(
        name=label[:120],
        slug=(slug or '').strip()[:64] or None,
        description=(description or '').strip()[:500] or None,
        visibility=visibility,
        is_child_safe=bool(is_child_safe),
        created_by_user_id=created_by_user_id,
    )
    db.session.add(space)
    db.session.commit()

    # The creator owns it — meaningful for invite spaces, harmless for household.
    if created_by_user_id:
        add_space_member(space, created_by_user_id, role='owner')
    return space


def create_channel(
    *,
    space: ChatSpace,
    name: str,
    kind: str = 'channel',
    created_by_user_id: int | None = None,
    is_child_safe: bool = True,
) -> ChatChannel:
    """Create a text (``channel``) or ``voice`` channel inside a space."""
    label = (name or '').strip()
    if not label:
        raise ValueError('Channel name is required')
    if kind not in ('channel', 'voice'):
        raise ValueError('kind must be channel or voice')

    channel = ChatChannel(
        kind=kind,
        name=label[:120],
        space_id=space.id,
        is_child_safe=bool(is_child_safe),
        created_by_user_id=created_by_user_id,
    )
    db.session.add(channel)
    db.session.commit()
    return channel


# ---------------------------------------------------------------- invites


def create_space_invite(
    *,
    space: ChatSpace,
    created_by_user_id: int | None = None,
    expires_at: datetime | None = None,
    max_uses: int | None = None,
) -> ChatSpaceInvite:
    invite = ChatSpaceInvite(
        space_id=space.id,
        token=secrets.token_urlsafe(32),
        created_by_user_id=created_by_user_id,
        expires_at=expires_at,
        max_uses=max_uses if (max_uses or 0) > 0 else None,
    )
    db.session.add(invite)
    db.session.commit()
    return invite


def invite_is_usable(invite: ChatSpaceInvite | None) -> bool:
    if invite is None or invite.revoked_at is not None:
        return False
    expires = _aware(invite.expires_at)
    if expires and _now() > expires:
        return False
    if invite.max_uses is not None and (invite.uses or 0) >= invite.max_uses:
        return False
    return True


def redeem_space_invite(token: str, user) -> tuple[ChatSpace | None, str | None]:
    """Join the invite's space. Returns ``(space, error)`` — never raises for
    ordinary bad-token cases so routes can answer without leaking which part failed.
    """
    key = (token or '').strip()
    if not key:
        return None, 'Invite token is required'

    invite = db.session.execute(
        select(ChatSpaceInvite).where(ChatSpaceInvite.token == key)
    ).scalars().first()
    if not invite_is_usable(invite):
        return None, 'This invite is no longer valid'

    space = db.session.get(ChatSpace, invite.space_id)
    if space is None or space.archived_at is not None:
        return None, 'This invite is no longer valid'

    # A child still cannot enter a space that is not child-safe.
    if normalize_role(getattr(user, 'role', None)) == 'child' and not space.is_child_safe:
        return None, 'This space is not available for this account'

    already = get_space_member(space.id, user.id)
    if not already:
        db.session.add(ChatSpaceMember(space_id=space.id, user_id=user.id, role='member'))
    invite.uses = (invite.uses or 0) + 1
    db.session.commit()
    return space, None


def revoke_space_invite(invite: ChatSpaceInvite) -> None:
    invite.revoked_at = _now()
    db.session.commit()


def space_member_rows(space: ChatSpace) -> list[dict]:
    """Roster for the space settings UI — implicit household members included."""
    if space.visibility == 'household':
        users = db.session.execute(select(User)).scalars().all()
        explicit = {m.user_id: m for m in db.session.execute(
            select(ChatSpaceMember).where(ChatSpaceMember.space_id == space.id)
        ).scalars().all()}
        rows = []
        for user in users:
            if normalize_role(getattr(user, 'role', None)) == 'child' and not space.is_child_safe:
                continue
            member = explicit.get(user.id)
            rows.append({
                'user_id': user.id,
                'name': user.name,
                'role': member.role if member else 'member',
                'implicit': member is None,
            })
        return rows

    members = db.session.execute(
        select(ChatSpaceMember).where(ChatSpaceMember.space_id == space.id)
    ).scalars().all()
    rows = []
    for member in members:
        user = db.session.get(User, member.user_id)
        if user is None:
            continue
        rows.append({
            'user_id': user.id,
            'name': user.name,
            'role': member.role,
            'implicit': False,
        })
    return rows
