"""Framework-neutral invite projections shared by Flask and FastAPI routes."""
from __future__ import annotations

from datetime import datetime, timezone


INVITE_TTL_HOURS = 48


def smtp_ready() -> bool:
    """Report whether the configured SMTP sender can deliver invite mail."""
    try:
        from oneirodex.utils.smtp import is_smtp_config_valid

        valid, _reason = is_smtp_config_valid()
        return bool(valid)
    except Exception:  # noqa: BLE001 — missing settings should not break invite reads
        return False


def site_url() -> str:
    from oneirodex.utils.public_origin import public_origin

    return public_origin()


def invite_url(token: str, *, origin: str | None = None) -> str:
    if origin:
        return f'{origin.rstrip("/")}/register?token={token}'
    from oneirodex.utils.public_origin import invite_url as build_invite_url

    return build_invite_url(token)


def invites_unlimited(user) -> bool:
    """Main admins are not invite-metered."""
    return getattr(user, 'role', None) == 'admin'


def unused_invite_count(user) -> int:
    from sqlalchemy import func, select

    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import InviteToken

    return db.session.scalar(
        select(func.count(InviteToken.id)).filter_by(
            creator_user_id=user.user_id, used=False,
        )
    ) or 0


def invite_row(invite, *, origin: str | None = None) -> dict:
    created = getattr(invite, 'created_at', None)
    # Use the persisted expiry so the UI matches the redeem transition.
    expires = getattr(invite, 'expires_at', None)
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return {
        'token': invite.token,
        'email': invite.recipient_email or None,
        'url': invite_url(invite.token, origin=origin),
        'created_at': created.isoformat() if created else None,
        'expires_at': getattr(invite, 'expires_at', None).isoformat()
        if getattr(invite, 'expires_at', None) else None,
        'expired': bool(expires and expires < datetime.now(timezone.utc)),
    }
