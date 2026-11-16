"""Operator-managed encryption keys for emulator save blobs."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import os
import re
import stat
from typing import Mapping

from cryptography.fernet import Fernet

from oneirodex.utils.runtime_config import get_runtime_config

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SaveKeyUnavailable(RuntimeError):
    """The configured save keyring is missing, unsafe, or lacks a key."""


@dataclass(frozen=True)
class SaveKeyring:
    active_key_id: str
    keys: Mapping[str, Fernet]
    legacy_keys: tuple[Fernet, ...] = field(default_factory=tuple, repr=False)


def _keyring_path() -> str:
    config = get_runtime_config()
    path = config.get("SAVE_KEYRING_FILE") if config is not None else None
    path = path or os.environ.get("ONEIRODEX_SAVE_KEYRING_FILE")
    if not isinstance(path, str) or not path.strip():
        raise SaveKeyUnavailable(
            "Save encryption requires an operator-managed save keyring"
        )
    return path.strip()


def load_save_keyring(path: str | None = None) -> SaveKeyring:
    keyring_path = path or _keyring_path()
    try:
        if os.name != "nt" and stat.S_IMODE(os.stat(keyring_path).st_mode) & 0o077:
            raise SaveKeyUnavailable("Save keyring permissions are unsafe")
        with open(keyring_path, "r", encoding="utf-8") as source:
            payload = json.load(source)
    except SaveKeyUnavailable:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SaveKeyUnavailable(
            "Save keyring is unreadable; restore its protected operator backup"
        ) from exc

    if not isinstance(payload, dict):
        raise SaveKeyUnavailable("Save keyring is invalid")
    active_key_id = payload.get("active_key_id")
    raw_keys = payload.get("keys")
    raw_legacy = payload.get("legacy_keys", {})
    if (
        not isinstance(active_key_id, str)
        or not _KEY_ID_RE.fullmatch(active_key_id)
        or not isinstance(raw_keys, dict)
        or not raw_keys
        or active_key_id not in raw_keys
        or not isinstance(raw_legacy, dict)
    ):
        raise SaveKeyUnavailable("Save keyring is invalid")

    try:
        keys = {
            key_id: Fernet(encoded.encode("ascii"))
            for key_id, encoded in raw_keys.items()
            if isinstance(key_id, str)
            and _KEY_ID_RE.fullmatch(key_id)
            and isinstance(encoded, str)
        }
        legacy_keys = tuple(
            Fernet(encoded.encode("ascii"))
            for key_id, encoded in raw_legacy.items()
            if isinstance(key_id, str)
            and _KEY_ID_RE.fullmatch(key_id)
            and isinstance(encoded, str)
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise SaveKeyUnavailable("Save keyring contains an invalid key") from exc
    if len(keys) != len(raw_keys) or len(legacy_keys) != len(raw_legacy):
        raise SaveKeyUnavailable("Save keyring contains an invalid key")
    return SaveKeyring(active_key_id, keys, legacy_keys)


def legacy_fernet(secret_key: str | None) -> Fernet:
    """Recreate the original GTENC1 key for compatibility reads/moves."""
    import hashlib

    secret = (secret_key or "oneirodex").encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))
