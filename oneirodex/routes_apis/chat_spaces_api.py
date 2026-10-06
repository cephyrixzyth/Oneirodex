"""Spaces API — servers with text + voice channels (W23-SOCIAL-1/2).

Space creation is **admin only** (locked product decision); membership,
listing and invite redemption are member-facing. Non-members get 404 rather
than 403 so an invite space's existence is not enumerable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import request

from oneirodex.utils.api_response import api_error, api_ok
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import ChatChannel, ChatSpace, ChatSpaceInvite
from oneirodex.utils.auth import admin_required
from oneirodex.utils.chat_spaces import (
    SPACE_VISIBILITIES,
    add_space_member,
    channels_for_space,
    create_channel,
    create_space,
    create_space_invite,
    redeem_space_invite,
    remove_space_member,
    revoke_space_invite,
    space_member_rows,
    spaces_for_user,
    user_is_space_member,
)
from oneirodex.utils.livekit_rtc import voice_room_name
from oneirodex.utils.rbac import normalize_role
from oneirodex.schemas.chat_spaces import AddSpaceMemberBody
from oneirodex.utils.validation import validate_body

from oneirodex.utils.api_tokens import require_api_scope

from . import apis_bp


def _visible_space_or_none(space_id: int) -> ChatSpace | None:
    space = db.session.get(ChatSpace, space_id)
    if space is None or not user_is_space_member(current_user, space):
        return None
    return space


def _channel_payload(channel) -> dict:
    row = channel.to_dict()
    if channel.kind == 'voice':
        row['room'] = voice_room_name(channel.id)
    return row


def _refuse_missing_space(space, *, require_active: bool = False):
    """404 for a space the caller cannot act on, or ``None`` when they can.

    Six handlers spelled this out. `require_active` covers the channel-create
    case, which also rejects an archived space — the same refusal, so keeping it
    here stops the two wordings drifting apart.
    """
    if space is None or (require_active and space.archived_at is not None):
        return api_error('Space not found', code='not_found')
    return None


@apis_bp.route('/chat/spaces', methods=['GET'])
@login_required
@require_api_scope('read:social')
def chat_spaces_list():
    """Spaces the caller may see, each with its text and voice channels."""
    payload = []
    for space in spaces_for_user(current_user):
        channels = channels_for_space(current_user, space)
        payload.append({
            **space.to_dict(),
            'channels': [_channel_payload(c) for c in channels if c.kind == 'channel'],
            'voice_channels': [_channel_payload(c) for c in channels if c.kind == 'voice'],
        })
    return api_ok({'spaces': payload})


@apis_bp.route('/chat/spaces', methods=['POST'])
@login_required
@require_api_scope('write:social')
@admin_required
def chat_spaces_create():
    data = request.get_json(silent=True) or {}
    visibility = (data.get('visibility') or 'household').strip().lower()
    if visibility not in SPACE_VISIBILITIES:
        return api_error('visibility must be household or invite', code='bad_request')
    try:
        space = create_space(
            name=data.get('name') or '',
            created_by_user_id=current_user.id,
            visibility=visibility,
            description=data.get('description'),
            is_child_safe=bool(data.get('is_child_safe', True)),
            slug=data.get('slug'),
        )
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'space': space.to_dict()}, status=201)


@apis_bp.route('/chat/spaces/<int:space_id>/channels', methods=['POST'])
@login_required
@require_api_scope('write:social')
@admin_required
def chat_space_channel_create(space_id: int):
    space = db.session.get(ChatSpace, space_id)
    refusal = _refuse_missing_space(space, require_active=True)
    if refusal is not None:
        return refusal
    data = request.get_json(silent=True) or {}
    try:
        channel = create_channel(
            space=space,
            name=data.get('name') or '',
            kind=(data.get('kind') or 'channel').strip().lower(),
            created_by_user_id=current_user.id,
            is_child_safe=bool(data.get('is_child_safe', True)),
        )
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'channel': _channel_payload(channel)}, status=201)


@apis_bp.route('/chat/spaces/<int:space_id>/members', methods=['GET'])
@login_required
@require_api_scope('read:social')
def chat_space_members(space_id: int):
    space = _visible_space_or_none(space_id)
    refusal = _refuse_missing_space(space)
    if refusal is not None:
        return refusal
    return api_ok({'members': space_member_rows(space)})


@apis_bp.route('/chat/spaces/<int:space_id>/members', methods=['POST'])
@login_required
@require_api_scope('write:social')
@admin_required
@validate_body(AddSpaceMemberBody)
def chat_space_member_add(space_id: int, body: AddSpaceMemberBody):
    space = db.session.get(ChatSpace, space_id)
    refusal = _refuse_missing_space(space)
    if refusal is not None:
        return refusal
    member = add_space_member(space, body.user_id, role=(body.role or 'member'))
    return api_ok({'user_id': member.user_id, 'role': member.role})


@apis_bp.route('/chat/spaces/<int:space_id>/members/<int:user_id>', methods=['DELETE'])
@login_required
@require_api_scope('write:social')
@admin_required
def chat_space_member_remove(space_id: int, user_id: int):
    space = db.session.get(ChatSpace, space_id)
    refusal = _refuse_missing_space(space)
    if refusal is not None:
        return refusal
    removed = remove_space_member(space, user_id)
    return api_ok({'removed': removed})


@apis_bp.route('/chat/spaces/<int:space_id>/invites', methods=['GET'])
@login_required
@require_api_scope('read:social')
@admin_required
def chat_space_invites_list(space_id: int):
    space = db.session.get(ChatSpace, space_id)
    refusal = _refuse_missing_space(space)
    if refusal is not None:
        return refusal
    rows = db.session.execute(
        db.select(ChatSpaceInvite).where(ChatSpaceInvite.space_id == space.id)
    ).scalars().all()
    return api_ok({'invites': [i.to_dict() for i in rows]})


@apis_bp.route('/chat/spaces/<int:space_id>/invites', methods=['POST'])
@login_required
@require_api_scope('write:social')
@admin_required
def chat_space_invite_create(space_id: int):
    space = db.session.get(ChatSpace, space_id)
    refusal = _refuse_missing_space(space)
    if refusal is not None:
        return refusal

    data = request.get_json(silent=True) or {}
    expires_at = None
    raw_expiry = data.get('expires_at')
    if raw_expiry:
        try:
            expires_at = datetime.fromisoformat(str(raw_expiry).replace('Z', '+00:00'))
        except ValueError:
            return api_error('expires_at must be an ISO timestamp', code='bad_request')
    elif data.get('expires_in_hours'):
        try:
            hours = float(data['expires_in_hours'])
        except (TypeError, ValueError):
            return api_error('expires_in_hours must be a number', code='bad_request')
        expires_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)

    invite = create_space_invite(
        space=space,
        created_by_user_id=current_user.id,
        expires_at=expires_at,
        max_uses=data.get('max_uses'),
    )
    # Token is returned once, on creation — same stance as member API tokens.
    return api_ok({'invite': invite.to_dict(include_token=True)}, status=201)


@apis_bp.route('/chat/spaces/invites/<int:invite_id>/revoke', methods=['POST'])
@login_required
@require_api_scope('write:social')
@admin_required
def chat_space_invite_revoke(invite_id: int):
    invite = db.session.get(ChatSpaceInvite, invite_id)
    if invite is None:
        return api_error('Invite not found', code='not_found')
    revoke_space_invite(invite)
    return api_ok()


@apis_bp.route('/chat/spaces/join', methods=['POST'])
@login_required
@require_api_scope('write:social')
def chat_space_join():
    """Redeem an invite token. Child accounts still cannot enter unsafe spaces."""
    data = request.get_json(silent=True) or {}
    space, error = redeem_space_invite(data.get('token') or '', current_user)
    if error:
        return api_error(error, code='bad_request')
    return api_ok({'space': space.to_dict()})


@apis_bp.route('/chat/spaces/<int:space_id>/voice/<int:channel_id>/room', methods=['GET'])
@login_required
@require_api_scope('read:social')
def chat_space_voice_room(space_id: int, channel_id: int):
    """Resolve the canonical room id for a voice channel.

    The client never invents room names — it asks here, then passes the result
    to ``/api/rtc/token``, which re-checks membership independently.
    """
    space = _visible_space_or_none(space_id)
    refusal = _refuse_missing_space(space)
    if refusal is not None:
        return refusal

    channel = db.session.get(ChatChannel, channel_id)
    if (
        channel is None
        or channel.space_id != space.id
        or channel.kind != 'voice'
        or channel.archived_at is not None
    ):
        return api_error('Voice channel not found', code='not_found')
    if normalize_role(getattr(current_user, 'role', None)) == 'child' and not channel.is_child_safe:
        return api_error('Voice channel not found', code='not_found')

    return api_ok({
        'room': voice_room_name(channel.id),
        'channel': _channel_payload(channel),
    })
