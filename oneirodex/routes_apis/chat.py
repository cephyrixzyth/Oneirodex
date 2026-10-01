"""Chat channels + DMs API (Wave 15) + attachments (Wave 16)."""

from __future__ import annotations

from flask import jsonify, request

from oneirodex.utils.api_response import api_error, api_ok
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import ChatChannel, ChatMessage, User
from oneirodex.utils.auth import admin_required
from oneirodex.utils.chat import (
    ALLOWED_REACTIONS,
    archive_channel,
    create_household_channel,
    ensure_channel_membership,
    leave_channel,
    list_channels_for_user,
    list_messages,
    mark_channel_read,
    open_or_create_dm,
    post_message,
    search_messages,
    set_channel_muted,
    toggle_reaction,
    user_can_access_channel,
)
from oneirodex.utils.chat_attachments import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_MESSAGE,
    attachments_for_messages,
    upload_attachment,
)
from oneirodex.utils.custom_emoji import (
    MAX_CUSTOM_EMOJI,
    delete_custom_emoji,
    list_custom_emoji,
    upload_custom_emoji,
)
from oneirodex.schemas.chat import MuteChannelBody
from oneirodex.utils.validation import validate_body

from . import apis_bp


def _message_payload(msg: ChatMessage, *, author_name: str | None = None) -> dict:
    att = attachments_for_messages([msg.id]).get(msg.id, [])
    return msg.to_dict(
        author_name=author_name,
        reactions={},
        mine=[],
        attachments=att,
    )


def _refuse_not_found():
    """The opaque 404 every chat lookup answers with.

    Deliberately not a 403: telling someone a channel exists but is not theirs
    confirms it exists. Ten call sites shared this wording for that reason, so
    it is stated once here rather than ten times.
    """
    return api_error('Not found', code='not_found')


def _visible_channel(channel_id: int):
    """Load a channel the caller may see, or the refusal. ``(ch, refusal)``."""
    ch = db.session.get(ChatChannel, channel_id)
    if not ch or not user_can_access_channel(current_user, ch):
        return None, _refuse_not_found()
    return ch, None


def _active_channel(channel_id: int):
    """Load a channel that is not archived, or the refusal. ``(ch, refusal)``."""
    ch = db.session.get(ChatChannel, channel_id)
    if not ch or ch.archived_at is not None:
        return None, _refuse_not_found()
    return ch, None


@apis_bp.route('/chat/channels', methods=['GET'])
@login_required
def chat_channels_list():
    channels = list_channels_for_user(current_user)
    # `rooms` alias for slide-out dock (same payloads)
    return jsonify({'channels': channels, 'rooms': channels})


@apis_bp.route('/chat/channels', methods=['POST'])
@login_required
def chat_channels_create():
    data = request.get_json(silent=True) or {}
    try:
        ch = create_household_channel(
            current_user,
            name=(data.get('name') or '').strip(),
            slug=(data.get('slug') or '').strip(),
            is_child_safe=bool(data.get('is_child_safe', True)),
        )
    except PermissionError as exc:
        return api_error(str(exc), code='forbidden')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    payload = ch.to_dict()
    payload['muted'] = False
    payload['unread'] = 0
    return api_ok({'channel': payload, 'room': payload}, status=201)


@apis_bp.route('/chat/channels/<int:channel_id>/archive', methods=['POST'])
@login_required
def chat_channel_archive(channel_id: int):
    ch, refusal = _active_channel(channel_id)
    if refusal is not None:
        return refusal
    try:
        archive_channel(current_user, ch)
    except PermissionError as exc:
        return api_error(str(exc), code='forbidden')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'channel_id': ch.id, 'archived': True})


@apis_bp.route('/chat/channels/<int:channel_id>/leave', methods=['POST'])
@login_required
def chat_channel_leave(channel_id: int):
    ch, refusal = _active_channel(channel_id)
    if refusal is not None:
        return refusal
    try:
        leave_channel(current_user, ch)
    except PermissionError:
        return _refuse_not_found()
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'channel_id': ch.id, 'left': True})


@apis_bp.route('/chat/dm', methods=['POST'])
@login_required
def chat_open_dm():
    data = request.get_json(silent=True) or {}
    other = None
    if data.get('user_id') is not None:
        try:
            other = db.session.get(User, int(data['user_id']))
        except (TypeError, ValueError):
            other = None
    elif data.get('username'):
        other = db.session.execute(
            select(User).where(User.name == str(data['username']).strip()),
        ).scalars().first()
    if not other or not other.state:
        return api_error('User not found', code='not_found')
    try:
        ch = open_or_create_dm(current_user, other)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'channel': ch.to_dict()})


@apis_bp.route('/chat/channels/<int:channel_id>/mute', methods=['POST'])
@login_required
@validate_body(MuteChannelBody)
def chat_channel_mute(channel_id: int, body: MuteChannelBody):
    ch, refusal = _visible_channel(channel_id)
    if refusal is not None:
        return refusal
    try:
        muted = set_channel_muted(current_user, ch, body.muted)
    except PermissionError:
        return _refuse_not_found()
    return api_ok({'channel_id': ch.id, 'muted': muted})


@apis_bp.route('/chat/channels/<int:channel_id>/messages', methods=['GET'])
@login_required
def chat_messages_list(channel_id: int):
    ch, refusal = _visible_channel(channel_id)
    if refusal is not None:
        return refusal
    limit = min(100, max(1, int(request.args.get('limit') or 50)))
    before = request.args.get('before')
    since = request.args.get('since')
    before_id = int(before) if before and str(before).isdigit() else None
    since_id = int(since) if since and str(since).isdigit() else None
    messages = list_messages(
        channel_id,
        limit=limit,
        before_id=before_id,
        since_id=since_id,
        viewer_user_id=current_user.id,
    )
    if messages:
        mark_channel_read(channel_id, current_user.id, messages[-1]['id'])
    return jsonify({'messages': messages, 'channel': ch.to_dict()})


@apis_bp.route('/chat/channels/<int:channel_id>/attachments', methods=['POST'])
@login_required
def chat_attachment_upload(channel_id: int):
    """Upload a pending chat attachment (multipart). Bind via attachment_ids on send."""
    ch, refusal = _visible_channel(channel_id)
    if refusal is not None:
        return refusal
    ensure_channel_membership(ch, current_user)
    file = request.files.get('file') or request.files.get('attachment')
    try:
        row = upload_attachment(channel=ch, user=current_user, file=file)
    except PermissionError as exc:
        return api_error(str(exc), code='forbidden')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({
        'attachment': row.to_dict(),
        'limits': {
            'max_bytes': MAX_ATTACHMENT_BYTES,
            'max_per_message': MAX_ATTACHMENTS_PER_MESSAGE,
        },
    }, status=201)


@apis_bp.route('/chat/attachments/<file_name>', methods=['GET'])
@login_required
def chat_attachment_file(file_name: str):
    """One chat attachment, for someone who can read its channel.

    Attachments used to be plain static files, readable by anyone with the
    link. A pending one (not yet sent) is visible to its uploader only.
    """
    import os

    from flask import send_from_directory

    from oneirodex.models import ChatMessageAttachment
    from oneirodex.utils.chat_attachments import attachments_dir

    row = db.session.execute(
        select(ChatMessageAttachment).where(ChatMessageAttachment.file_name == file_name)
    ).scalars().first()
    if row is None or (row.message_id is None and row.uploaded_by_user_id != current_user.id):
        return _refuse_not_found()
    _ch, refusal = _visible_channel(row.channel_id)
    if refusal is not None:
        return refusal
    folder = attachments_dir()
    if not os.path.isfile(os.path.join(folder, row.file_name)):
        return _refuse_not_found()
    resp = send_from_directory(
        folder, row.file_name, mimetype=row.mime, download_name=row.original_name,
        as_attachment=not row.mime.startswith('image/'),
    )
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


@apis_bp.route('/chat/channels/<int:channel_id>/messages', methods=['POST'])
@login_required
def chat_messages_post(channel_id: int):
    ch, refusal = _visible_channel(channel_id)
    if refusal is not None:
        return refusal
    data = request.get_json(silent=True) or {}
    parent_raw = data.get('parent_message_id')
    parent_id = None
    if parent_raw is not None and str(parent_raw).strip() != '':
        try:
            parent_id = int(parent_raw)
        except (TypeError, ValueError):
            return api_error('Invalid parent_message_id', code='bad_request')
    raw_ids = data.get('attachment_ids') or []
    if raw_ids and not isinstance(raw_ids, list):
        return api_error('attachment_ids must be a list', code='bad_request')
    try:
        attachment_ids = [int(x) for x in raw_ids] if raw_ids else []
    except (TypeError, ValueError):
        return api_error('Invalid attachment_ids', code='bad_request')
    try:
        msg = post_message(
            ch,
            current_user,
            data.get('body') or '',
            parent_message_id=parent_id,
            attachment_ids=attachment_ids,
        )
    except (ValueError, PermissionError) as exc:
        db.session.rollback()
        code = 'forbidden' if isinstance(exc, PermissionError) else 'bad_request'
        return api_error(str(exc), code=code)
    return api_ok({
        'message': _message_payload(msg, author_name=current_user.name),
    }, status=201)


@apis_bp.route('/chat/messages/<int:message_id>/reactions', methods=['POST'])
@login_required
def chat_message_reaction_toggle(message_id: int):
    msg = db.session.get(ChatMessage, message_id)
    if not msg:
        return _refuse_not_found()
    data = request.get_json(silent=True) or {}
    try:
        result = toggle_reaction(msg, current_user, data.get('emoji') or '')
    except PermissionError as exc:
        return api_error(str(exc), code='forbidden')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({**result})


@apis_bp.route('/chat/emoji', methods=['GET'])
@login_required
def chat_emoji_list():
    custom = list_custom_emoji()
    return jsonify({
        'fixed': sorted(ALLOWED_REACTIONS),
        'custom': custom,
        'max_custom': MAX_CUSTOM_EMOJI,
    })


@apis_bp.route('/chat/emoji', methods=['POST'])
@login_required
@admin_required
def chat_emoji_upload():
    slug = request.form.get('slug') or ''
    label = request.form.get('label') or ''
    file = request.files.get('file') or request.files.get('image')
    try:
        row = upload_custom_emoji(
            slug=slug,
            label=label,
            file=file,
            uploader=current_user,
        )
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_ok({'emoji': row.to_dict()}, status=201)


@apis_bp.route('/chat/emoji/<slug>', methods=['DELETE'])
@login_required
@admin_required
def chat_emoji_delete(slug: str):
    if not delete_custom_emoji(slug):
        return _refuse_not_found()
    return api_ok()


@apis_bp.route('/chat/search', methods=['GET'])
@login_required
def chat_search():
    q = (request.args.get('q') or '').strip()
    limit = min(50, max(1, int(request.args.get('limit') or 20)))
    try:
        results = search_messages(current_user, q, limit=limit)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return jsonify({'results': results, 'q': q})
