"""Focused compatibility and key-identity tests for encrypted save blobs."""
import json
import base64
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from scripts.migrate_emulator_save_keys import initialize_keyring, rotate_keyring
from scripts.migrate_emulator_save_keys import migrate_rows
from oneirodex.models import EmulatorSave, EmulatorSaveGeneration, Game, Library, User
from oneirodex.platform import LibraryPlatform
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

    context = save_crypto.save_context(7, "game-a", "slot1", "a" * 32)
    payload, encrypted = save_crypto.maybe_encrypt(b"save-canary", context=context)

    assert encrypted is True
    assert payload.startswith(save_crypto.BOUND_MAGIC + b"key-a:")
    assert save_crypto.maybe_decrypt(payload, context=context) == b"save-canary"


def test_context_bound_save_cannot_be_copied_to_another_owner_or_generation(tmp_path, monkeypatch):
    path = _keyring(tmp_path)
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(path))
    monkeypatch.setattr(save_crypto, "encrypt_saves_enabled", lambda: True)
    context = save_crypto.save_context(7, "game-a", "slot1", "a" * 32)
    payload, _ = save_crypto.maybe_encrypt(b"save-canary", context=context)

    for other in (
        save_crypto.save_context(8, "game-a", "slot1", "a" * 32),
        save_crypto.save_context(7, "game-b", "slot1", "a" * 32),
        save_crypto.save_context(7, "game-a", "slot2", "a" * 32),
        save_crypto.save_context(7, "game-a", "slot1", "b" * 32),
    ):
        with pytest.raises(save_crypto.SaveContextError, match="different generation"):
            save_crypto.maybe_decrypt(payload, context=other)


def test_store_save_binds_ciphertext_to_current_owner_and_slot(
    db_session, tmp_path, monkeypatch,
):
    owner = User(
        name=f"save-bound-{uuid4().hex[:8]}",
        email=f"save-bound-{uuid4().hex[:8]}@example.com",
        password_hash="unused", role="user", user_id=str(uuid4()), state=True,
    )
    library = Library(name=f"save-bound-{uuid4().hex[:8]}", platform=LibraryPlatform.NES, display_order=1)
    db_session.add_all([owner, library])
    db_session.flush()
    game = Game(
        uuid=str(uuid4()), name="Bound save canary", library_uuid=library.uuid,
        full_disk_path=f"/test/{uuid4().hex}.nes",
    )
    db_session.add(game)
    db_session.commit()

    ring = _keyring(tmp_path)
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(ring))
    monkeypatch.setattr(save_crypto, "encrypt_saves_enabled", lambda: True)
    monkeypatch.setattr("oneirodex.utils.emulator_saves._saves_root", lambda: str(tmp_path / "saves"))
    from io import BytesIO
    from oneirodex.utils.emulator_saves import read_save_bytes, store_save

    row = store_save(
        user_id=owner.id, game_uuid=game.uuid, slot_name="slot1",
        file_storage=BytesIO(b"owned-save"),
    )
    stored = Path(row.storage_path).read_bytes()
    assert stored.startswith(save_crypto.BOUND_MAGIC)
    assert read_save_bytes(row) == b"owned-save"
    wrong_owner = save_crypto.save_context(
        owner.id + 1, game.uuid, row.slot_name, save_crypto.generation_id_for_path(row.storage_path),
    )
    with pytest.raises(save_crypto.SaveContextError, match="different generation"):
        save_crypto.maybe_decrypt(stored, context=wrong_owner)


def test_keyed_save_requires_matching_operator_key(tmp_path, monkeypatch):
    original = _keyring(tmp_path)
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(original))
    monkeypatch.setattr(save_crypto, "encrypt_saves_enabled", lambda: True)
    context = save_crypto.save_context(7, "game-a", "slot1", "c" * 32)
    payload, _ = save_crypto.maybe_encrypt(b"preserve-me", context=context)

    replacement = _keyring(
        tmp_path,
        keys={"other": Fernet.generate_key().decode("ascii")},
        active="other",
    )
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(replacement))
    with pytest.raises(RuntimeError, match="key is unavailable"):
        save_crypto.maybe_decrypt(payload, context=context)


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


def test_postgres_rotation_updates_current_and_history_after_commit(
    db_session, tmp_path, monkeypatch,
):
    owner = User(
        name=f"save-key-{uuid4().hex[:8]}",
        email=f"save-key-{uuid4().hex[:8]}@example.com",
        password_hash="unused", role="user", user_id=str(uuid4()), state=True,
    )
    library = Library(name=f"save-key-{uuid4().hex[:8]}", platform=LibraryPlatform.NES, display_order=1)
    db_session.add_all([owner, library])
    db_session.flush()
    game = Game(
        uuid=str(uuid4()), name="Save key rotation canary", library_uuid=library.uuid,
        full_disk_path=f"/test/{uuid4().hex}.nes",
    )
    db_session.add(game)
    db_session.flush()

    current_plain = b"current-save-generation"
    previous_plain = b"prior-save-generation"
    current_path = tmp_path / "current.save"
    previous_path = tmp_path / "previous.save"
    current_path.write_bytes(save_crypto.MAGIC + save_crypto.legacy_fernet("old-secret").encrypt(current_plain))
    previous_path.write_bytes(save_crypto.MAGIC + save_crypto.legacy_fernet("old-secret").encrypt(previous_plain))
    current = EmulatorSave(
        user_id=owner.id, game_uuid=game.uuid, slot_name="slot1", filename="state.sav",
        size_bytes=len(current_plain), storage_path=str(current_path), encrypted=True, revision=2,
    )
    db_session.add(current)
    db_session.flush()
    history = EmulatorSaveGeneration(
        save_id=current.id, filename="old.sav", size_bytes=len(previous_plain),
        storage_path=str(previous_path), encrypted=True,
    )
    db_session.add(history)
    db_session.commit()
    current_id = current.id
    history_id = history.id

    initial_ring = tmp_path / "old-ring.json"
    initialize_keyring(initial_ring, "old-secret")
    active_ring = tmp_path / "active-ring.json"
    rotate_keyring(initial_ring, active_ring)
    monkeypatch.setenv("ONEIRODEX_SAVE_KEYRING_FILE", str(active_ring))

    report = migrate_rows(db_session, Path(tmp_path), apply=False)
    assert report["rotated"] == 2
    assert current_path.exists() and previous_path.exists()

    result = migrate_rows(db_session, Path(tmp_path), apply=True)
    assert result["rotated"] == 2
    db_session.expire_all()
    migrated_current = db_session.get(EmulatorSave, current_id)
    migrated_history = db_session.get(EmulatorSaveGeneration, history_id)
    assert migrated_current is not None and migrated_history is not None
    assert migrated_current.revision == 2
    assert db_session.query(EmulatorSaveGeneration).filter_by(save_id=current_id).count() == 1
    assert save_crypto.maybe_decrypt(
        Path(migrated_current.storage_path).read_bytes(),
        context=save_crypto.context_for_row(migrated_current),
    ) == current_plain
    assert save_crypto.maybe_decrypt(
        Path(migrated_history.storage_path).read_bytes(),
        context=save_crypto.context_for_row(migrated_history, owner=migrated_current),
    ) == previous_plain
    assert not current_path.exists() and not previous_path.exists()
