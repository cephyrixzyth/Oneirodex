"""LiveKit RTC token mint + room ACL (Wave 16)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from oneirodex.utils.role_catalog import normalize_role
from oneirodex.utils.runtime_config import get_runtime_config


def livekit_enabled(*, config=None) -> bool:
    try:
        app_config = config if config is not None else get_runtime_config()
        if app_config is None:
            raise RuntimeError('Runtime configuration is unavailable')

        return bool(app_config.get('ENABLE_LIVEKIT', True))
    except RuntimeError:
        return os.getenv('ENABLE_LIVEKIT', 'true').lower() in ('1', 'true', 'yes')


def livekit_config() -> dict[str, str]:
    return {
        'url': (os.getenv('LIVEKIT_URL') or '').strip(),
        'api_key': (os.getenv('LIVEKIT_API_KEY') or '').strip(),
        'api_secret': (os.getenv('LIVEKIT_API_SECRET') or '').strip(),
    }


def normalize_room_name(raw: str) -> str:
    """Opaque household room id — no game titles in SFU metadata by default."""
    cleaned = ''.join(ch if ch.isalnum() or ch in '-_:' else '-' for ch in (raw or '').strip())[:96]
    return cleaned or 'lobby'


def voice_room_name(channel_id: int) -> str:
    """Canonical room id for a voice channel. Callers never pass free text."""
    return f'voice:{int(channel_id)}'


HOUSEHOLD_LOBBY = 'household:lobby'
_PARTY_PREFIX = 'household:party:'
_VOICE_PREFIX = 'voice:'


def user_may_join_room(user, room: str) -> bool:
    """Resolve a room name to something the user demonstrably has access to.

    Previously this only kept children out of rooms *named* "adult"/"admin",
    which meant any authenticated user could mint a token for any room string —
    and party rooms are keyed on game UUIDs that are visible in details URLs.
    That was obscurity, not enforcement.

    Every recognised room now resolves to a real access check, and **anything
    unrecognised is denied**.
    """
    if getattr(user, 'id', None) is None:
        return False

    role = normalize_role(getattr(user, 'role', None))
    name = (room or '').strip()
    lowered = name.lower()

    # Voice channel — membership of the owning space decides.
    if lowered.startswith(_VOICE_PREFIX):
        raw_id = name[len(_VOICE_PREFIX):]
        if not raw_id.isdigit():
            return False
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import ChatChannel
        from oneirodex.utils.chat_spaces import user_can_access_channel

        channel = db.session.get(ChatChannel, int(raw_id))
        if channel is None or channel.kind != 'voice' or channel.archived_at is not None:
            return False
        return user_can_access_channel(user, channel)

    # Game party — you may join if you may see the game.
    if lowered.startswith(_PARTY_PREFIX):
        game_uuid = name[len(_PARTY_PREFIX):].strip()
        if not game_uuid:
            return False
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game
        from oneirodex.utils.library_acl import user_can_access_game
        from sqlalchemy import select

        game = db.session.execute(
            select(Game).filter_by(uuid=game_uuid)
        ).scalars().first()
        if game is None:
            return False
        return bool(user_can_access_game(user, game))

    # The one intentionally household-wide room.
    #
    # Children were excluded outright, which read oddly against "household-wide"
    # and gave households no way to include them. It is a setting now, defaulting
    # to the exclusion that already shipped so no install changes behaviour on
    # upgrade. Every other room stays exactly as strict as before.
    if lowered == HOUSEHOLD_LOBBY:
        if role != 'child':
            return True
        return children_allowed_in_lobby()

    return False


def children_allowed_in_lobby() -> bool:
    """Household setting: may `child` accounts join the voice lobby?

    Defaults to False, and stays False if the settings row cannot be read — a
    parental control that fails open is not a parental control.
    """
    try:
        from oneirodex.utils.global_settings import global_settings_row

        settings = global_settings_row()
        return bool(getattr(settings, 'allow_children_in_household_lobby', False))
    except Exception:  # noqa: BLE001 — no app/db context, or column not migrated yet
        return False


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def mint_livekit_token(
    *,
    identity: str,
    name: str,
    room: str,
    ttl_seconds: int = 3600,
    can_publish: bool = True,
    can_subscribe: bool = True,
    can_publish_data: bool = True,
) -> str:
    """HS256 JWT compatible with LiveKit access tokens (no extra package required)."""
    cfg = livekit_config()
    if not cfg['api_key'] or not cfg['api_secret']:
        raise RuntimeError('LIVEKIT_API_KEY/SECRET not configured')

    now = int(time.time())
    video: dict[str, Any] = {
        'roomJoin': True,
        'room': room,
        'canPublish': bool(can_publish),
        'canSubscribe': bool(can_subscribe),
        'canPublishData': bool(can_publish_data),
    }
    payload = {
        'iss': cfg['api_key'],
        'sub': identity,
        'name': name,
        'nbf': now - 10,
        'exp': now + max(60, min(ttl_seconds, 3600)),
        'video': video,
    }
    header = {'alg': 'HS256', 'typ': 'JWT'}
    segments = [
        _b64url(json.dumps(header, separators=(',', ':')).encode('utf-8')),
        _b64url(json.dumps(payload, separators=(',', ':')).encode('utf-8')),
    ]
    signing_input = '.'.join(segments).encode('ascii')
    sig = hmac.new(cfg['api_secret'].encode('utf-8'), signing_input, hashlib.sha256).digest()
    return f'{segments[0]}.{segments[1]}.{_b64url(sig)}'
