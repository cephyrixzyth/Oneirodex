#!/usr/bin/env python3
"""Prepare a protected save keyring and re-encrypt immutable save blobs.

The command never loads dotenv files, falls back to TEST_DATABASE_URL, prints
save paths or key material, or performs provider requests. Re-encryption is
opt-in with --apply and operates only on rows whose files are under --root.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oneirodex.models import EmulatorSave, EmulatorSaveGeneration, User
from oneirodex.utils.save_crypto import BOUND_MAGIC, _encrypt_with_keyring, context_for_row, maybe_decrypt, save_context
from oneirodex.utils.save_keyring import load_save_keyring
from scripts.migrate_store_credentials import resolve_database_url


def _write_keyring(path: Path, payload: dict) -> None:
    path = path.expanduser().absolute()
    if path.parent.is_symlink():
        raise ValueError("Keyring output directory must not be a symlink")
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        if not parent_existed:
            os.chmod(path.parent, 0o700)
        if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
            raise ValueError("Keyring output directory permissions are unsafe")
    if path.exists() or path.is_symlink():
        raise ValueError("Output keyring already exists")
    fd, temp_name = tempfile.mkstemp(prefix=".save-keyring-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def initialize_keyring(path: Path, secret_key: str) -> None:
    active_id = f"save-{secrets.token_hex(6)}"
    legacy_key = base64.urlsafe_b64encode(
        hashlib.sha256((secret_key or "oneirodex").encode("utf-8")).digest(),
    ).decode("ascii")
    _write_keyring(path, {
        "active_key_id": active_id,
        "keys": {active_id: Fernet.generate_key().decode("ascii")},
        "legacy_keys": {"secret-key-derived-v1": legacy_key},
    })


def rotate_keyring(source: Path, destination: Path) -> str:
    load_save_keyring(str(source))
    source_payload = json.loads(source.read_text(encoding="utf-8"))
    keys = dict(source_payload["keys"])
    key_id = f"save-{secrets.token_hex(6)}"
    keys[key_id] = Fernet.generate_key().decode("ascii")
    _write_keyring(destination, {
        "active_key_id": key_id,
        "keys": keys,
        "legacy_keys": dict(source_payload.get("legacy_keys", {})),
    })
    return key_id


def _safe_path(raw_path: str, root: Path) -> Path | None:
    try:
        candidate = Path(raw_path)
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            return None
        return resolved
    except (OSError, ValueError, RuntimeError):
        return None


def _encrypt_active(raw: bytes, keyring, context: dict) -> bytes:
    return _encrypt_with_keyring(raw, keyring, context=context)


def _stage(path: Path, payload: bytes, generation_id: str) -> Path:
    fd, temp_name = tempfile.mkstemp(prefix=".save-rotation-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        final_path = path.parent / f"{generation_id}.save"
        os.replace(temp_path, final_path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
        return final_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _reference_key(raw_path: str) -> str:
    # Resolve aliases even when the last component is missing. A symlink row
    # cannot be migrated, but must still protect the file it references.
    return os.path.normcase(str(Path(raw_path).resolve()))


def _unreferenced(session: Session, aliases: set[str]) -> bool:
    paths = sorted(aliases)
    for offset in range(0, len(paths), 450):
        for model in (EmulatorSave, EmulatorSaveGeneration):
            if session.scalar(select(model.id).where(
                model.storage_path.in_(paths[offset:offset + 450]),
            ).limit(1)) is not None:
                return False
    return True


def migrate_rows(session: Session, root: Path, *, apply: bool) -> dict[str, int]:
    keyring = load_save_keyring()
    counts = {"visited": 0, "already_active": 0, "rotated": 0, "skipped": 0, "failures": 0}
    rows = [
        *(session.execute(select(EmulatorSave)).scalars().all()),
        *(session.execute(select(EmulatorSaveGeneration)).scalars().all()),
    ]
    identities = [(type(row), row.id) for row in rows]
    aliases: dict[str, set[str]] = {}
    references_known = True
    if apply:
        for row in rows:
            try:
                aliases.setdefault(_reference_key(row.storage_path), set()).add(row.storage_path)
            except (OSError, ValueError, RuntimeError, TypeError):
                references_known = False
    for model, row_id in identities:
        counts["visited"] += 1
        try:
            if apply:
                owner_query = select(EmulatorSave.user_id)
                if model is EmulatorSave:
                    owner_query = owner_query.where(EmulatorSave.id == row_id)
                else:
                    owner_query = owner_query.join(EmulatorSaveGeneration).where(
                        EmulatorSaveGeneration.id == row_id,
                    )
                owner_id = session.scalar(owner_query)
                if owner_id is None:
                    counts["skipped"] += 1
                    continue
                # Match store_save/delete_save, then discard any ORM snapshot
                # read before the writer committed while we waited.
                if session.scalar(select(User.id).where(User.id == owner_id).with_for_update()) is None:
                    counts["skipped"] += 1
                    continue
            row = session.get(model, row_id, populate_existing=apply)
            if row is None:
                counts["skipped"] += 1
                continue
            owner = row if isinstance(row, EmulatorSave) else session.get(EmulatorSave, row.save_id)
            if apply and owner is not None and owner is not row:
                session.refresh(owner)
            if owner is None:
                counts["failures"] += 1
                continue
            if apply and owner.user_id != owner_id:
                raise ValueError("Save ownership changed during rotation")
            if not row.encrypted:
                counts["skipped"] += 1
                continue
            old_path = _safe_path(row.storage_path, root)
            if old_path is None:
                counts["failures"] += 1
                continue
            if apply:
                aliases.setdefault(_reference_key(row.storage_path), set()).add(row.storage_path)
            stored = old_path.read_bytes()
            context = context_for_row(row, owner=owner)
            if stored.startswith(BOUND_MAGIC):
                header = stored[len(BOUND_MAGIC):].partition(b":")[0].decode("ascii")
                if header == keyring.active_key_id:
                    maybe_decrypt(stored, context=context)
                    counts["already_active"] += 1
                    continue
            plain = maybe_decrypt(stored, context=context)
            generation_id = uuid4().hex
            replacement_context = save_context(
                owner.user_id, owner.game_uuid, owner.slot_name, generation_id,
            )
            replacement = _encrypt_active(plain, keyring, replacement_context)
            if maybe_decrypt(replacement, context=replacement_context) != plain:
                raise ValueError("Save rotation verification failed")
            if not apply:
                counts["rotated"] += 1
                continue
            new_path = _stage(old_path, replacement, generation_id)
            row.storage_path = str(new_path)
            try:
                session.commit()
            except Exception:
                session.rollback()
                # Commit outcome can be ambiguous; keep both immutable files.
                raise
            try:
                # The initial alias inventory includes both tables. Fresh SQL
                # also sees history inserted by the serialized production writer.
                # Writers must still be stopped for operator migration; arbitrary
                # concurrent imports or manual path edits are not supported.
                candidates = aliases.get(_reference_key(str(old_path)))
                if references_known and candidates and _unreferenced(session, candidates):
                    old_path.unlink()
            except Exception:  # uncertain references must preserve ciphertext
                pass
            counts["rotated"] += 1
        except Exception:  # noqa: BLE001 - report only counts, never DB/path details
            session.rollback()
            counts["failures"] += 1
        finally:
            if apply:
                # Includes skipped/active/missing rows and the reference query's
                # post-commit read transaction. Never leave an owner lock behind.
                session.rollback()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--initialize-keyring", type=Path, metavar="OUTPUT")
    modes.add_argument("--rotate-keyring-from", type=Path, metavar="SOURCE")
    modes.add_argument("--migrate", action="store_true", help="re-encrypt save rows to the active key")
    parser.add_argument("--write-keyring", type=Path, metavar="OUTPUT")
    parser.add_argument("--root", type=Path, help="configured emulator save root")
    parser.add_argument("--apply", action="store_true", help="commit re-encryption; default is report-only")
    args = parser.parse_args()

    try:
        if args.initialize_keyring:
            secret_key = os.environ.get("SECRET_KEY")
            if not secret_key:
                raise ValueError("SECRET_KEY is required to preserve legacy encrypted saves")
            initialize_keyring(args.initialize_keyring, secret_key)
            print("Save keyring initialized; protect and back it up separately from database and save files.")
            return 0
        if args.rotate_keyring_from:
            if not args.write_keyring:
                raise ValueError("--write-keyring is required when preparing a rotated keyring")
            key_id = rotate_keyring(args.rotate_keyring_from, args.write_keyring)
            print(f"Rotated keyring prepared with active_key_id={key_id}; retain prior keys for recovery.")
            return 0
        if not args.root:
            raise ValueError("--root is required for --migrate")
        raw_root = args.root.expanduser().absolute()
        if raw_root.is_symlink():
            raise ValueError("Save root must be an existing non-symlink directory")
        root = raw_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Save root must be an existing non-symlink directory")
        database_url = resolve_database_url()
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with Session(engine) as session:
                counts = migrate_rows(session, root, apply=args.apply)
        finally:
            engine.dispose()
    except Exception as exc:  # never print a database URL, path, or key material
        print(f"Save key operation failed ({type(exc).__name__}); no confirmation can be inferred.", file=sys.stderr)
        return 1
    mode = "applied" if args.apply else "report-only"
    print(f"Save key migration {mode}: " + " ".join(f"{key}={value}" for key, value in counts.items()))
    return 1 if counts["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
