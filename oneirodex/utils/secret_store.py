"""Versioned, context-bound storage for reusable integration secrets.

The key ring is operator managed and independent from both database backups
and Flask's SECRET_KEY. Values without this envelope are legacy values and are
read only during the explicit migration window; every new write is encrypted.
"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import hashlib
import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from oneirodex.utils.store_credentials import (
    StoreCredentialError,
    StoreCredentialKeyUnavailable,
    StoreCredentialKeyring,
    load_store_credential_keyring,
)

REUSABLE_SECRET_PREFIX = 'odrc:v1:'
_KEY_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
_CONTEXT_RE = re.compile(r'^[a-z][A-Za-z0-9_.:-]{0,191}$')

GLOBAL_SECRET_FIELDS = frozenset({
    'smtp_password',
    'igdb_client_secret',
    'oidc_client_secret',
    'steam_web_api_key',
    'steamgriddb_api_key',
    'giantbomb_api_key',
    'mobygames_api_key',
    'thegamesdb_api_key',
    'retroachievements_api_key',
})

ARR_SECRET_FIELDS = frozenset({
    'prowlarr_api_key', 'jackett_api_key',
    'qbittorrent_password', 'transmission_password', 'deluge_password',
    'sabnzbd_api_key', 'nzbget_password',
    'real_debrid_token', 'alldebrid_api_key', 'premiumize_api_key',
    'torbox_api_key', 'challenge_token_api_key', 'hyperion_token', 'ha_token',
})


def encrypt_reusable_secret(
    value: str,
    *,
    context: str,
    keyring: StoreCredentialKeyring | None = None,
) -> str:
    """Encrypt a secret using a field-specific key derived from the key ring."""
    if not isinstance(value, str) or not value:
        raise ValueError('Reusable secret must be a non-empty string')
    context_bytes = _context_bytes(context)
    ring = keyring or load_store_credential_keyring()
    key_id = ring.active_key_id
    master = ring.key_material.get(key_id)
    if master is None:
        raise StoreCredentialKeyUnavailable('Active reusable-secret key is unavailable')
    token = _context_cipher(master, context_bytes).encrypt(value.encode('utf-8')).decode('ascii')
    encoded_context = base64.urlsafe_b64encode(context_bytes).decode('ascii').rstrip('=')
    return f'{REUSABLE_SECRET_PREFIX}{key_id}:{encoded_context}:{token}'


def decrypt_reusable_secret(
    envelope: str,
    *,
    context: str,
    keyring: StoreCredentialKeyring | None = None,
) -> str:
    """Decrypt only a valid envelope bound to the requested context."""
    key_id, stored_context, token = _parse_envelope(envelope)
    expected_context = _context_bytes(context)
    if stored_context != expected_context:
        raise StoreCredentialError('Reusable secret context does not match')
    ring = keyring or load_store_credential_keyring()
    master = ring.key_material.get(key_id)
    if master is None:
        raise StoreCredentialKeyUnavailable('Reusable-secret decryption key is unavailable')
    try:
        return _context_cipher(master, expected_context).decrypt(token.encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise StoreCredentialError('Reusable secret ciphertext could not be decrypted') from exc


def reusable_secret_key_id(envelope: str) -> str:
    """Return a validated non-secret key ID from an envelope."""
    key_id, _context, _token = _parse_envelope(envelope)
    return key_id


def read_reusable_secret(
    value: str | None,
    *,
    context: str,
    keyring: StoreCredentialKeyring | None = None,
) -> str | None:
    """Read a new envelope or a legacy plaintext value during migration.

    An unknown or malformed `odrc:` value is always an error. It cannot fall
    through to the legacy plaintext path.
    """
    if not value:
        return None
    if value.startswith('odrc:'):
        return decrypt_reusable_secret(value, context=context, keyring=keyring)
    return value


def write_reusable_secret(
    value: str | None,
    *,
    context: str,
    keyring: StoreCredentialKeyring | None = None,
) -> str | None:
    if value is None or value == '':
        return None
    if value.startswith('odrc:'):
        # A caller may preserve a masked value, but never accepts opaque
        # ciphertext under the wrong setting/context without verifying it.
        decrypt_reusable_secret(value, context=context, keyring=keyring)
        return value
    return encrypt_reusable_secret(value, context=context, keyring=keyring)


def has_reusable_secret(value: str | None) -> bool:
    """Presence-only projection. It never decrypts or returns a value."""
    return bool(value)


def global_secret_context(field: str) -> str:
    if field not in GLOBAL_SECRET_FIELDS:
        raise ValueError('Unsupported reusable-secret field')
    return f'global_settings.{field}'


def read_global_secret(row: Any | None, field: str) -> str | None:
    value = getattr(row, field, None) if row is not None else None
    return read_reusable_secret(value, context=global_secret_context(field))


def write_global_secret(row: Any, field: str, value: str | None) -> None:
    setattr(
        row,
        field,
        write_reusable_secret(value, context=global_secret_context(field)),
    )


def has_global_secret(row: Any | None, field: str) -> bool:
    return has_reusable_secret(getattr(row, field, None) if row is not None else None)


def reusable_secret_storage_status() -> dict[str, Any]:
    """Expose actionable key-ring availability without exposing its path or key IDs."""
    try:
        load_store_credential_keyring()
    except StoreCredentialKeyUnavailable:
        return {
            'available': False,
            'message': (
                'Encrypted integration credentials are unavailable. Restore the operator-managed '
                'key-ring backup; if no matching backup exists, reconnect affected integrations.'
            ),
        }
    return {'available': True, 'message': None}


def migrate_reusable_secrets(session, *, batch_size: int = 100) -> dict[str, int]:
    """Encrypt legacy GlobalSettings secrets and rotate old-key envelopes.

    Each settings row is committed only after every stored value has been
    transformed and independently decrypted for verification. Failed rows are
    left intact and can be retried after the operator repairs the key ring.
    """
    if batch_size < 1 or batch_size > 1000:
        raise ValueError('batch_size must be between 1 and 1000')
    ring = load_store_credential_keyring()
    from oneirodex.models import GlobalSettings
    from sqlalchemy import select

    result = {
        'rows_changed': 0, 'secrets_encrypted': 0, 'secrets_rotated': 0,
        'rows_already_current': 0, 'remaining_legacy': 0, 'failures': 0,
    }
    last_id = 0
    while True:
        ids = session.execute(
            select(GlobalSettings.id)
            .where(GlobalSettings.id > last_id)
            .order_by(GlobalSettings.id)
            .limit(batch_size)
        ).scalars().all()
        if not ids:
            break
        for row_id in ids:
            last_id = row_id
            row = session.get(GlobalSettings, row_id)
            if row is None:
                continue
            changed = False
            encrypted = rotated = 0
            try:
                for field in GLOBAL_SECRET_FIELDS:
                    value = getattr(row, field, None)
                    replacement, was_encrypted, was_rotated = _migrate_value(
                        value, context=global_secret_context(field), keyring=ring,
                    )
                    if replacement != value:
                        setattr(row, field, replacement)
                        changed = True
                    encrypted += int(was_encrypted)
                    rotated += int(was_rotated)

                raw_arr = row.arr_settings
                if isinstance(raw_arr, dict):
                    new_arr = deepcopy(raw_arr)
                    for field in ARR_SECRET_FIELDS:
                        if field in new_arr and new_arr[field] is not None:
                            new_arr[field], was_encrypted, was_rotated = _migrate_value(
                                new_arr[field], context=arr_secret_context(field), keyring=ring,
                            )
                            encrypted += int(was_encrypted)
                            rotated += int(was_rotated)
                    indexers = new_arr.get('indexers')
                    if isinstance(indexers, list):
                        for position, item in enumerate(indexers):
                            if not isinstance(item, dict) or item.get('api_key') is None:
                                continue
                            indexer_id = item.get('id')
                            if not isinstance(indexer_id, str) or not indexer_id.strip():
                                indexer_id = f'legacy-{position}'
                            item['api_key'], was_encrypted, was_rotated = _migrate_value(
                                item['api_key'],
                                context=arr_secret_context('api_key', indexer_id=indexer_id),
                                keyring=ring,
                            )
                            encrypted += int(was_encrypted)
                            rotated += int(was_rotated)
                    if new_arr != raw_arr:
                        row.arr_settings = new_arr
                        changed = True

                if changed:
                    session.commit()
                    result['rows_changed'] += 1
                else:
                    result['rows_already_current'] += 1
                result['secrets_encrypted'] += encrypted
                result['secrets_rotated'] += rotated
            except Exception:  # noqa: BLE001 - errors are counted, never rendered with values
                session.rollback()
                result['failures'] += 1

    result['remaining_legacy'] = _count_legacy_reusable_secrets(session)
    return result


def _migrate_value(value: Any, *, context: str, keyring: StoreCredentialKeyring):
    if value is None or value == '':
        return value, False, False
    if not isinstance(value, str):
        raise StoreCredentialError('Stored reusable secret is invalid')
    if value.startswith('odrc:'):
        plaintext = decrypt_reusable_secret(value, context=context, keyring=keyring)
        key_id = reusable_secret_key_id(value)
        if key_id == keyring.active_key_id:
            return value, False, False
        replacement = encrypt_reusable_secret(plaintext, context=context, keyring=keyring)
        if decrypt_reusable_secret(replacement, context=context, keyring=keyring) != plaintext:
            raise StoreCredentialError('Reusable secret rotation verification failed')
        return replacement, False, True
    replacement = encrypt_reusable_secret(value, context=context, keyring=keyring)
    if decrypt_reusable_secret(replacement, context=context, keyring=keyring) != value:
        raise StoreCredentialError('Reusable secret encryption verification failed')
    return replacement, True, False


def _count_legacy_reusable_secrets(session) -> int:
    from oneirodex.models import GlobalSettings
    from sqlalchemy import select

    count = 0
    for row in session.execute(select(GlobalSettings)).scalars():
        count += sum(
            1 for field in GLOBAL_SECRET_FIELDS
            if (value := getattr(row, field, None)) and not value.startswith('odrc:')
        )
        raw_arr = row.arr_settings if isinstance(row.arr_settings, dict) else {}
        count += sum(
            1 for field in ARR_SECRET_FIELDS
            if (value := raw_arr.get(field)) and (not isinstance(value, str) or not value.startswith('odrc:'))
        )
        indexers = raw_arr.get('indexers')
        if isinstance(indexers, list):
            count += sum(
                1 for item in indexers if isinstance(item, dict)
                and (value := item.get('api_key'))
                and (not isinstance(value, str) or not value.startswith('odrc:'))
            )
    return count


def arr_secret_context(field: str, *, indexer_id: str | None = None) -> str:
    if field == 'api_key' and indexer_id:
        if not isinstance(indexer_id, str) or not indexer_id.strip() or len(indexer_id) > 128:
            raise ValueError('Indexer credential identity is invalid')
        identity_hash = hashlib.sha256(indexer_id.encode('utf-8')).hexdigest()
        return f'global_settings.arr_settings.indexers.{identity_hash}.api_key'
    if field not in ARR_SECRET_FIELDS:
        raise ValueError('Unsupported reusable-secret field')
    return f'global_settings.arr_settings.{field}'


def read_arr_settings(row: Any | None) -> dict[str, Any]:
    """Copy `arr_settings` and decrypt its enumerated secret values."""
    raw = getattr(row, 'arr_settings', None) if row is not None else None
    if not isinstance(raw, dict):
        return {}
    return _transform_arr_settings(raw, decrypt=True)


def write_arr_settings(row: Any, values: dict[str, Any]) -> None:
    """Store enumerated `arr_settings` secrets as context-bound envelopes."""
    if not isinstance(values, dict):
        raise ValueError('Integration settings must be an object')
    row.arr_settings = _transform_arr_settings(values, decrypt=False)


def _transform_arr_settings(values: dict[str, Any], *, decrypt: bool) -> dict[str, Any]:
    transformed = dict(values)
    for field in ARR_SECRET_FIELDS:
        value = transformed.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise StoreCredentialError('Stored integration secret is invalid')
        context = arr_secret_context(field)
        transformed[field] = (
            read_reusable_secret(value, context=context)
            if decrypt else write_reusable_secret(value, context=context)
        )

    indexers = transformed.get('indexers')
    if isinstance(indexers, list):
        encrypted_indexers = []
        for position, item in enumerate(indexers):
            if not isinstance(item, dict):
                encrypted_indexers.append(item)
                continue
            indexer = dict(item)
            api_key = indexer.get('api_key')
            if api_key is not None:
                if not isinstance(api_key, str):
                    raise StoreCredentialError('Stored indexer credential is invalid')
                indexer_id = indexer.get('id')
                if not isinstance(indexer_id, str) or not indexer_id.strip():
                    indexer_id = f'legacy-{position}'
                context = arr_secret_context('api_key', indexer_id=indexer_id)
                indexer['api_key'] = (
                    read_reusable_secret(api_key, context=context)
                    if decrypt else write_reusable_secret(api_key, context=context)
                )
            encrypted_indexers.append(indexer)
        transformed['indexers'] = encrypted_indexers
    return transformed


def _parse_envelope(envelope: str) -> tuple[str, bytes, str]:
    if not isinstance(envelope, str) or not envelope.startswith(REUSABLE_SECRET_PREFIX):
        raise StoreCredentialError('Reusable secret envelope is invalid')
    parts = envelope[len(REUSABLE_SECRET_PREFIX):].split(':', 2)
    if len(parts) != 3:
        raise StoreCredentialError('Reusable secret envelope is invalid')
    key_id, encoded_context, token = parts
    if not _KEY_ID_RE.fullmatch(key_id) or not encoded_context or not token:
        raise StoreCredentialError('Reusable secret envelope is invalid')
    try:
        padded = encoded_context + '=' * (-len(encoded_context) % 4)
        context = base64.b64decode(padded.encode('ascii'), altchars=b'-_', validate=True)
        decoded = context.decode('ascii')
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise StoreCredentialError('Reusable secret envelope is invalid') from exc
    if _context_bytes(decoded) != context:
        raise StoreCredentialError('Reusable secret envelope is invalid')
    return key_id, context, token


def _context_bytes(context: str) -> bytes:
    if not isinstance(context, str) or not _CONTEXT_RE.fullmatch(context):
        raise ValueError('Reusable secret context is invalid')
    return context.encode('ascii')


def _context_cipher(master: bytes, context: bytes) -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b'Oneirodex reusable secret envelope v1',
        info=b'Oneirodex field binding:' + context,
    ).derive(master)
    return Fernet(base64.urlsafe_b64encode(key))
