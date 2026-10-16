"""At-rest encryption helpers for emulator save blobs (Fernet)."""

from __future__ import annotations

import base64
import hashlib

from oneirodex.utils.runtime_config import get_runtime_config
from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings

MAGIC = b'GTENC1:'


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
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            'cryptography package is required for encrypted emulator saves',
        ) from exc
    secret = (get_runtime_config().get('SECRET_KEY') or 'oneirodex').encode('utf-8')
    digest = hashlib.sha256(secret).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def maybe_encrypt(raw: bytes) -> tuple[bytes, bool]:
    """Return (payload, encrypted_flag)."""
    if not encrypt_saves_enabled():
        return raw, False
    token = _fernet().encrypt(raw)
    return MAGIC + token, True


def maybe_decrypt(payload: bytes) -> bytes:
    if not payload.startswith(MAGIC):
        return payload
    return _fernet().decrypt(payload[len(MAGIC):])
