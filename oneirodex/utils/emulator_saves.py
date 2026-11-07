"""Opt-in emulator save-state storage (per user / game)."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

from oneirodex.utils.runtime_config import get_runtime_config
from sqlalchemy import func, select
from werkzeug.utils import secure_filename

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import EmulatorSave, EmulatorSaveGeneration, GlobalSettings, User
from oneirodex.utils.save_crypto import maybe_decrypt, maybe_encrypt
from oneirodex.utils.library_paths import library_dir

MAX_SAVE_BYTES = 2 * 1024 * 1024  # 2 MiB
MAX_SLOTS_PER_GAME = 10
DEFAULT_USER_SAVE_QUOTA_MB = 1024


class SaveQuotaExceeded(ValueError):
    """An upload would exceed the member's aggregate save-storage quota."""

    code = 'payload_too_large'


class SaveRevisionConflict(ValueError):
    """The slot changed since the caller last read it."""

    code = 'conflict'

    def __init__(self, current_revision: int):
        self.current_revision = int(current_revision)
        super().__init__('A newer save exists for this slot')


def save_quota_would_be_exceeded(
    total_bytes: int,
    replacement_bytes: int,
    upload_bytes: int,
    quota_bytes: int,
) -> bool:
    """Check a write against the member total, excluding the replaced slot."""
    return (
        max(0, int(total_bytes))
        - max(0, int(replacement_bytes))
        + max(0, int(upload_bytes))
        > max(0, int(quota_bytes))
    )

# Slot vocabulary the WebRetro shell writes. `auto` is the state taken when
# the member leaves the room (Back / Power / tab hidden); `cloud-state` is the
# explicit "Sync now"; `qs-<name>` are the member's named quick saves; and
# `cloud-sram` is battery SRAM, which is a save *file* and never a state.
AUTO_STATE_SLOT = 'auto'
CLOUD_STATE_SLOT = 'cloud-state'
CLOUD_SRAM_SLOT = 'cloud-sram'
QUICK_SAVE_PREFIX = 'qs-'
# The legacy Wave 7 placeholder slot name, still readable.
LEGACY_STATE_SLOTS = ('cloud1',)


def is_state_slot(row: EmulatorSave) -> bool:
    """A slot that holds a libretro state (resumable), not SRAM."""
    slot = str(row.slot_name or '')
    if slot == CLOUD_SRAM_SLOT:
        return False
    if slot in (AUTO_STATE_SLOT, CLOUD_STATE_SLOT) or slot in LEGACY_STATE_SLOTS:
        return True
    if slot.startswith(QUICK_SAVE_PREFIX):
        return True
    return str(row.filename or '').lower().endswith('.state')


def resume_summary(row: EmulatorSave) -> dict:
    """The part of a state row a tile needs to say "Resume"."""
    return {
        'slot_name': row.slot_name,
        'updated_at': row.updated_at.isoformat() if row.updated_at else None,
    }


def latest_state_by_game(user_id: int, game_uuids) -> dict[str, dict]:
    """Newest resumable state per game for one member, one query.

    Used by the browse payload so a tile can read "Resume" instead of "Play"
    without a request per tile. Games with only SRAM (or nothing) are absent.
    """
    uuids = [str(u) for u in (game_uuids or []) if u]
    if not user_id or not uuids:
        return {}
    rows = db.session.execute(
        select(EmulatorSave)
        .where(EmulatorSave.user_id == user_id, EmulatorSave.game_uuid.in_(uuids))
        .order_by(EmulatorSave.updated_at.desc()),
    ).scalars().all()
    latest: dict[str, dict] = {}
    for row in rows:
        if row.game_uuid in latest or not is_state_slot(row):
            continue
        latest[row.game_uuid] = resume_summary(row)
    return latest


def save_sync_enabled() -> bool:
    settings = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    if settings is not None and getattr(settings, 'enable_emulator_save_sync', None) is not None:
        return bool(settings.enable_emulator_save_sync)
    return str(get_runtime_config().get('ENABLE_EMULATOR_SAVE_SYNC', 'true')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def _saves_root() -> str:
    root = get_runtime_config().get('EMULATOR_SAVES_PATH')
    if root:
        return root
    return os.path.join(library_dir(), 'saves')


def list_saves(user_id: int, game_uuid: str) -> list[EmulatorSave]:
    return list(
        db.session.execute(
            select(EmulatorSave)
            .filter_by(user_id=user_id, game_uuid=game_uuid)
            .order_by(EmulatorSave.updated_at.desc(), EmulatorSave.slot_name.asc()),
        ).scalars().all(),
    )


def read_save_bytes(row: EmulatorSave) -> bytes:
    if not row.storage_path or not os.path.isfile(row.storage_path):
        raise FileNotFoundError('Save file missing on disk')
    with open(row.storage_path, 'rb') as handle:
        payload = handle.read()
    return maybe_decrypt(payload)


def store_save(
    *,
    user_id: int,
    game_uuid: str,
    slot_name: str,
    file_storage,
    expected_revision: int | None = None,
) -> EmulatorSave:
    if not save_sync_enabled():
        raise RuntimeError('Emulator save sync is disabled')

    # Serialize this member's uploads so concurrent requests cannot both pass
    # the aggregate quota check. The lock is held until the save row commits.
    db.session.execute(
        select(User.id).where(User.id == user_id).with_for_update(),
    ).first()

    slot = (slot_name or 'slot1').strip() or 'slot1'
    if len(slot) > 64:
        raise ValueError('Save slot name exceeds 64 characters')
    existing = list_saves(user_id, game_uuid)
    current = next((row for row in existing if row.slot_name == slot), None)
    current_revision = int(current.revision or 1) if current else 0
    if expected_revision is not None and int(expected_revision) != current_revision:
        raise SaveRevisionConflict(current_revision)
    if current is None and len(existing) >= MAX_SLOTS_PER_GAME:
        raise ValueError(f'Maximum of {MAX_SLOTS_PER_GAME} save slots per game')

    raw = file_storage.read(MAX_SAVE_BYTES + 1)
    if not raw:
        raise ValueError('Save file was empty')
    if len(raw) > MAX_SAVE_BYTES:
        raise ValueError(f'Save exceeds {MAX_SAVE_BYTES} byte limit')

    config = get_runtime_config() or {}
    try:
        quota_mb = max(1, int(config.get('EMULATOR_SAVES_USER_QUOTA_MB', DEFAULT_USER_SAVE_QUOTA_MB)))
    except (TypeError, ValueError):
        quota_mb = DEFAULT_USER_SAVE_QUOTA_MB
    quota_bytes = quota_mb * 1024 * 1024
    total_bytes = db.session.execute(
        select(func.coalesce(func.sum(EmulatorSave.size_bytes), 0))
        .where(EmulatorSave.user_id == user_id),
    ).scalar_one()
    history_bytes = db.session.execute(
        select(func.coalesce(func.sum(EmulatorSaveGeneration.size_bytes), 0))
        .join(EmulatorSave, EmulatorSave.id == EmulatorSaveGeneration.save_id)
        .where(EmulatorSave.user_id == user_id),
    ).scalar_one()
    # Replaced bytes are retained as a generation, so replacement does not
    # free quota; only an explicit delete releases retained storage.
    replacement_bytes = 0
    if save_quota_would_be_exceeded(
        (total_bytes or 0) + (history_bytes or 0), replacement_bytes, len(raw), quota_bytes,
    ):
        raise SaveQuotaExceeded(
            f'Member save-storage quota exceeded ({quota_mb} MiB total)',
        )

    original = secure_filename(getattr(file_storage, 'filename', None) or 'save.state')
    if not original:
        original = 'save.state'

    payload, encrypted = maybe_encrypt(raw)

    dest_dir = os.path.join(_saves_root(), str(user_id), game_uuid)
    os.makedirs(dest_dir, exist_ok=True)
    # Opaque unique names avoid collisions between distinct display slots that
    # sanitize to the same filesystem name, and ensure writes never truncate a
    # previously committed generation.
    dest_name = f'{uuid4().hex}.save'
    dest_path = os.path.join(dest_dir, dest_name)
    fd, temp_path = tempfile.mkstemp(prefix='.pending-', dir=dest_dir)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, dest_path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise

    if current is None:
        current = EmulatorSave(
            user_id=user_id,
            game_uuid=game_uuid,
            slot_name=slot,
            filename=original,
            size_bytes=len(raw),
            storage_path=dest_path,
            encrypted=encrypted,
            revision=1,
        )
        db.session.add(current)
    else:
        db.session.add(EmulatorSaveGeneration(
            save_id=current.id,
            filename=current.filename,
            size_bytes=current.size_bytes,
            storage_path=current.storage_path,
            encrypted=current.encrypted,
        ))
        current.filename = original
        current.size_bytes = len(raw)
        current.storage_path = dest_path
        current.encrypted = encrypted
        current.updated_at = datetime.now(timezone.utc)
        current.revision = current_revision + 1
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        # The commit result can be ambiguous if the connection fails after the
        # server commits. Preserve the unique unreferenced blob for a later,
        # reference-aware recovery/cleanup pass; never risk deleting a live row.
        raise
    return current


def delete_save(user_id: int, game_uuid: str, slot_name: str) -> bool:
    # Serialize deletion with writes so quota accounting and shared legacy-path
    # reference checks cannot race a replacement.
    db.session.execute(
        select(User.id).where(User.id == user_id).with_for_update(),
    ).first()
    row = db.session.execute(
        select(EmulatorSave).filter_by(
            user_id=user_id,
            game_uuid=game_uuid,
            slot_name=slot_name,
        ),
    ).scalars().first()
    if not row:
        return False
    paths = [row.storage_path]
    histories = list(db.session.execute(
        select(EmulatorSaveGeneration).filter_by(save_id=row.id),
    ).scalars().all())
    paths.extend(item.storage_path for item in histories)
    for item in histories:
        db.session.delete(item)
    db.session.delete(row)
    db.session.commit()
    # Delete bytes only after metadata commits, and only when no legacy/shared
    # slot path still references them.
    for path in set(paths):
        if path and not db.session.execute(
            select(EmulatorSave.id).where(EmulatorSave.storage_path == path).limit(1),
        ).first() and not db.session.execute(
            select(EmulatorSaveGeneration.id).where(
                EmulatorSaveGeneration.storage_path == path,
            ).limit(1),
        ).first():
            try:
                os.remove(path)
            except OSError:
                pass
    return True


def save_as_file_storage(row: EmulatorSave):
    """Return a BytesIO of decrypted save bytes for send_file."""
    return BytesIO(read_save_bytes(row))
