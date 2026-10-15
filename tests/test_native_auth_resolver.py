from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from flask import Flask, request
from flask_login import LoginManager, encode_cookie

from oneirodex.runtime_native.auth_resolver import (
    decode_remember_cookie,
    encode_remember_cookie,
    load_active_user_id,
    resolve_authentication,
    session_identifier,
    token_has_scope,
)


@dataclass
class User:
    id: int
    password_hash: str = "password-hash"
    role: str = "user"
    state: bool | None = True

    @property
    def is_active(self):
        return self.state is not False

    def session_fingerprint(self):
        return hashlib.sha256(self.password_hash.encode()).hexdigest()[:16]


@dataclass
class Token:
    user_id: int
    token_hash: str
    scopes: list[str]
    revoked_at: datetime | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None

    def is_expired(self, now=None):
        if self.expires_at is None:
            return False
        moment = now or datetime.now(timezone.utc)
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires <= moment

    def has_scope(self, scope):
        return "admin" in (self.scopes or []) or scope in (self.scopes or [])


def _harness(user=None, token=None, *, token_prefix="deadbeef"):
    users = {user.id: user} if user else {}
    touched = []

    def find_user(user_id):
        return users.get(user_id)

    def find_token(prefix):
        return token if prefix == token_prefix else None

    def commit_touch(row):
        touched.append(row)

    return find_user, find_token, commit_touch, touched


def _resolve(session=None, *, user=None, token=None, cookies=None, headers=None,
             session_protection="basic", remote_addr="192.0.2.8", user_agent="Agent/1"):
    find_user, find_token, commit_touch, touched = _harness(user, token)
    result = resolve_authentication(
        session if session is not None else {},
        cookies=cookies or {},
        headers=headers or {},
        remote_addr=remote_addr,
        user_agent=user_agent,
        secret_key="test-secret",
        find_user=find_user,
        find_token=find_token,
        commit_token_touch=commit_touch,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        session_protection=session_protection,
    )
    return result, touched


def test_identifier_and_remember_cookie_match_flask_login_063():
    user = User(7)
    app = Flask(__name__)
    manager = LoginManager()
    manager.init_app(app)
    with app.test_request_context(
        "/", environ_base={"REMOTE_ADDR": "192.0.2.8"},
        headers={"User-Agent": "Agent/1"},
    ):
        assert session_identifier(
            request.remote_addr, request.headers.get("User-Agent"),
            request.headers.get("X-Forwarded-For"),
        ) == manager._session_identifier_generator()
    with app.test_request_context(
        "/", environ_base={"REMOTE_ADDR": "192.0.2.8"},
        headers={
            "User-Agent": "Agent/1",
            "X-Forwarded-For": " 203.0.113.9 , 192.0.2.4 ",
        },
    ):
        assert session_identifier(
            request.remote_addr, request.headers.get("User-Agent"),
            request.headers.get("X-Forwarded-For"),
        ) == manager._session_identifier_generator()
    cookie = encode_cookie(user.get_id() if hasattr(user, "get_id") else
                           f"{user.id}:{user.session_fingerprint()}", key="test-secret")
    assert encode_remember_cookie(
        f"{user.id}:{user.session_fingerprint()}", "test-secret"
    ) == cookie
    assert decode_remember_cookie(cookie, "test-secret") == (
        f"{user.id}:{user.session_fingerprint()}"
    )
    assert decode_remember_cookie(cookie + "x", "test-secret") is None


def test_session_requires_active_user_and_constant_time_fingerprint_value():
    user = User(3)
    find_user, *_ = _harness(user)
    assert load_active_user_id(f"3:{user.session_fingerprint()}", find_user) is user
    assert load_active_user_id("3:wrong", find_user) is None
    assert load_active_user_id("3", find_user) is None
    assert load_active_user_id("3", find_user, allow_legacy_id=True) is user
    user.state = False
    assert load_active_user_id(f"3:{user.session_fingerprint()}", find_user) is None


def test_session_then_remember_then_bearer_precedence_and_clear_suppression():
    user = User(5)
    secret = "bearer-secret"
    token = Token(user.id, hashlib.sha256(secret.encode()).hexdigest(), ["read:library"])
    signed_remember = encode_cookie(
        f"{user.id}:{user.session_fingerprint()}", key="test-secret"
    )
    session = {
        "_user_id": f"{user.id}:{user.session_fingerprint()}",
        "_id": session_identifier("192.0.2.8", "Agent/1"),
        "_fresh": True,
    }
    result, touched = _resolve(
        session, user=user, token=token,
        cookies={"remember_token": signed_remember},
        headers={"Authorization": f"Bearer gt_deadbeef_{secret}"},
    )
    assert (result.user, result.source, result.token) == (user, "session", None)
    assert touched == []

    result, touched = _resolve(
        {}, user=user, token=token,
        cookies={"remember_token": signed_remember},
        headers={"Authorization": f"Bearer gt_deadbeef_{secret}"},
    )
    assert (result.user, result.source, result.token) == (user, "remember", None)
    assert result is not None and touched == []

    result, touched = _resolve(
        {"_remember": "clear"}, user=user, token=token,
        cookies={"remember_token": signed_remember},
        headers={"Authorization": f"Bearer gt_deadbeef_{secret}"},
    )
    assert (result.user, result.source, result.token) == (user, "bearer", token)
    assert touched == [token]


def test_present_invalid_remember_cookie_blocks_request_loader_fallback():
    user = User(5)
    secret = "bearer-secret"
    token = Token(user.id, hashlib.sha256(secret.encode()).hexdigest(), ["read:library"])
    result, touched = _resolve(
        {}, user=user, token=token,
        cookies={"remember_token": "invalid"},
        headers={"Authorization": f"Bearer gt_deadbeef_{secret}"},
    )
    assert result.user is None
    assert touched == []


def test_basic_protection_downgrades_freshness_but_preserves_session_identity():
    user = User(5)
    session = {
        "_user_id": f"{user.id}:{user.session_fingerprint()}",
        "_id": "different",
        "_fresh": True,
    }
    result, _ = _resolve(session, user=user, session_protection="basic")
    assert result.user is user
    assert result.source == "session"
    assert session["_fresh"] is False
    assert session["_id"] == "different"


def test_strong_protection_clears_login_keys_and_stops_all_fallbacks():
    user = User(5)
    session = {
        "_user_id": f"{user.id}:{user.session_fingerprint()}",
        "_id": "different",
        "_fresh": True,
        "next": "/admin",
        "unrelated": "keep",
    }
    result, touched = _resolve(
        session, user=user,
        cookies={"remember_token": "valid-ish"},
        headers={"Authorization": "Bearer gt_deadbeef_secret"},
        session_protection="strong",
    )
    assert result.user is None and result.session_protected
    assert session == {"unrelated": "keep", "_remember": "clear"}
    assert touched == []


def test_strong_protection_on_permanent_session_matches_flask_basic_branch():
    user = User(5)
    session = {
        "_permanent": True,
        "_user_id": f"{user.id}:{user.session_fingerprint()}",
        "_id": "different",
        "_fresh": True,
    }
    result, _ = _resolve(session, user=user, session_protection="strong")
    assert result.user is user
    assert session["_fresh"] is False
    assert "_user_id" in session


def test_bearer_token_revocation_hash_expiry_activity_touch_commit_and_scopes():
    user = User(12, role="admin")
    raw = "gt_deadbeef_secret"
    token = Token(
        user.id,
        hashlib.sha256(b"secret").hexdigest(),
        ["read:library"],
        expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    result, touched = _resolve({}, user=user, token=token,
                               headers={"Authorization": f"Bearer {raw}"})
    assert result.user is user and result.token is token and result.source == "bearer"
    assert token.last_used_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert touched == [token]
    assert token_has_scope(user, token, "read:library")
    assert not token_has_scope(user, token, "admin")

    invalid_tokens = (
        Token(user.id, hashlib.sha256(b"secret").hexdigest(), ["admin"],
              revoked_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        Token(user.id, hashlib.sha256(b"secret").hexdigest(), ["admin"],
              expires_at=datetime(2025, 12, 31, tzinfo=timezone.utc)),
        Token(user.id, "wrong", ["admin"]),
    )
    for token in invalid_tokens:
        result, touched = _resolve({}, user=user, token=token,
                                   headers={"Authorization": f"Bearer {raw}"})
        assert result.user is None
        assert touched == []

    user.state = False
    token = Token(user.id, hashlib.sha256(b"secret").hexdigest(), ["admin"])
    result, touched = _resolve({}, user=user, token=token,
                               headers={"Authorization": f"Bearer {raw}"})
    assert result.user is None and touched == []


def test_child_scope_denylist_applies_even_when_token_has_scope():
    child = User(21, role="child")
    token = Token(child.id, "", ["admin"])
    assert not token_has_scope(child, token, "admin")
    assert not token_has_scope(child, token, "write:library")
    assert token_has_scope(child, token, "read:library")

