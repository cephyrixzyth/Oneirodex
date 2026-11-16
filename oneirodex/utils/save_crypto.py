"""At-rest encryption helpers for emulator save blobs (Fernet)."""

from __future__ import annotations

import hashlib
import json
import re

from oneirodex.utils.runtime_config import get_runtime_config
from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.save_keyring import (
    SaveKeyUnavailable,
    legacy_fernet,
    load_save_keyring,
)

MAGIC = b'GTENC1:'  # Historical SECRET_KEY-derived format.
KEYED_MAGIC = b'GTENC2:'
BOUND_MAGIC = b'GTENC3:'
_BOUND_PLAINTEXT_MAGIC = b'ODSC1:'
_GENERATION_ID_RE = re.compile(r'^[0-9a-f]{32}$')


class SaveContextError(ValueError):
    """The authenticated save does not belong to the requested generation."""


def save_context(user_id, game_uuid: str, slot_name: str, generation_id: str) -> dict:
    if (isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1
            or not isinstance(game_uuid, str) or not game_uuid
            or not isinstance(slot_name, str) or not slot_name
            or not isinstance(generation_id, str) or not _GENERATION_ID_RE.fullmatch(generation_id)):
        raise SaveContextError('Save generation context is invalid')
    return {
        'user_id': user_id,
        'game_uuid': game_uuid,
        'slot_name': slot_name,
        'generation_id': generation_id,
    }


def generation_id_for_path(storage_path: str) -> str:
    normalized = str(storage_path).replace('\\', '/').rstrip('/')
    components = [part for part in normalized.split('/') if part]
    basename = components[-1].removesuffix('.save') if components else ''
    if _GENERATION_ID_RE.fullmatch(basename):
        return basename
    # Historical names were not necessarily opaque or unique outside their
    # owner/game/slot. Bind their normalized relative tail; move remapping only
    # changes the leading storage root.
    return hashlib.sha256('/'.join(components[-3:]).casefold().encode('utf-8')).hexdigest()[:32]


def context_for_row(row, *, owner=None) -> dict:
    if hasattr(row, 'user_id'):
        user_id, game_uuid, slot_name = row.user_id, row.game_uuid, row.slot_name
    else:
        if owner is None:
            raise SaveContextError('Save generation owner is unavailable')
        user_id, game_uuid, slot_name = owner.user_id, owner.game_uuid, owner.slot_name
    generation_id = generation_id_for_path(row.storage_path)
    return save_context(user_id, game_uuid, slot_name, generation_id)


def _context_digest(context: dict) -> bytes:
    normalized = save_context(
        context.get('user_id'), context.get('game_uuid'), context.get('slot_name'),
        context.get('generation_id'),
    )
    raw = json.dumps(normalized, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return hashlib.sha256(raw).digest()


def encrypt_saves_enabled() -> bool:
    if str(get_runtime_config().get('ENCRYPT_EMULATOR_SAVES', 'false')).lower() in (
        '1', 'true', 'yes', 'on',
    ):
        return True
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    return bool(getattr(settings, 'encrypt_emulator_saves', False)) if settings else False


def _fernet():
    """Legacy Fernet helper retained for standalone import compatibility."""
    config = get_runtime_config() or {}
    return legacy_fernet(config.get('SECRET_KEY'))


def maybe_encrypt(raw: bytes, *, context: dict | None = None) -> tuple[bytes, bool]:
    """Return (payload, encrypted_flag)."""
    if not encrypt_saves_enabled():
        return raw, False
    keyring = load_save_keyring()
    if context is None:
        raise SaveContextError('New encrypted saves require an owning generation context')
    return _encrypt_with_keyring(raw, keyring, context=context), True


def _encrypt_with_keyring(raw: bytes, keyring, *, context: dict | None = None) -> bytes:
    active = keyring.keys.get(keyring.active_key_id)
    if active is None:
        raise SaveKeyUnavailable('Active save encryption key is unavailable')
    if context is None:
        token = active.encrypt(raw)
        return KEYED_MAGIC + keyring.active_key_id.encode('ascii') + b':' + token
    token = active.encrypt(_BOUND_PLAINTEXT_MAGIC + _context_digest(context) + raw)
    return BOUND_MAGIC + keyring.active_key_id.encode('ascii') + b':' + token


def maybe_decrypt(payload: bytes, *, context: dict | None = None) -> bytes:
    if payload.startswith(BOUND_MAGIC):
        key_id, separator, token = payload[len(BOUND_MAGIC):].partition(b':')
        if not separator or not key_id:
            raise SaveKeyUnavailable('Encrypted save header is invalid')
        if context is None:
            raise SaveContextError('Encrypted save requires its owning generation context')
        keyring = load_save_keyring()
        key = keyring.keys.get(key_id.decode('ascii', errors='strict'))
        if key is None:
            raise SaveKeyUnavailable(
                'Save decryption key is unavailable; restore the matching operator backup'
            )
        opened = key.decrypt(token)
        prefix = _BOUND_PLAINTEXT_MAGIC + _context_digest(context)
        if not opened.startswith(prefix):
            raise SaveContextError('Encrypted save belongs to a different generation')
        return opened[len(prefix):]
    if payload.startswith(KEYED_MAGIC):
        key_id, separator, token = payload[len(KEYED_MAGIC):].partition(b':')
        if not separator or not key_id:
            raise SaveKeyUnavailable('Encrypted save header is invalid')
        keyring = load_save_keyring()
        key = keyring.keys.get(key_id.decode('ascii', errors='strict'))
        if key is None:
            raise SaveKeyUnavailable(
                'Save decryption key is unavailable; restore the matching operator backup'
            )
        return key.decrypt(token)
    if payload.startswith(MAGIC):
        ciphertext = payload[len(MAGIC):]
        try:
            return _fernet().decrypt(ciphertext)
        except Exception as legacy_error:  # noqa: BLE001 - try retained legacy keys only
            try:
                keyring = load_save_keyring()
            except SaveKeyUnavailable:
                raise legacy_error
            for key in keyring.legacy_keys:
                try:
                    return key.decrypt(ciphertext)
                except Exception:  # noqa: BLE001 - authenticated decryption is the key test
                    continue
            raise legacy_error
    return payload
