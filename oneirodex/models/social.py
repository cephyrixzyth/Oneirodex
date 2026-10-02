"""Social domain: friendships, the in-app notification centre, and the native
chat spaces / channels / messages / reactions."""
from datetime import datetime, timezone

from oneirodex import db
from oneirodex.models._base import JSONEncodedDict

class UserFriendship(db.Model):
    """Lite social graph — pending / accepted friendships (Wave 13)."""

    __tablename__ = 'user_friendships'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'friend_user_id', name='uq_user_friendship'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    friend_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    status = db.Column(db.String(16), default='pending', nullable=False)  # pending | accepted | blocked
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('friendships_sent', lazy='dynamic'))
    friend = db.relationship(
        'User',
        foreign_keys=[friend_user_id],
        backref=db.backref('friendships_received', lazy='dynamic'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'friend_user_id': self.friend_user_id,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class UserNotification(db.Model):
    """In-app notification center (Wave 14c)."""

    __tablename__ = 'user_notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    kind = db.Column(db.String(32), nullable=False, default='info')
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.String(500), nullable=True)
    link = db.Column(db.String(512), nullable=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    payload = db.Column(JSONEncodedDict, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'title': self.title,
            'body': self.body,
            'link': self.link,
            'actor_user_id': self.actor_user_id,
            'payload': self.payload or {},
            'read_at': self.read_at.isoformat() if self.read_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'unread': self.read_at is None,
        }

class ChatSpace(db.Model):
    """A space ("server") holding text + voice channels (W23-SOCIAL-1).

    ``visibility='household'`` auto-joins every non-child user; ``'invite'``
    requires an explicit ChatSpaceMember row. Admin-created only.
    Native first-party model — not Discord, no bridging.
    """

    __tablename__ = 'chat_spaces'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=True, unique=True)
    description = db.Column(db.String(500), nullable=True)
    # household = everyone (non-child) is a member; invite = explicit rows only
    visibility = db.Column(db.String(16), nullable=False, default='household')
    is_child_safe = db.Column(db.Boolean, default=True, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'description': self.description,
            'visibility': self.visibility,
            'is_child_safe': bool(self.is_child_safe),
            'display_order': self.display_order or 0,
            'created_by_user_id': self.created_by_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'archived': self.archived_at is not None,
        }

class ChatSpaceMember(db.Model):
    __tablename__ = 'chat_space_members'
    __table_args__ = (
        db.UniqueConstraint('space_id', 'user_id', name='uq_chat_space_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    space_id = db.Column(db.Integer, db.ForeignKey('chat_spaces.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False, default='member')  # owner | moderator | member
    muted = db.Column(db.Boolean, default=False, nullable=False)
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

class ChatSpaceInvite(db.Model):
    """Token invite into an ``invite``-visibility space."""

    __tablename__ = 'chat_space_invites'

    id = db.Column(db.Integer, primary_key=True)
    space_id = db.Column(db.Integer, db.ForeignKey('chat_spaces.id', ondelete='CASCADE'), nullable=False, index=True)
    token = db.Column(db.String(128), nullable=False, unique=True, index=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    max_uses = db.Column(db.Integer, nullable=True)
    uses = db.Column(db.Integer, default=0, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self, *, include_token: bool = False):
        row = {
            'id': self.id,
            'space_id': self.space_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'max_uses': self.max_uses,
            'uses': self.uses or 0,
            'revoked': self.revoked_at is not None,
        }
        if include_token:
            row['token'] = self.token
        return row

class ChatChannel(db.Model):
    """Text or voice channel in a space, or a 1:1 DM thread (Wave 15 · W23-SOCIAL-1)."""

    __tablename__ = 'chat_channels'

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(16), nullable=False, default='channel')  # channel | dm | voice
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(64), nullable=True, unique=True)
    # DMs carry no space; space channels are access-gated by space membership.
    space_id = db.Column(
        db.Integer,
        db.ForeignKey('chat_spaces.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    display_order = db.Column(db.Integer, default=0, nullable=False)
    is_child_safe = db.Column(db.Boolean, default=True, nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        kind = self.kind
        return {
            'id': self.id,
            'kind': kind,
            # Slide-out alias — same as kind (channel | dm | voice)
            'type': kind,
            'name': self.name,
            'slug': self.slug,
            'space_id': self.space_id,
            'display_order': self.display_order or 0,
            'is_child_safe': bool(self.is_child_safe),
            'created_by_user_id': self.created_by_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'archived': self.archived_at is not None,
            'archived_at': self.archived_at.isoformat() if self.archived_at else None,
        }

class ChatChannelMember(db.Model):
    __tablename__ = 'chat_channel_members'
    __table_args__ = (
        db.UniqueConstraint('channel_id', 'user_id', name='uq_chat_channel_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('chat_channels.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    last_read_message_id = db.Column(db.Integer, nullable=True)
    muted = db.Column(db.Boolean, default=False, nullable=False)
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('chat_channels.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    parent_message_id = db.Column(
        db.Integer,
        db.ForeignKey('chat_messages.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(
        self,
        *,
        author_name: str | None = None,
        reactions: dict | None = None,
        mine: list | None = None,
        attachments: list | None = None,
    ):
        payload = {
            'id': self.id,
            'channel_id': self.channel_id,
            'user_id': self.user_id,
            'user': author_name or 'member',
            'body': self.body,
            'parent_message_id': self.parent_message_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reactions': reactions or {},
            'mine': mine or [],
            'attachments': attachments if attachments is not None else [],
        }
        return payload

class ChatMessageAttachment(db.Model):
    """File/image attachment for a household chat message (Wave 16 chat)."""

    __tablename__ = 'chat_message_attachments'

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(
        db.Integer,
        db.ForeignKey('chat_channels.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    message_id = db.Column(
        db.Integer,
        db.ForeignKey('chat_messages.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    uploaded_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    file_name = db.Column(db.String(120), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime = db.Column(db.String(128), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def public_url(self) -> str:
        # Served by an authenticated route that checks the channel, never as a
        # static file (routes_apis/chat.py chat_attachment_file).
        return f'/api/chat/attachments/{self.file_name}'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'url': self.public_url(),
            'mime': self.mime,
            'name': self.original_name,
            'size': self.size_bytes,
        }

class ChatMessageReaction(db.Model):
    """Emoji reaction on a chat message (Wave 17)."""

    __tablename__ = 'chat_message_reactions'
    __table_args__ = (
        db.UniqueConstraint('message_id', 'user_id', 'emoji', name='uq_chat_message_reaction'),
    )

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(
        db.Integer,
        db.ForeignKey('chat_messages.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    emoji = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

class CustomEmoji(db.Model):
    """Household custom reaction emoji (Wave 17b) — admin upload capped."""

    __tablename__ = 'custom_emoji'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(24), nullable=False, unique=True)
    label = db.Column(db.String(64), nullable=False)
    file_name = db.Column(db.String(80), nullable=False)
    uploaded_by_user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def reaction_key(self) -> str:
        return f':{self.slug}:'

    def public_url(self) -> str:
        return f'/static/library/chat-emoji/{self.file_name}'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'slug': self.slug,
            'label': self.label,
            'emoji': self.reaction_key(),
            'url': self.public_url(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


__all__ = [
    "UserFriendship",
    "UserNotification",
    "ChatSpace",
    "ChatSpaceMember",
    "ChatSpaceInvite",
    "ChatChannel",
    "ChatChannelMember",
    "ChatMessage",
    "ChatMessageAttachment",
    "ChatMessageReaction",
    "CustomEmoji",
]
