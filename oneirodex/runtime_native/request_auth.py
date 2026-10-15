"""Framework-neutral extraction and resolution of FastAPI request identity.

This module adapts an ASGI-style request to the existing signed-session and
authentication rules. It deliberately uses duck-typed request attributes so
the compatibility rules can be tested without a running server or database.
Persistence callbacks remain caller-owned; native callers should omit the
optional Flask-Login loader and use the framework-independent fingerprint
resolver.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .auth_resolver import AuthResolution, resolve_authentication, token_has_scope
from .session_compat import load_session_cookie


@dataclass(frozen=True)
class RequestAuthContext:
    """Resolved identity plus the mutable Flask-compatible session state.

    Routes can inspect ``resolution`` and update ``session_data``. The original
    snapshot lets response adapters reproduce Flask's modified/refresh rules.
    No raw bearer credential or cookie value is retained.
    """

    session_data: MutableMapping[str, Any]
    original_session: Mapping[str, Any]
    resolution: AuthResolution
    session_cookie_name: str
    remember_cookie_name: str
    session_refresh_each_request: bool

    @property
    def user(self) -> Any | None:
        return self.resolution.user

    @property
    def token(self) -> Any | None:
        return self.resolution.token

    @property
    def source(self) -> str:
        return self.resolution.source

    @property
    def session_protected(self) -> bool:
        return self.resolution.session_protected

    @property
    def session_modified(self) -> bool:
        return dict(self.session_data) != dict(self.original_session)

    @property
    def should_set_session_cookie(self) -> bool:
        """Whether Flask's session interface would write/refresh this session."""
        return self.session_modified or bool(
            self.session_data.get("_permanent") and self.session_refresh_each_request
        )

    @property
    def remember_action(self) -> str | None:
        action = self.session_data.get("_remember")
        return action if action in {"set", "clear"} else None

    def has_scope(self, scope: str) -> bool:
        """Apply the existing role and token-scope policy to this identity."""
        if self.user is None:
            return False
        return token_has_scope(self.user, self.token, scope)


def request_auth_context(
    request: Any,
    config: Mapping[str, Any],
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    now: datetime | None = None,
    allow_bearer: bool = True,
) -> RequestAuthContext:
    """Resolve a request using Flask's session, remember, and Bearer rules.

    ``request`` only needs ``cookies``, ``headers``, and optional ``client``
    attributes (as provided by Starlette). The three persistence functions are
    injected so this module neither imports app models nor opens transactions.
    ``load_user_id`` is an optional compatibility hook for callers that must
    retain an existing loader. Native routes should omit it so the shared
    resolver applies active-user and password-fingerprint checks directly.
    """
    secret_key = config.get("SECRET_KEY")
    if not secret_key:
        raise ValueError("Native request authentication requires SECRET_KEY")

    cookies = _mapping_attr(request, "cookies")
    headers = _mapping_attr(request, "headers")
    if not allow_bearer:
        auth_header_name = str(config.get("AUTH_HEADER_NAME") or "Authorization").lower()
        headers = {key: value for key, value in headers.items() if key.lower() != auth_header_name}
    session_cookie_name = str(config.get("SESSION_COOKIE_NAME") or "session")
    remember_cookie_name = str(config.get("REMEMBER_COOKIE_NAME") or "remember_token")
    fallback_keys = config.get("SECRET_KEY_FALLBACKS") or ()
    session_data = load_session_cookie(
        cookies.get(session_cookie_name),
        secret_key,
        max_age=_lifetime_seconds(config.get("PERMANENT_SESSION_LIFETIME", 31_536_000)),
        fallback_secret_keys=fallback_keys,
    )
    original_session = dict(session_data)

    client = getattr(request, "client", None)
    remote_addr = getattr(client, "host", None) if client is not None else None
    from oneirodex.utils.trusted_proxy import trusted_forwarded_for

    session_protection = config.get(
        "SESSION_PROTECTION", getattr(login_manager, "session_protection", "basic")
    )
    resolution = resolve_authentication(
        session_data,
        cookies=cookies,
        headers=headers,
        remote_addr=remote_addr,
        user_agent=_header(headers, "User-Agent"),
        forwarded_for=trusted_forwarded_for(request, config),
        secret_key=secret_key,
        find_user=find_user,
        find_token=find_token,
        commit_token_touch=commit_token_touch,
        load_user_id=load_user_id,
        now=now or datetime.now(timezone.utc),
        session_protection=session_protection,
        remember_cookie_name=remember_cookie_name,
        authorization_header_name=str(config.get("AUTH_HEADER_NAME") or "Authorization"),
        allow_legacy_id=bool(config.get("TESTING")),
    )
    return RequestAuthContext(
        session_data=session_data,
        original_session=original_session,
        resolution=resolution,
        session_cookie_name=session_cookie_name,
        remember_cookie_name=remember_cookie_name,
        session_refresh_each_request=bool(config.get("SESSION_REFRESH_EACH_REQUEST", True)),
    )


def _mapping_attr(obj: Any, name: str) -> Mapping[str, str]:
    value = getattr(obj, name, None)
    return value if isinstance(value, Mapping) else {}


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _lifetime_seconds(value: Any) -> int:
    if isinstance(value, timedelta):
        return max(0, int(value.total_seconds()))
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 31_536_000
