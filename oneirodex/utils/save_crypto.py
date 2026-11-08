"""At-rest encryption helpers for emulator save blobs (Fernet)."""

from __future__ import annotations

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


def maybe_encrypt(raw: bytes) -> tuple[bytes, bool]:
    """Return (payload, encrypted_flag)."""
    if not encrypt_saves_enabled():
        return raw, False
    keyring = load_save_keyring()
    return _encrypt_with_keyring(raw, keyring), True


def _encrypt_with_keyring(raw: bytes, keyring) -> bytes:
    active = keyring.keys.get(keyring.active_key_id)
    if active is None:
        raise SaveKeyUnavailable('Active save encryption key is unavailable')
    token = active.encrypt(raw)
    return KEYED_MAGIC + keyring.active_key_id.encode('ascii') + b':' + token


def maybe_decrypt(payload: bytes) -> bytes:
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
