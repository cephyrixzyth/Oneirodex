"""Focused compatibility and key-identity tests for encrypted save blobs."""
import json
import base64
import hashlib

import pytest
from cryptography.fernet import Fernet

from scripts.migrate_emulator_save_keys import initialize_keyring, rotate_keyring
from oneirodex.utils import save_crypto
from oneirodex.utils.save_keyring import load_save_keyring


def _keyring(tmp_path, *, active="key-a", keys=None, legacy_keys=None):
    path = tmp_path / "save-keyring.json"
    path.write_text(json.dumps({
        "active_key_id": active,
        "keys": keys or {"key-a": Fernet.generate_key().decode("ascii")},
        "legacy_keys": legacy_keys or {},
    }), encoding="utf-8")
    if path.stat().st_mode:
        path.chmod(0o600)
    return path


def test_new_encrypted_saves_use_active_versioned_key(tmp_path, monkeypatch):
    path = _keyring(tmp_path)
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(path))
    monkeypatch.setattr(save_crypto, "encrypt_saves_enabled", lambda: True)

    payload, encrypted = save_crypto.maybe_encrypt(b"save-canary")

    assert encrypted is True
    assert payload.startswith(save_crypto.KEYED_MAGIC + b"key-a:")
    assert save_crypto.maybe_decrypt(payload) == b"save-canary"


def test_keyed_save_requires_matching_operator_key(tmp_path, monkeypatch):
    original = _keyring(tmp_path)
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(original))
    monkeypatch.setattr(save_crypto, "encrypt_saves_enabled", lambda: True)
    payload, _ = save_crypto.maybe_encrypt(b"preserve-me")

    replacement = _keyring(
        tmp_path,
        keys={"other": Fernet.generate_key().decode("ascii")},
        active="other",
    )
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(replacement))
    with pytest.raises(RuntimeError, match="key is unavailable"):
        save_crypto.maybe_decrypt(payload)


def test_legacy_gtenc1_reads_with_secret_key_after_new_format(tmp_path, monkeypatch):
    monkeypatch.setattr(
        save_crypto, "get_runtime_config", lambda: {"SECRET_KEY": "legacy-secret"},
    )
    token = save_crypto._fernet().encrypt(b"legacy-save")

    assert save_crypto.maybe_decrypt(save_crypto.MAGIC + token) == b"legacy-save"


def test_legacy_gtenc1_can_use_retained_operator_key(tmp_path, monkeypatch):
    old_secret = "legacy-secret"
    old_key = base64.urlsafe_b64encode(hashlib.sha256(old_secret.encode()).digest())
    old_fernet = Fernet(old_key)
    token = old_fernet.encrypt(b"legacy-save")
    path = _keyring(
        tmp_path,
        legacy_keys={"legacy-a": old_key.decode("ascii")},
    )
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(path))
    monkeypatch.setattr(save_crypto, "get_runtime_config", lambda: {"SECRET_KEY": "rotated-secret"})

    assert save_crypto.maybe_decrypt(save_crypto.MAGIC + token) == b"legacy-save"


def test_keyring_initialization_and_rotation_preserve_legacy_read_key(tmp_path):
    initial = tmp_path / "save-keyring.json"
    initialize_keyring(initial, "existing-secret-key")
    first = load_save_keyring(str(initial))
    legacy_token = save_crypto.MAGIC + save_crypto.legacy_fernet(
        "existing-secret-key",
    ).encrypt(b"retained-generation")

    rotated_path = tmp_path / "rotated-keyring.json"
    new_active = rotate_keyring(initial, rotated_path)
    rotated = load_save_keyring(str(rotated_path))

    assert rotated.active_key_id == new_active
    assert new_active != first.active_key_id
    assert set(rotated.keys) == {first.active_key_id, new_active}
    assert any(key.decrypt(legacy_token[len(save_crypto.MAGIC):]) == b"retained-generation"
               for key in rotated.legacy_keys)
