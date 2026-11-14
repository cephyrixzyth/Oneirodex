"""Server-side lifetime and revocation checks for browser login cookies."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from oneirodex.models import PersistentLoginSession

MAX_SESSION_AGE = timedelta(days=30)
MAX_SESSION_IDLE = timedelta(days=7)
_TOUCH_INTERVAL = timedelta(minutes=5)


def issue_login_identity(user, *, now: datetime | None = None) -> str:
    """Create a login record and return a cookie identity with a random secret."""
    from oneirodex.runtime_native.db_session import native_db

    moment = _utc(now)
    session_id = uuid4().hex
    secret = secrets.token_urlsafe(32)
    row = PersistentLoginSession(
        id=session_id,
        user_id=int(user.id),
        secret_hash=_secret_hash(secret),
        created_at=moment,
        last_seen_at=moment,
        expires_at=moment + MAX_SESSION_AGE,
    )
    native_db.session.add(row)
    native_db.session.commit()
    fingerprint = user.session_fingerprint()
    return f'{user.id}:{fingerprint}:{session_id}:{secret}'


def ensure_login_identity(
    identity: str, *, testing: bool = False, enabled: bool = False,
) -> str:
    """Replace a newly issued legacy user ID with a persisted session identity."""
    if testing or not enabled or _parse_identity(identity) is not None:
        return identity
    raw_user_id, separator, fingerprint = identity.partition(':')
    if not separator or not raw_user_id.isdecimal():
        raise ValueError('Cannot issue a persistent login for an invalid identity')
    from oneirodex.models import User
    from oneirodex.runtime_native.db_session import native_db

    user = native_db.session.get(User, int(raw_user_id))
    if user is None or not hmac.compare_digest(
        fingerprint, str(user.session_fingerprint())
    ):
        raise ValueError('Cannot issue a persistent login for an inactive identity')
    return issue_login_identity(user)


def validate_login_identity(
    identity: str,
    user,
    *,
    now: datetime | None = None,
    touch: bool = True,
) -> bool:
    """Reject old-format, revoked, expired, idle or forged persistent identities."""
    from oneirodex.runtime_native.db_session import native_db

    parsed = _parse_identity(identity)
    if parsed is None:
        return False
    user_id, fingerprint, session_id, secret = parsed
    if user_id != int(user.id) or not hmac.compare_digest(
        fingerprint, str(user.session_fingerprint())
    ):
        return False

    moment = _utc(now)
    row = native_db.session.execute(
        select(PersistentLoginSession).where(
            PersistentLoginSession.id == session_id,
            PersistentLoginSession.user_id == user_id,
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    if not hmac.compare_digest(row.secret_hash, _secret_hash(secret)):
        return False
    if _utc(row.expires_at) <= moment:
        return False
    if _utc(row.last_seen_at) <= moment - MAX_SESSION_IDLE:
        return False
    if touch and _utc(row.last_seen_at) < moment - _TOUCH_INTERVAL:
        _touch(session_id, moment)
    return True


def revoke_login_session(session_id: str, *, user_id: int, now: datetime | None = None) -> bool:
    """Revoke one session owned by a user; caller owns transaction commit."""
    from oneirodex.runtime_native.db_session import native_db

    if not isinstance(session_id, str) or len(session_id) != 32:
        return False
    result = native_db.session.execute(
        update(PersistentLoginSession)
        .where(
            PersistentLoginSession.id == session_id,
            PersistentLoginSession.user_id == int(user_id),
            PersistentLoginSession.revoked_at.is_(None),
        )
        .values(revoked_at=_utc(now))
    )
    return bool(result.rowcount)


def revoke_all_login_sessions(user_id: int, *, now: datetime | None = None) -> int:
    """Revoke all active browser sessions owned by a user."""
    from oneirodex.runtime_native.db_session import native_db

    result = native_db.session.execute(
        update(PersistentLoginSession)
        .where(
            PersistentLoginSession.user_id == int(user_id),
            PersistentLoginSession.revoked_at.is_(None),
        )
        .values(revoked_at=_utc(now))
    )
    return max(0, int(result.rowcount or 0))


def active_login_sessions(user_id: int):
    """List the user's non-revoked, non-expired sessions newest first."""
    from oneirodex.runtime_native.db_session import native_db

    now = _utc()
    return list(native_db.session.execute(
        select(PersistentLoginSession)
        .where(
            PersistentLoginSession.user_id == int(user_id),
            PersistentLoginSession.revoked_at.is_(None),
            PersistentLoginSession.expires_at > now,
            PersistentLoginSession.last_seen_at > now - MAX_SESSION_IDLE,
        )
        .order_by(PersistentLoginSession.last_seen_at.desc())
    ).scalars())


def session_id_from_identity(identity: str | None) -> str | None:
    parsed = _parse_identity(identity)
    return parsed[2] if parsed else None


def prepare_session_identity_for_cookie(session_data, config) -> None:
    """Keep retired user-id cookies from becoming trusted during a rewrite.

    Login handlers issue persistent identities explicitly. Generic response
    writers may serialize a rejected legacy session to preserve flashes or
    other state, so they must drop its authentication fields instead of
    upgrading it into a new server-side session.
    """
    if config.get('TESTING') or not config.get('PERSISTENT_SESSIONS_ENABLED', True):
        return
    identity = session_data.get('_user_id')
    if identity and session_id_from_identity(str(identity)) is None:
        for key in ('_user_id', '_fresh', '_id'):
            session_data.pop(key, None)


def _touch(session_id: str, now: datetime) -> None:
    from oneirodex.runtime_native.db_session import current_native_engine

    engine = current_native_engine()
    if engine is None:
        from oneirodex import db

        engine = db.engine
    with engine.begin() as connection:
        connection.execute(
            update(PersistentLoginSession)
            .where(
                PersistentLoginSession.id == session_id,
                PersistentLoginSession.revoked_at.is_(None),
                PersistentLoginSession.last_seen_at < now - _TOUCH_INTERVAL,
            )
            .values(last_seen_at=now)
        )


def _parse_identity(identity: str | None):
    if not isinstance(identity, str):
        return None
    parts = identity.split(':')
    if len(parts) != 4:
        return None
    raw_user_id, fingerprint, session_id, secret = parts
    if (
        not raw_user_id.isdecimal()
        or len(fingerprint) != 16
        or len(session_id) != 32
        or not secret
    ):
        return None
    try:
        user_id = int(raw_user_id)
    except ValueError:
        return None
    return user_id, fingerprint, session_id, secret


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode('ascii')).hexdigest()


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
