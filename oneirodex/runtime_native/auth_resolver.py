"""Framework-independent Flask-Login-compatible authentication resolver.

The native FastAPI pilot can use this boundary without touching Flask request
globals. Persistence is injected so the caller owns its database transaction
and can preserve the existing token last-used commit behavior.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


_FLASK_LOGIN_SESSION_KEYS = (
    "_user_id", "_remember", "_remember_seconds", "_id", "_fresh", "next",
)


@dataclass(frozen=True)
class AuthResolution:
    user: Any | None
    token: Any | None = None
    source: str = "anonymous"
    session_protected: bool = False


def session_identifier(
    remote_addr: str | None,
    user_agent: str | None,
    forwarded_for: str | None = None,
) -> str:
    """Match Flask-Login 0.6.3's SHA-512 address/agent identifier exactly.

    Flask-Login formats the UTF-8 byte values directly into the f-string,
    including their ``b'...'`` representation. It also trusts the first
    comma-separated X-Forwarded-For value here; callers must pass the same
    header value seen by Flask for parity.
    """
    address = forwarded_for if forwarded_for is not None else remote_addr
    if address is not None:
        address = address.encode("utf-8").split(b",", 1)[0].strip()
    else:
        address = None
    if user_agent is not None:
        user_agent = user_agent.encode("utf-8")
    base = f"{address}|{user_agent}"
    return hashlib.sha512(base.encode("utf-8")).hexdigest()


def load_active_user_id(
    user_id: str | None,
    find_user: Callable[[int], Any | None],
    *,
    allow_legacy_id: bool = False,
) -> Any | None:
    """Apply this app's active-user and password-fingerprint session rules."""
    raw = str(user_id or "")
    uid, separator, fingerprint = raw.partition(":")
    try:
        user = find_user(int(uid))
    except (TypeError, ValueError):
        return None
    if user is None or not _user_active(user):
        return None
    if separator:
        expected = _session_fingerprint(user)
        if not hmac.compare_digest(fingerprint, expected):
            return None
        return user
    return user if allow_legacy_id else None


def decode_remember_cookie(cookie: str | None, secret_key: str | bytes) -> str | None:
    """Validate Flask-Login 0.6.3's ``payload|HMAC-SHA512`` cookie format."""
    if not isinstance(cookie, str):
        return None
    try:
        payload, digest = cookie.rsplit("|", 1)
    except ValueError:
        return None
    # Flask-Login 0.6.3 encodes textual SECRET_KEY as latin1.
    key = secret_key.encode("latin1") if isinstance(secret_key, str) else secret_key
    expected = hmac.new(key, payload.encode("utf-8"), hashlib.sha512).hexdigest()
    return payload if hmac.compare_digest(expected, digest) else None


def encode_remember_cookie(user_id: str, secret_key: str | bytes) -> str:
    """Create Flask-Login 0.6.3's compatible ``payload|HMAC-SHA512`` cookie."""
    payload = str(user_id)
    key = secret_key.encode("latin1") if isinstance(secret_key, str) else secret_key
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha512).hexdigest()
    return f"{payload}|{digest}"


def resolve_authentication(
    session_data: MutableMapping[str, Any],
    *,
    cookies: Mapping[str, str],
    headers: Mapping[str, str],
    remote_addr: str | None,
    user_agent: str | None,
    forwarded_for: str | None = None,
    secret_key: str | bytes,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    now: datetime | None = None,
    session_protection: str | None = "basic",
    remember_cookie_name: str = "remember_token",
    authorization_header_name: str = "Authorization",
    allow_legacy_id: bool = False,
    touch_bearer: bool = True,
) -> AuthResolution:
    """Resolve session, remember cookie, then Bearer auth in Flask-Login order.

    The callbacks perform all persistence operations. Token touch is committed
    exactly once only after token hash, expiry, revocation, and user-active
    checks pass. Raw credentials are never retained in the returned result.
    """
    mode = session_protection if session_protection in {"basic", "strong"} else None
    ident = session_identifier(remote_addr, user_agent, forwarded_for)
    if session_data and mode and ident != session_data.get("_id"):
        if mode == "basic" or session_data.get("_permanent"):
            if session_data.get("_fresh") is not False:
                session_data["_fresh"] = False
        elif mode == "strong":
            for key in _FLASK_LOGIN_SESSION_KEYS:
                session_data.pop(key, None)
            session_data["_remember"] = "clear"
            return AuthResolution(None, session_protected=True)

    session_user_id = session_data.get("_user_id")
    if session_user_id is not None:
        if load_user_id is not None:
            user = load_user_id(str(session_user_id))
        else:
            user = load_active_user_id(
                str(session_user_id), find_user, allow_legacy_id=allow_legacy_id
            )
        if user is not None:
            return AuthResolution(user, source="session")

    remember_cookie = cookies.get(remember_cookie_name)
    has_remember_cookie = (
        remember_cookie_name in cookies and session_data.get("_remember") != "clear"
    )
    if has_remember_cookie:
        remembered_id = decode_remember_cookie(remember_cookie, secret_key)
        if remembered_id is not None:
            if load_user_id is not None:
                user = load_user_id(remembered_id)
            else:
                user = load_active_user_id(
                    remembered_id, find_user, allow_legacy_id=allow_legacy_id
                )
            if user is not None:
                session_data["_user_id"] = remembered_id
                session_data["_fresh"] = False
                return AuthResolution(user, source="remember")
        # Flask-Login does not invoke request_loader when a remember cookie is
        # present (even when malformed or rejected).
        return AuthResolution(None)

    authorization = _header(headers, authorization_header_name) or ""
    if not authorization.lower().startswith("bearer "):
        return AuthResolution(None)
    raw = authorization.split(" ", 1)[1].strip()
    user, token = _verify_bearer(
        raw, find_user, find_token, commit_token_touch, now=now, touch=touch_bearer,
    )
    if user is None:
        return AuthResolution(None)
    return AuthResolution(user, token=token, source="bearer")


def token_has_scope(user: Any, token: Any | None, scope: str) -> bool:
    """Mirror API scope policy, including explicit admin-token consent."""
    role = str(getattr(user, "role", "user") or "user").strip().lower()
    denied = {
        "child": {"admin", "write:library", "write:download"},
    }.get(role, set())
    if scope in denied:
        return False
    if token is not None:
        has_scope = getattr(token, "has_scope", None)
        if callable(has_scope):
            return bool(has_scope(scope))
        scopes = getattr(token, "scopes", None) or []
        return "admin" in scopes or scope in scopes
    if role == "admin":
        return True
    return scope != "admin"


def _verify_bearer(
    raw: str,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    *,
    now: datetime | None,
    touch: bool = True,
) -> tuple[Any | None, Any | None]:
    if not raw or not raw.startswith("gt_"):
        return None, None
    body = raw[len("gt_"):]
    if "_" not in body:
        return None, None
    prefix, secret = body.split("_", 1)
    if not prefix or not secret:
        return None, None
    token = find_token(prefix)
    if token is None or getattr(token, "revoked_at", None) is not None:
        return None, None
    expected = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(str(getattr(token, "token_hash", "")), expected):
        return None, None
    expired = getattr(token, "is_expired", None)
    if callable(expired):
        if expired(now):
            return None, None
    elif _is_expired(getattr(token, "expires_at", None), now):
        return None, None
    try:
        user = find_user(int(token.user_id))
    except (TypeError, ValueError, AttributeError):
        return None, None
    # Match the existing bearer request loader: persisted false/NULL state is
    # rejected there. Session and remember resolution use User.is_active parity.
    if user is None or not getattr(user, "state", False):
        return None, None
    if touch:
        token.last_used_at = now or datetime.now(timezone.utc)
        commit_token_touch(token)
    return user, token


def _is_expired(expires_at: datetime | None, now: datetime | None) -> bool:
    if expires_at is None:
        return False
    moment = now or datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= moment


def _user_active(user: Any) -> bool:
    if hasattr(user, "is_active"):
        return bool(user.is_active)
    return getattr(user, "state", None) is not False


def _session_fingerprint(user: Any) -> str:
    method = getattr(user, "session_fingerprint", None)
    if callable(method):
        return str(method())
    password_hash = getattr(user, "password_hash", "") or ""
    return hashlib.sha256(str(password_hash).encode("utf-8")).hexdigest()[:16]


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None
