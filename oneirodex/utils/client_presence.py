"""Companion client heartbeat presence helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import ClientDevice
from oneirodex.utils.client_capabilities import normalize_device_kind

CLIENT_HEARTBEAT_TTL_SECONDS = 300


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def user_client_connected(user_id: int | None) -> bool:
    """True when the user has a device heartbeat within the TTL window."""
    if user_id is None:
        return False

    cutoff = _utcnow() - timedelta(seconds=CLIENT_HEARTBEAT_TTL_SECONDS)
    row = db.session.execute(
        select(ClientDevice.id)
        .filter(
            ClientDevice.user_id == user_id,
            ClientDevice.last_seen_at >= cutoff,
        )
        .limit(1)
    ).first()
    return row is not None


def record_client_heartbeat(
    user_id: int,
    device_id: str,
    *,
    device_kind: str | None = None,
    device_name: str | None = None,
    client_version: str | None = None,
    user_agent: str | None = None,
) -> ClientDevice:
    """Upsert a client device row and refresh last_seen_at."""
    now = _utcnow()
    device = db.session.execute(
        select(ClientDevice).filter_by(user_id=user_id, device_id=device_id)
    ).scalars().first()

    kind = normalize_device_kind(device_kind)

    if device is None:
        device = ClientDevice(
            user_id=user_id,
            device_id=device_id,
            device_kind=kind,
            device_name=_truncate(device_name, 128),
            client_version=_truncate(client_version, 64),
            user_agent=_truncate(user_agent, 512),
            last_seen_at=now,
            created_at=now,
        )
        db.session.add(device)
    else:
        device.last_seen_at = now
        device.device_kind = kind
        if device_name is not None:
            device.device_name = _truncate(device_name, 128)
        if client_version is not None:
            device.client_version = _truncate(client_version, 64)
        if user_agent is not None:
            device.user_agent = _truncate(user_agent, 512)

    db.session.commit()
    return device


def _truncate(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:max_len]
