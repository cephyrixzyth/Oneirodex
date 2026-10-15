"""Native FastAPI read APIs for household chat surfaces."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .acquire_status import _login_redirect
from .request_auth import request_auth_context


async def _bounded_form(request: Request, max_body_bytes: int):
    """Parse one bounded multipart form without buffering unbounded uploads."""
    declared = request.headers.get('content-length')
    try:
        if declared is not None and int(declared) > max_body_bytes:
            return None, True
    except ValueError:
        pass

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_body_bytes:
            return None, True
    # Starlette Request.stream() checks this cached body before its consumed
    # flag, so form parsing reuses the bounded bytes instead of reading receive
    # a second time. Files are then spooled and explicitly closed by callers.
    request._body = bytes(body)
    return await request.form(max_files=1, max_fields=8), False


class ChatReadData:
    def channels(self, user):
        from oneirodex.utils.chat import list_channels_for_user

        return list_channels_for_user(user)

    def spaces(self, user):
        from oneirodex.utils.chat_spaces import channels_for_space, spaces_for_user
        from oneirodex.utils.livekit_rtc import voice_room_name

        payload = []
        for space in spaces_for_user(user):
            channels = channels_for_space(user, space)
            rows = []
            for channel in channels:
                row = channel.to_dict()
                if channel.kind == 'voice':
                    row['room'] = voice_room_name(channel.id)
                rows.append(row)
            payload.append({
                **space.to_dict(),
                'channels': [row for row in rows if row.get('kind') == 'channel'],
                'voice_channels': [row for row in rows if row.get('kind') == 'voice'],
            })
        return payload

    def messages(self, user, channel_id: int, *, limit: int, before_id, since_id):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatChannel
        from oneirodex.utils.chat import (
            list_messages, mark_channel_read, user_can_access_channel,
        )

        channel = db.session.get(ChatChannel, channel_id)
        if channel is None or not user_can_access_channel(user, channel):
            return None
        messages = list_messages(
            channel_id, limit=limit, before_id=before_id, since_id=since_id,
            viewer_user_id=user.id,
        )
        if messages:
            mark_channel_read(channel_id, user.id, messages[-1]['id'])
        return {'messages': messages, 'channel': channel.to_dict()}

    def search(self, user, query: str, *, limit: int):
        from oneirodex.utils.chat import search_messages

        return search_messages(user, query, limit=limit)

    def create_channel(self, user, payload: dict):
        from oneirodex.utils.chat import create_household_channel

        channel = create_household_channel(
            user, name=(payload.get('name') or '').strip(),
            slug=(payload.get('slug') or '').strip(),
            is_child_safe=bool(payload.get('is_child_safe', True)),
        )
        result = channel.to_dict()
        result['muted'] = False
        result['unread'] = 0
        return result

    def mute_channel(self, user, channel_id: int, muted: bool):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatChannel
        from oneirodex.utils.chat import set_channel_muted, user_can_access_channel

        channel = db.session.get(ChatChannel, channel_id)
        if channel is None or not user_can_access_channel(user, channel):
            return None
        return set_channel_muted(user, channel, muted)

    def channel_action(self, user, channel_id: int, action: str):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatChannel
        from oneirodex.utils.chat import archive_channel, leave_channel

        channel = db.session.get(ChatChannel, channel_id)
        if channel is None or channel.archived_at is not None:
            return None
        if action == 'archive':
            archive_channel(user, channel)
            return {'channel_id': channel.id, 'archived': True}
        leave_channel(user, channel)
        return {'channel_id': channel.id, 'left': True}

    def open_dm(self, user, payload: dict):
        from sqlalchemy import select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User
        from oneirodex.utils.chat import open_or_create_dm

        other = None
        if payload.get('user_id') is not None:
            try:
                other = db.session.get(User, int(payload['user_id']))
            except (TypeError, ValueError, OverflowError):
                other = None
        elif payload.get('username'):
            other = db.session.execute(
                select(User).where(User.name == str(payload['username']).strip())
            ).scalars().first()
        if not other or not other.state:
            return None
        return open_or_create_dm(user, other).to_dict()

    def post_message(self, user, channel_id: int, payload: dict):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatChannel
        from oneirodex.utils.chat import post_message, user_can_access_channel
        from oneirodex.utils.chat_attachments import attachments_for_messages

        channel = db.session.get(ChatChannel, channel_id)
        if channel is None or not user_can_access_channel(user, channel):
            return None
        parent_raw = payload.get('parent_message_id')
        parent_id = None
        if parent_raw is not None and str(parent_raw).strip() != '':
            try:
                parent_id = int(parent_raw)
            except (TypeError, ValueError):
                raise ValueError('Invalid parent_message_id') from None
        raw_ids = payload.get('attachment_ids') or []
        if raw_ids and not isinstance(raw_ids, list):
            raise ValueError('attachment_ids must be a list')
        try:
            attachment_ids = [int(value) for value in raw_ids] if raw_ids else []
        except (TypeError, ValueError):
            raise ValueError('Invalid attachment_ids') from None
        message = post_message(
            channel, user, payload.get('body') or '', parent_message_id=parent_id,
            attachment_ids=attachment_ids,
        )
        attachments = attachments_for_messages([message.id]).get(message.id, [])
        return message.to_dict(
            author_name=user.name, reactions={}, mine=[], attachments=attachments,
        )

    def toggle_reaction(self, user, message_id: int, emoji: str):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatMessage
        from oneirodex.utils.chat import toggle_reaction

        message = db.session.get(ChatMessage, message_id)
        if message is None:
            return None
        return toggle_reaction(message, user, emoji)

    def attachment(self, user, file_name: str):
        from pathlib import Path

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatMessageAttachment
        from oneirodex.utils.chat import user_can_access_channel
        from oneirodex.utils.chat_attachments import attachments_dir

        row = db.session.execute(
            db.select(ChatMessageAttachment).where(
                ChatMessageAttachment.file_name == file_name
            )
        ).scalars().first()
        if row is None or (
            row.message_id is None and row.uploaded_by_user_id != user.id
        ):
            return None
        from oneirodex.models import ChatChannel

        channel = db.session.get(ChatChannel, row.channel_id)
        if channel is None or not user_can_access_channel(user, channel):
            return None
        root = Path(attachments_dir()).resolve()
        path = (root / row.file_name).resolve()
        if path.parent != root or not path.is_file():
            return None
        return path, row.mime, row.original_name, not row.mime.startswith('image/')

    def space_members(self, user, space_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatSpace
        from oneirodex.utils.chat_spaces import space_member_rows, user_is_space_member

        space = db.session.get(ChatSpace, space_id)
        if space is None or not user_is_space_member(user, space):
            return None
        return space_member_rows(space)

    def space_invites(self, space_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatSpace, ChatSpaceInvite

        space = db.session.get(ChatSpace, space_id)
        if space is None:
            return None
        rows = db.session.execute(
            db.select(ChatSpaceInvite).where(ChatSpaceInvite.space_id == space.id)
        ).scalars().all()
        return [invite.to_dict() for invite in rows]

    def add_space_member(self, space_id: int, user_id: int, role: str | None):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatSpace
        from oneirodex.utils.chat_spaces import add_space_member

        space = db.session.get(ChatSpace, space_id)
        if space is None:
            return None
        member = add_space_member(space, user_id, role=(role or 'member'))
        return {'user_id': member.user_id, 'role': member.role}

    def remove_space_member(self, space_id: int, user_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatSpace
        from oneirodex.utils.chat_spaces import remove_space_member

        space = db.session.get(ChatSpace, space_id)
        if space is None:
            return None
        return remove_space_member(space, user_id)

    def create_space(self, user, payload: dict):
        from oneirodex.utils.chat_spaces import create_space

        space = create_space(
            name=payload.get('name') or '', created_by_user_id=user.id,
            visibility=payload.get('visibility') or 'household',
            description=payload.get('description'),
            is_child_safe=bool(payload.get('is_child_safe', True)),
            slug=payload.get('slug'),
        )
        return space.to_dict()

    def create_space_channel(self, user, space_id: int, payload: dict):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatSpace
        from oneirodex.utils.chat_spaces import create_channel
        from oneirodex.utils.livekit_rtc import voice_room_name

        space = db.session.get(ChatSpace, space_id)
        if space is None or space.archived_at is not None:
            return None
        channel = create_channel(
            space=space, name=payload.get('name') or '',
            kind=(payload.get('kind') or 'channel').strip().lower(),
            created_by_user_id=user.id,
            is_child_safe=bool(payload.get('is_child_safe', True)),
        )
        result = channel.to_dict()
        if channel.kind == 'voice':
            result['room'] = voice_room_name(channel.id)
        return result

    def voice_room(self, user, space_id: int, channel_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatChannel, ChatSpace
        from oneirodex.utils.chat_spaces import user_is_space_member
        from oneirodex.utils.livekit_rtc import voice_room_name
        from oneirodex.utils.role_catalog import normalize_role

        space = db.session.get(ChatSpace, space_id)
        if space is None or not user_is_space_member(user, space):
            return None
        channel = db.session.get(ChatChannel, channel_id)
        if (
            channel is None or channel.space_id != space.id
            or channel.kind != 'voice' or channel.archived_at is not None
            or (normalize_role(getattr(user, 'role', None)) == 'child' and not channel.is_child_safe)
        ):
            return None
        row = channel.to_dict()
        row['room'] = voice_room_name(channel.id)
        return {'room': voice_room_name(channel.id), 'channel': row}

    def create_space_invite(self, space_id: int, user_id: int, expires_at, max_uses):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatSpace
        from oneirodex.utils.chat_spaces import create_space_invite

        space = db.session.get(ChatSpace, space_id)
        if space is None:
            return None
        invite = create_space_invite(
            space=space, created_by_user_id=user_id,
            expires_at=expires_at, max_uses=max_uses,
        )
        return invite.to_dict(include_token=True)

    def revoke_space_invite(self, invite_id: int) -> bool:
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatSpaceInvite
        from oneirodex.utils.chat_spaces import revoke_space_invite

        invite = db.session.get(ChatSpaceInvite, invite_id)
        if invite is None:
            return False
        revoke_space_invite(invite)
        return True

    def join_space(self, user, token: str):
        from oneirodex.utils.chat_spaces import redeem_space_invite

        space, error = redeem_space_invite(token, user)
        return (space.to_dict(), None) if not error else (None, error)

    def upload_emoji(self, user, *, slug: str, label: str, file, upload_folder: str | None):
        from oneirodex.utils.custom_emoji import upload_custom_emoji

        return upload_custom_emoji(
            slug=slug, label=label, file=file, uploader=user,
            upload_folder=upload_folder,
        ).to_dict()

    def delete_emoji(self, slug: str, *, upload_folder: str | None):
        from oneirodex.utils.custom_emoji import delete_custom_emoji

        return delete_custom_emoji(slug, upload_folder=upload_folder)

    def upload_attachment(self, user, channel_id: int, *, file, config):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatChannel
        from oneirodex.utils.chat import ensure_channel_membership, user_can_access_channel
        from oneirodex.utils.chat_attachments import (
            MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS_PER_MESSAGE,
            upload_attachment as persist_attachment,
        )

        channel = db.session.get(ChatChannel, channel_id)
        if channel is None or not user_can_access_channel(user, channel):
            return None
        ensure_channel_membership(channel, user)
        row = persist_attachment(
            channel=channel, user=user, file=file,
            upload_folder=config.get('UPLOAD_FOLDER'),
            storage_max_bytes=config.get('CHAT_ATTACHMENT_STORAGE_MAX_BYTES'),
            storage_max_files=config.get('CHAT_ATTACHMENT_STORAGE_MAX_FILES'),
        )
        return {
            'attachment': row.to_dict(),
            'limits': {
                'max_bytes': MAX_ATTACHMENT_BYTES,
                'max_per_message': MAX_ATTACHMENTS_PER_MESSAGE,
                'max_total_bytes': config.get('CHAT_ATTACHMENT_STORAGE_MAX_BYTES'),
                'max_total_files': config.get('CHAT_ATTACHMENT_STORAGE_MAX_FILES'),
            },
        }


def _admin_auth_error(flask_app, request, login_manager, auth):
    from oneirodex.utils.role_catalog import normalize_role

    if normalize_role(getattr(auth.user, 'role', None)) != 'admin':
        from .oidc_status import _login_redirect as admin_login_redirect

        return admin_login_redirect(
            flask_app, request, login_manager, auth,
            message='You must be an admin to access this page.',
            category='danger', include_next=False,
        )
    if auth.token is not None and not auth.has_scope('admin'):
        from oneirodex.utils.api_contract import api_error_payload

        body, status = api_error_payload(
            'This token does not have the admin scope', code='forbidden',
        )
        return JSONResponse(body, status_code=status)
    return None


def create_chat_reads_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ChatReadData()

    @router.api_route('/api/chat/channels', methods=['GET', 'HEAD'])
    def chat_channels(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                try:
                    channels = data.channels(auth.user)
                    response = JSONResponse({'channels': channels, 'rooms': channels})
                except Exception:  # noqa: BLE001 — keep the legacy read failure private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not load chat channels', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/chat/channels')
    async def chat_channels_create(request: Request):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                import json

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    created = data.create_channel(auth.user, payload)
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload({
                        'channel': created, 'room': created,
                    }), status_code=201)
                except PermissionError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='forbidden')
                    response = JSONResponse(body, status_code=status)
                except ValueError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not create chat channel', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/channels/{channel_id}/mute')
    async def chat_channel_mute(request: Request, channel_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                import json

                from pydantic import ValidationError
                from oneirodex.schemas.chat import MuteChannelBody
                from oneirodex.utils.validation import format_validation_errors

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    body = MuteChannelBody.model_validate(payload)
                except ValidationError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    detail = format_validation_errors(exc)
                    result, status = api_error_payload(
                        'Invalid request.', code='unprocessable', detail=detail,
                    )
                    response = JSONResponse(result, status_code=status)
                else:
                    try:
                        muted = data.mute_channel(auth.user, channel_id, body.muted)
                    except PermissionError:
                        muted = None
                    if muted is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        result, status = api_error_payload('Not found', code='not_found')
                        response = JSONResponse(result, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({
                            'channel_id': channel_id, 'muted': muted,
                        }))
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    def channel_action(request: Request, channel_id: int, action: str):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                try:
                    payload = data.channel_action(auth.user, channel_id, action)
                except PermissionError as exc:
                    code = 'not_found' if action == 'leave' else 'forbidden'
                    message = 'Not found' if action == 'leave' else str(exc)
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(message, code=code)
                    response = JSONResponse(body, status_code=status)
                except ValueError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not update chat channel', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
                else:
                    if payload is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('Not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload(payload))
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/channels/{channel_id}/archive')
    def chat_channel_archive(channel_id: int, request: Request):
        return channel_action(request, channel_id, 'archive')

    @router.post('/api/chat/channels/{channel_id}/leave')
    def chat_channel_leave(channel_id: int, request: Request):
        return channel_action(request, channel_id, 'leave')

    @router.post('/api/chat/dm')
    async def chat_open_dm(request: Request):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                import json

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    channel = data.open_dm(auth.user, payload)
                    if channel is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('User not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({'channel': channel}))
                except ValueError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not open chat conversation', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/emoji')
    async def chat_emoji_upload(request: Request):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
            if response is None:
                from io import BytesIO

                from starlette.datastructures import UploadFile as StarletteUploadFile
                from werkzeug.datastructures import FileStorage

                from oneirodex.utils.custom_emoji import MAX_UPLOAD_BYTES

                form, too_large = await _bounded_form(request, MAX_UPLOAD_BYTES + 64 * 1024)
                if too_large:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Request body too large', code='payload_too_large',
                    )
                    response = JSONResponse(body, status_code=status)
                else:
                    try:
                        upload = form.get('file') or form.get('image')
                        file = None
                        if isinstance(upload, StarletteUploadFile):
                            raw = await upload.read(MAX_UPLOAD_BYTES + 1)
                            file = FileStorage(
                                stream=BytesIO(raw), filename=upload.filename,
                                content_type=upload.content_type,
                            )
                        slug = str(form.get('slug') or '')
                        label = str(form.get('label') or '')
                    finally:
                        await form.close()
                    try:
                        emoji = data.upload_emoji(
                            auth.user, slug=slug, label=label, file=file,
                            upload_folder=flask_app.config.get('UPLOAD_FOLDER'),
                        )
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(
                            api_ok_payload({'emoji': emoji}), status_code=201,
                        )
                    except ValueError as exc:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(body, status_code=status)
                    except Exception:  # noqa: BLE001 — keep storage detail private
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Could not upload chat emoji', code='internal',
                        )
                        response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/channels/{channel_id}/attachments')
    async def chat_attachment_upload(request: Request, channel_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            if response is None:
                from io import BytesIO

                from starlette.datastructures import UploadFile as StarletteUploadFile
                from werkzeug.datastructures import FileStorage

                from oneirodex.utils.chat_attachments import MAX_ATTACHMENT_BYTES

                form, too_large = await _bounded_form(
                    request, MAX_ATTACHMENT_BYTES + 64 * 1024,
                )
                if too_large:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Request body too large', code='payload_too_large',
                    )
                    response = JSONResponse(body, status_code=status)
                else:
                    try:
                        upload = form.get('file') or form.get('attachment')
                        file = None
                        if isinstance(upload, StarletteUploadFile):
                            raw = await upload.read(MAX_ATTACHMENT_BYTES + 1)
                            file = FileStorage(
                                stream=BytesIO(raw), filename=upload.filename,
                                content_type=upload.content_type,
                            )
                    finally:
                        await form.close()
                    try:
                        result = data.upload_attachment(
                            auth.user, channel_id, file=file, config=flask_app.config,
                        )
                        if result is None:
                            from oneirodex.utils.api_contract import api_error_payload

                            body, status = api_error_payload('Not found', code='not_found')
                            response = JSONResponse(body, status_code=status)
                        else:
                            from oneirodex.utils.api_contract import api_ok_payload

                            response = JSONResponse(api_ok_payload(result), status_code=201)
                    except PermissionError as exc:
                        from oneirodex.runtime_native.db_session import native_db as db
                        from oneirodex.utils.api_contract import api_error_payload

                        db.session.rollback()
                        body, status = api_error_payload(str(exc), code='forbidden')
                        response = JSONResponse(body, status_code=status)
                    except ValueError as exc:
                        from oneirodex.runtime_native.db_session import native_db as db
                        from oneirodex.utils.api_contract import api_error_payload

                        db.session.rollback()
                        body, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(body, status_code=status)
                    except Exception:  # noqa: BLE001 — keep storage detail private
                        from oneirodex.runtime_native.db_session import native_db as db
                        from oneirodex.utils.api_contract import api_error_payload

                        db.session.rollback()
                        body, status = api_error_payload(
                            'Could not upload chat attachment', code='internal',
                        )
                        response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.delete('/api/chat/emoji/{slug}')
    def chat_emoji_delete(request: Request, slug: str):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
            if response is None:
                try:
                    if not data.delete_emoji(
                        slug, upload_folder=flask_app.config.get('UPLOAD_FOLDER'),
                    ):
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('Not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload())
                except ValueError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep storage detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not delete chat emoji', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/channels/{channel_id}/messages')
    async def chat_message_post(request: Request, channel_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                import json

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    message = data.post_message(auth.user, channel_id, payload)
                    if message is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('Not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(
                            api_ok_payload({'message': message}), status_code=201,
                        )
                except (ValueError, PermissionError) as exc:
                    from oneirodex.runtime_native.db_session import native_db as db
                    from oneirodex.utils.api_contract import api_error_payload

                    db.session.rollback()
                    code = 'forbidden' if isinstance(exc, PermissionError) else 'bad_request'
                    body, status = api_error_payload(str(exc), code=code)
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    from oneirodex.runtime_native.db_session import native_db as db
                    from oneirodex.utils.api_contract import api_error_payload

                    db.session.rollback()
                    body, status = api_error_payload(
                        'Could not post chat message', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/messages/{message_id}/reactions')
    async def chat_message_reaction(request: Request, message_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                import json

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    result = data.toggle_reaction(
                        auth.user, message_id, payload.get('emoji') or '',
                    )
                    if result is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('Not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload(result))
                except PermissionError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='forbidden')
                    response = JSONResponse(body, status_code=status)
                except ValueError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not update message reaction', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.api_route('/api/chat/attachments/{file_name}', methods=['GET', 'HEAD'])
    def chat_attachment(request: Request, file_name: str):
        from starlette.responses import FileResponse

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                try:
                    attachment = data.attachment(auth.user, file_name)
                    if attachment is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('Not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        path, mime, original_name, download = attachment
                        response = FileResponse(
                            path, media_type=mime, filename=original_name,
                            content_disposition_type='attachment' if download else 'inline',
                        )
                        response.headers['Cache-Control'] = 'private, max-age=3600'
                except Exception:  # noqa: BLE001 — keep storage detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not load chat attachment', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/spaces')
    async def chat_space_create(request: Request):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
            if response is None:
                import json

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                visibility = payload.get('visibility') or 'household'
                if not isinstance(visibility, str) or visibility.strip().lower() not in {
                    'household', 'invite',
                }:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'visibility must be household or invite', code='bad_request',
                    )
                    response = JSONResponse(body, status_code=status)
                else:
                    payload['visibility'] = visibility.strip().lower()
                    try:
                        space = data.create_space(auth.user, payload)
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(
                            api_ok_payload({'space': space}), status_code=201,
                        )
                    except ValueError as exc:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(body, status_code=status)
                    except Exception:  # noqa: BLE001 — keep persistence detail private
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Could not create chat space', code='internal',
                        )
                        response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/spaces/{space_id}/channels')
    async def chat_space_channel_create(request: Request, space_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
            if response is None:
                import json

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    channel = data.create_space_channel(auth.user, space_id, payload)
                    if channel is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('Space not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(
                            api_ok_payload({'channel': channel}), status_code=201,
                        )
                except ValueError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not create space channel', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.api_route('/api/chat/spaces/{space_id}/members', methods=['GET', 'HEAD'])
    def chat_space_members(request: Request, space_id: int):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                try:
                    members = data.space_members(auth.user, space_id)
                    if members is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('Space not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({'members': members}))
                except Exception:  # noqa: BLE001 — keep the legacy read failure private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not load space members', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/chat/spaces/{space_id}/members')
    async def chat_space_member_add(request: Request, space_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
            if response is None:
                import json

                from pydantic import ValidationError
                from oneirodex.schemas.chat_spaces import AddSpaceMemberBody
                from oneirodex.utils.validation import format_validation_errors

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    body = AddSpaceMemberBody.model_validate(payload)
                except ValidationError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    result, status = api_error_payload(
                        'Invalid request.', code='unprocessable',
                        detail=format_validation_errors(exc),
                    )
                    response = JSONResponse(result, status_code=status)
                else:
                    member = data.add_space_member(space_id, body.user_id, body.role)
                    if member is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        result, status = api_error_payload('Space not found', code='not_found')
                        response = JSONResponse(result, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload(member))
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.delete('/api/chat/spaces/{space_id}/members/{user_id}')
    def chat_space_member_remove(request: Request, space_id: int, user_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
            if response is None:
                try:
                    removed = data.remove_space_member(space_id, user_id)
                    if removed is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload('Space not found', code='not_found')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({'removed': removed}))
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not remove space member', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.api_route('/api/chat/spaces/{space_id}/invites', methods=['GET', 'HEAD'])
    def chat_space_invites(request: Request, space_id: int):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
                if response is None:
                    try:
                        invites = data.space_invites(space_id)
                        if invites is None:
                            from oneirodex.utils.api_contract import api_error_payload

                            body, status = api_error_payload('Space not found', code='not_found')
                            response = JSONResponse(body, status_code=status)
                        else:
                            from oneirodex.utils.api_contract import api_ok_payload

                            response = JSONResponse(api_ok_payload({'invites': invites}))
                    except Exception:  # noqa: BLE001 — keep the legacy read failure private
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Could not load space invites', code='internal',
                        )
                        response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/api/chat/spaces/{space_id}/invites')
    async def chat_space_invite_create(request: Request, space_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
            if response is None:
                import json
                from datetime import datetime, timedelta, timezone

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                expires_at = None
                raw_expiry = payload.get('expires_at')
                if raw_expiry:
                    try:
                        expires_at = datetime.fromisoformat(str(raw_expiry).replace('Z', '+00:00'))
                    except ValueError:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'expires_at must be an ISO timestamp', code='bad_request',
                        )
                        response = JSONResponse(body, status_code=status)
                elif payload.get('expires_in_hours'):
                    try:
                        hours = float(payload['expires_in_hours'])
                    except (TypeError, ValueError):
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'expires_in_hours must be a number', code='bad_request',
                        )
                        response = JSONResponse(body, status_code=status)
                    else:
                        expires_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)
                if response is None:
                    try:
                        invite = data.create_space_invite(
                            space_id, auth.user.id, expires_at, payload.get('max_uses'),
                        )
                        if invite is None:
                            from oneirodex.utils.api_contract import api_error_payload

                            body, status = api_error_payload('Space not found', code='not_found')
                            response = JSONResponse(body, status_code=status)
                        else:
                            from oneirodex.utils.api_contract import api_ok_payload

                            response = JSONResponse(
                                api_ok_payload({'invite': invite}), status_code=201,
                            )
                    except ValueError as exc:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(str(exc), code='bad_request')
                        response = JSONResponse(body, status_code=status)
                    except Exception:  # noqa: BLE001 — keep persistence detail private
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Could not create space invite', code='internal',
                        )
                        response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/spaces/invites/{invite_id}/revoke')
    def chat_space_invite_revoke(request: Request, invite_id: int):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                response = _admin_auth_error(flask_app, request, login_manager, auth)
            if response is None:
                if not data.revoke_space_invite(invite_id):
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload('Invite not found', code='not_found')
                    response = JSONResponse(body, status_code=status)
                else:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload())
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/api/chat/spaces/join')
    async def chat_space_join(request: Request):
        from .csrf_compat import csrf_error_response

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            response = csrf_error_response(request, auth.session_data, flask_app.config)
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and auth.token is not None and not auth.has_scope('write:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: write:social', code='forbidden',
                    detail={'required_scope': 'write:social'},
                )
                response = JSONResponse(body, status_code=status)
            elif response is None:
                import json

                try:
                    payload = json.loads(await request.body() or b'{}')
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    space, error = data.join_space(auth.user, payload.get('token') or '')
                    if error:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(error, code='bad_request')
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload({'space': space}))
                except Exception:  # noqa: BLE001 — keep persistence detail private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not join chat space', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.api_route(
        '/api/chat/spaces/{space_id}/voice/{channel_id}/room', methods=['GET', 'HEAD'],
    )
    def chat_space_voice_room(request: Request, space_id: int, channel_id: int):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                try:
                    payload = data.voice_room(auth.user, space_id, channel_id)
                    if payload is None:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Voice channel not found', code='not_found',
                        )
                        response = JSONResponse(body, status_code=status)
                    else:
                        from oneirodex.utils.api_contract import api_ok_payload

                        response = JSONResponse(api_ok_payload(payload))
                except Exception:  # noqa: BLE001 — keep the legacy read failure private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not load voice channel', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/chat/spaces', methods=['GET', 'HEAD'])
    def chat_spaces(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                try:
                    from oneirodex.utils.api_contract import api_ok_payload

                    response = JSONResponse(api_ok_payload({'spaces': data.spaces(auth.user)}))
                except Exception:  # noqa: BLE001 — keep the legacy read failure private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not load chat spaces', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/chat/channels/{channel_id}/messages', methods=['GET', 'HEAD'])
    def chat_messages(request: Request, channel_id: int):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                try:
                    from oneirodex.utils.chat import parse_chat_limit

                    limit = parse_chat_limit(
                        request.query_params.get('limit'), default=50, maximum=100,
                    )
                except ValueError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                else:
                    before = request.query_params.get('before')
                    since = request.query_params.get('since')
                    before_id = int(before) if before and str(before).isdigit() else None
                    since_id = int(since) if since and str(since).isdigit() else None
                    try:
                        payload = data.messages(
                            auth.user, channel_id, limit=limit,
                            before_id=before_id, since_id=since_id,
                        )
                        if payload is None:
                            from oneirodex.utils.api_contract import api_error_payload

                            body, status = api_error_payload('Not found', code='not_found')
                            response = JSONResponse(body, status_code=status)
                        else:
                            response = JSONResponse(payload)
                    except Exception:  # noqa: BLE001 — keep the legacy read failure private
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Could not load chat messages', code='internal',
                        )
                        response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/chat/search', methods=['GET', 'HEAD'])
    def chat_search(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                query = (request.query_params.get('q') or '').strip()
                try:
                    from oneirodex.utils.chat import parse_chat_limit

                    limit = parse_chat_limit(
                        request.query_params.get('limit'), default=20, maximum=50,
                    )
                    response = JSONResponse({
                        'results': data.search(auth.user, query, limit=limit), 'q': query,
                    })
                except ValueError as exc:
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(str(exc), code='bad_request')
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep the legacy read failure private
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not search chat messages', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


def mount_chat_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_chat_reads_router(flask_app, **kwargs))
    return app
