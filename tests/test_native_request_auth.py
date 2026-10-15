from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from oneirodex.runtime_native.auth_resolver import session_identifier
from oneirodex.runtime_native.request_auth import request_auth_context
from oneirodex.runtime_native.session_compat import dump_session_cookie


SECRET = "request-auth-test-secret"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


@dataclass
class User:
    id: int
    role: str = "user"
    state: bool = True
    is_active: bool = True
    password_hash: str = "password-hash"

    def session_fingerprint(self):
        return hashlib.sha256(self.password_hash.encode()).hexdigest()[:16]


@dataclass
class Token:
    user_id: int
    token_hash: str
    scopes: list[str]
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class Request:
    def __init__(self, *, cookies=None, headers=None, host="192.0.2.20"):
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.client = SimpleNamespace(host=host) if host else None


def _auth(request, users, tokens=None, commits=None, **config):
    tokens = tokens or {}
    commits = commits if commits is not None else []
    settings = {
        "SECRET_KEY": SECRET,
        "PERMANENT_SESSION_LIFETIME": timedelta(days=31),
        "SESSION_PROTECTION": "basic",
        "SESSION_COOKIE_NAME": "session",
        "REMEMBER_COOKIE_NAME": "remember_token",
        "SESSION_REFRESH_EACH_REQUEST": True,
        **config,
    }
    return request_auth_context(
        request,
        settings,
        find_user=lambda user_id: users.get(user_id),
        find_token=lambda prefix: tokens.get(prefix),
        commit_token_touch=commits.append,
        now=NOW,
    )


def test_signed_session_keeps_password_fingerprint_and_session_protection_rules():
    user = User(7)
    user_id = f"{user.id}:{user.session_fingerprint()}"
    session = {"_user_id": user_id, "_fresh": True}
    cookie = dump_session_cookie(session, SECRET)
    request = Request(
        cookies={"session": cookie},
        headers={"User-Agent": "test-agent"},
    )

    context = _auth(request, {7: user})

    assert context.user is user
    assert context.source == "session"
    assert context.session_cookie_name == "session"
    assert context.session_modified  # session protection marks it non-fresh
    assert context.session_data["_fresh"] is False
    assert context.should_set_session_cookie
    assert context.remember_action is None


def test_forged_forwarded_for_does_not_change_native_session_fingerprint():
    user = User(70)
    user_id = f"{user.id}:{user.session_fingerprint()}"
    session_id = session_identifier("192.0.2.20", "test-agent")
    cookie = dump_session_cookie(
        {"_user_id": user_id, "_id": session_id, "_fresh": True}, SECRET
    )
    request = Request(
        cookies={"session": cookie},
        headers={"User-Agent": "test-agent", "X-Forwarded-For": "198.51.100.9"},
        host="192.0.2.20",
    )

    context = _auth(
        request,
        {70: user},
        TRUSTED_PROXIES=1,
        TRUSTED_PROXY_CIDRS="10.10.0.0/24",
    )

    assert context.user is user
    assert context.session_data["_fresh"] is True


def test_remember_cookie_restores_stale_session_and_blocks_bearer_fallback():
    user = User(8)
    payload = f"{user.id}:{user.session_fingerprint()}"
    digest = hmac.new(SECRET.encode("latin1"), payload.encode(), hashlib.sha512).hexdigest()
    remember = f"{payload}|{digest}"
    request = Request(
        cookies={"remember_token": remember},
        headers={"Authorization": "Bearer gt_prefix_secret"},
    )
    token = Token(99, hashlib.sha256(b"secret").hexdigest(), ["library:read"])
    commits = []

    context = _auth(request, {8: user}, {"prefix": token}, commits)

    assert context.user is user
    assert context.source == "remember"
    assert context.session_data["_user_id"] == payload
    assert context.session_data["_fresh"] is False
    assert context.should_set_session_cookie
    assert context.remember_cookie_name == "remember_token"
    assert not commits


def test_bearer_scope_and_last_used_are_preserved_without_retaining_secret():
    user = User(9, role="admin")
    token = Token(9, hashlib.sha256(b"secret").hexdigest(), ["library:read"])
    commits = []
    request = Request(headers={"authorization": "Bearer gt_prefix_secret"})

    context = _auth(request, {9: user}, {"prefix": token}, commits)

    assert context.user is user
    assert context.token is token
    assert context.source == "bearer"
    assert context.has_scope("library:read")
    assert not context.has_scope("admin")
    assert token.last_used_at == NOW
    assert commits == [token]
    assert "secret" not in repr(context)


def test_session_protection_strong_clears_session_and_remember_cookie():
    user = User(10)
    stale_id = session_identifier("192.0.2.1", "old-agent")
    session = {"_user_id": f"{user.id}:{user.session_fingerprint()}", "_id": stale_id,
               "_fresh": True, "next": "/library"}
    cookie = dump_session_cookie(session, SECRET)
    request = Request(
        cookies={"session": cookie, "remember_token": "invalid"},
        headers={"User-Agent": "new-agent"},
    )

    context = _auth(request, {10: user}, SESSION_PROTECTION="strong")

    assert context.user is None
    assert context.session_protected
    assert context.session_data == {"_remember": "clear"}
    assert context.remember_action == "clear"
    assert context.should_set_session_cookie


def test_invalid_session_fingerprint_rejects_user():
    user = User(11)
    cookie = dump_session_cookie({"_user_id": "11:stale-fingerprint"}, SECRET)
    context = _auth(Request(cookies={"session": cookie}), {11: user})
    assert context.user is None
    assert context.source == "anonymous"


def test_invalid_secret_fails_closed_and_numeric_lifetime_is_supported():
    request = Request()
    context = _auth(request, {}, PERMANENT_SESSION_LIFETIME=1800)
    assert context.user is None

    try:
        request_auth_context(
            request,
            {},
            find_user=lambda _user_id: None,
            find_token=lambda _prefix: None,
            commit_token_touch=lambda _token: None,
        )
    except ValueError as exc:
        assert "SECRET_KEY" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("missing SECRET_KEY must fail closed")
