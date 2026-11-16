"""Authenticated encryption for linked external-store credentials.

The key ring is operator-managed and must live outside the application database
and its backups. It is deliberately independent of Flask's SECRET_KEY.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import os
import re
import stat
from typing import Any, Mapping

from cryptography.fernet import Fernet, InvalidToken


_ENVELOPE_PREFIX = "odsc:v1:"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class StoreCredentialError(ValueError):
    """A stable, redacted credential-storage error safe for API classification."""


class StoreCredentialKeyUnavailable(StoreCredentialError):
    """The operator key ring cannot be read or does not contain a usable key."""


class StoreCredentialMigrationRequired(StoreCredentialError):
    """A linked row still has a legacy plaintext credential."""


@dataclass(frozen=True)
class StoreCredentialKeyring:
    active_key_id: str
    keys: Mapping[str, Fernet]
    key_material: Mapping[str, bytes] = field(default_factory=dict, repr=False, compare=False)


def _keyring_path() -> str:
    try:
        from oneirodex.utils.runtime_config import get_runtime_config

        config = get_runtime_config()
    except Exception:  # noqa: BLE001 - preserve a safe unavailable result
        config = None
    path = None
    if config is not None:
        path = config.get("REUSABLE_SECRET_KEYRING_FILE") or config.get("STORE_CREDENTIAL_KEYRING_FILE")
    path = (
        path
        or os.environ.get("ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE")
        or os.environ.get("ONEIRODEX_STORE_CREDENTIAL_KEYRING_FILE")
    )
    if not isinstance(path, str) or not path.strip():
        raise StoreCredentialKeyUnavailable(
            'Credential key ring is not configured; restore the operator-managed backup or configure the key ring'
        )
    return path.strip()


def load_store_credential_keyring(path: str | None = None) -> StoreCredentialKeyring:
    """Load and validate the operator key ring without exposing its values."""
    keyring_path = path or _keyring_path()
    try:
        if os.name != 'nt' and stat.S_IMODE(os.stat(keyring_path).st_mode) & 0o077:
            raise StoreCredentialKeyUnavailable(
                "Credential key ring permissions are unsafe"
            )
        with open(keyring_path, "r", encoding="utf-8") as source:
            payload = json.load(source)
    except StoreCredentialKeyUnavailable:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StoreCredentialKeyUnavailable(
            'Credential key ring is unreadable or invalid; restore the operator-managed backup'
        ) from exc

    if not isinstance(payload, dict):
        raise StoreCredentialKeyUnavailable("Credential key ring is invalid")
    active_key_id = payload.get("active_key_id")
    raw_keys = payload.get("keys")
    if (
        not isinstance(active_key_id, str)
        or not _KEY_ID_RE.fullmatch(active_key_id)
        or not isinstance(raw_keys, dict)
        or not raw_keys
        or active_key_id not in raw_keys
    ):
        raise StoreCredentialKeyUnavailable("Store credential key ring is invalid")

    keys: dict[str, Fernet] = {}
    key_material: dict[str, bytes] = {}
    try:
        for key_id, encoded_key in raw_keys.items():
            if (
                not isinstance(key_id, str)
                or not _KEY_ID_RE.fullmatch(key_id)
                or not isinstance(encoded_key, str)
            ):
                raise ValueError
            keys[key_id] = Fernet(encoded_key.encode("ascii"))
            key_material[key_id] = base64.urlsafe_b64decode(encoded_key.encode("ascii"))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise StoreCredentialKeyUnavailable("Credential key ring contains an invalid key") from exc

    return StoreCredentialKeyring(
        active_key_id=active_key_id, keys=keys, key_material=key_material,
    )


def encrypt_store_credential(value: str, *, keyring: StoreCredentialKeyring | None = None) -> str:
    """Encrypt a credential into an algorithm- and key-versioned envelope."""
    if not isinstance(value, str) or not value:
        raise ValueError("Store credential must be a non-empty string")
    ring = keyring or load_store_credential_keyring()
    fernet = ring.keys.get(ring.active_key_id)
    if fernet is None:
        raise StoreCredentialKeyUnavailable("Active credential key is unavailable")
    token = fernet.encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_ENVELOPE_PREFIX}{ring.active_key_id}:{token}"


def decrypt_store_credential(value: str, *, keyring: StoreCredentialKeyring | None = None) -> str:
    """Decrypt a versioned envelope; never reinterpret unknown ciphertext as plaintext."""
    if not isinstance(value, str) or not value.startswith(_ENVELOPE_PREFIX):
        raise StoreCredentialError("Store credential ciphertext is invalid")
    remainder = value[len(_ENVELOPE_PREFIX):]
    key_id, separator, token = remainder.partition(":")
    if not separator or not _KEY_ID_RE.fullmatch(key_id) or not token:
        raise StoreCredentialError("Store credential ciphertext is invalid")
    ring = keyring or load_store_credential_keyring()
    fernet = ring.keys.get(key_id)
    if fernet is None:
        raise StoreCredentialKeyUnavailable(
            'Credential decryption key is unavailable; restore matching key IDs from the operator backup'
        )
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise StoreCredentialError("Store credential ciphertext could not be decrypted") from exc


def _ciphertext_key_id(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(_ENVELOPE_PREFIX):
        raise StoreCredentialError("Store credential ciphertext is invalid")
    key_id, separator, token = value[len(_ENVELOPE_PREFIX):].partition(":")
    if not separator or not token or not _KEY_ID_RE.fullmatch(key_id):
        raise StoreCredentialError("Store credential ciphertext is invalid")
    return key_id


def read_store_credential(account: Any) -> str | None:
    """Read only encrypted credentials; legacy plaintext requires conversion."""
    ciphertext = getattr(account, "credential_ciphertext", None)
    legacy = getattr(account, "credential", None)
    if ciphertext:
        # A present ciphertext always wins. A missing/wrong key or corrupt
        # ciphertext must not cause fallback to a legacy plaintext value.
        return decrypt_store_credential(ciphertext)
    if legacy:
        raise StoreCredentialMigrationRequired(
            "Store credentials need the encrypted-storage conversion"
        )
    return None


def has_store_credential(account: Any | None) -> bool:
    """Presence-only query for status; never decrypts or returns secret data."""
    return bool(
        account
        and (
            getattr(account, "credential_ciphertext", None)
            or getattr(account, "credential", None)
        )
    )


def write_store_credential(account: Any, value: str | None) -> None:
    """Encrypt a new credential and clear legacy plaintext on the same row."""
    if value:
        account.credential_ciphertext = encrypt_store_credential(value)
        account.credential = None
    else:
        account.credential_ciphertext = None
        account.credential = None


def migrate_legacy_store_credentials(session, *, batch_size: int = 100) -> dict[str, int]:
    """Encrypt old rows in individually committed, verified, rerunnable batches.

    The database schema must already have the `credential_ciphertext` column.
    Failures leave that row's original plaintext in place and never report its
    value. Callers must pass an isolated or explicitly operator-selected session.
    """
    if batch_size < 1 or batch_size > 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    ring = load_store_credential_keyring()

    from sqlalchemy import func, or_, select
    from oneirodex.models import StoreAccount

    encrypted = 0
    rotated = 0
    already_encrypted = 0
    failures = 0
    credential_rows = or_(
        StoreAccount.credential.isnot(None),
        StoreAccount.credential_ciphertext.isnot(None),
    )
    last_id = 0
    while True:
        row_ids = session.execute(
            select(StoreAccount.id)
            .where(StoreAccount.id > last_id, credential_rows)
            .order_by(StoreAccount.id)
            .limit(batch_size)
        ).scalars().all()
        if not row_ids:
            break
        for row_id in row_ids:
            last_id = row_id
            account = session.get(StoreAccount, row_id)
            if account is None:
                continue
            legacy = account.credential
            ciphertext = account.credential_ciphertext
            if not legacy and ciphertext:
                try:
                    plaintext = decrypt_store_credential(ciphertext, keyring=ring)
                    if _ciphertext_key_id(ciphertext) == ring.active_key_id:
                        already_encrypted += 1
                    else:
                        replacement = encrypt_store_credential(plaintext, keyring=ring)
                        if decrypt_store_credential(replacement, keyring=ring) != plaintext:
                            raise StoreCredentialError("Store credential rotation verification failed")
                        account.credential_ciphertext = replacement
                        session.commit()
                        rotated += 1
                except StoreCredentialError:
                    session.rollback()
                    failures += 1
                continue
            if not legacy:
                continue
            try:
                if ciphertext:
                    if decrypt_store_credential(ciphertext, keyring=ring) != legacy:
                        raise StoreCredentialError("Legacy and encrypted store credentials disagree")
                    account.credential = None
                else:
                    replacement = encrypt_store_credential(legacy, keyring=ring)
                    if decrypt_store_credential(replacement, keyring=ring) != legacy:
                        raise StoreCredentialError("Store credential encryption verification failed")
                    account.credential_ciphertext = replacement
                    account.credential = None
                session.commit()
                encrypted += 1
            except Exception:  # noqa: BLE001 - count safely and allow explicit rerun
                session.rollback()
                failures += 1

    remaining = session.scalar(
        select(func.count(StoreAccount.id)).where(
            StoreAccount.credential.isnot(None),
            StoreAccount.credential != "",
        )
    ) or 0
    return {
        "encrypted": encrypted,
        "rotated": rotated,
        "already_encrypted": already_encrypted,
        "remaining_legacy": int(remaining),
        "failures": failures,
    }
