"""In-process login / auth endpoint rate limiting (Wave polish).

No Redis required — suitable for single-container Unraid/Compose installs.
Keys are IP (+ optional username). Failed attempts lock the key; success clears it.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque

_lock = threading.Lock()
_hits: dict[str, Deque[float]] = defaultdict(deque)


def _defaults() -> tuple[int, float]:
    max_attempts = 10
    window = 300.0
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            max_attempts = int(current_app.config.get('LOGIN_RATE_LIMIT_ATTEMPTS') or max_attempts)
            window = float(current_app.config.get('LOGIN_RATE_LIMIT_WINDOW_SECONDS') or window)
        else:
            max_attempts = int(os.getenv('LOGIN_RATE_LIMIT_ATTEMPTS', str(max_attempts)) or max_attempts)
            window = float(os.getenv('LOGIN_RATE_LIMIT_WINDOW_SECONDS', str(window)) or window)
    except (ValueError, TypeError, Exception):
        try:
            max_attempts = int(os.getenv('LOGIN_RATE_LIMIT_ATTEMPTS', '10') or '10')
            window = float(os.getenv('LOGIN_RATE_LIMIT_WINDOW_SECONDS', '300') or '300')
        except ValueError:
            max_attempts, window = 10, 300.0
    return max(1, min(max_attempts, 100)), max(30.0, min(window, 3600.0))


def rate_limit_enabled() -> bool:
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            return bool(current_app.config.get('ENABLE_LOGIN_RATE_LIMIT', True))
    except Exception:
        pass
    return os.getenv('ENABLE_LOGIN_RATE_LIMIT', 'true').lower() in (
        '1', 'true', 'yes', 'on',
    )


def client_ip_from_request(request) -> str:
    """The client IP the rate limit keys on.

    ``remote_addr`` only. It used to take the first ``X-Forwarded-For`` hop,
    which any client can set, so a new header value per request meant a fresh
    bucket every time and no limit at all. Behind a reverse proxy, set
    ``TRUSTED_PROXIES`` and ProxyFix (utils/proxy.py) puts the real client
    address in ``remote_addr`` from the hops that proxy added.
    """
    _warn_if_behind_an_untrusted_proxy(request)
    return (request.remote_addr or 'unknown')[:64]


_PROXY_WARNED = False


def _warn_if_behind_an_untrusted_proxy(request) -> None:
    """Say once, in the log, when requests carry X-Forwarded-For but
    TRUSTED_PROXIES is 0: every visitor then shares the proxy's address, so one
    person's failed logins lock everyone out of the per-address limit."""
    global _PROXY_WARNED
    if _PROXY_WARNED or not request.headers.get('X-Forwarded-For'):
        return
    try:
        from flask import current_app

        if int(current_app.config.get('TRUSTED_PROXIES') or 0) > 0:
            return
        current_app.logger.warning(
            'Requests carry X-Forwarded-For but TRUSTED_PROXIES is 0: the login '
            'rate limit sees the proxy as the client, so one visitor can lock '
            'everyone out. Set TRUSTED_PROXIES to the number of proxies in front.'
        )
    except Exception:  # noqa: BLE001 — a warning must never break login
        return
    _PROXY_WARNED = True


def _prune(bucket: Deque[float], now: float, window: float) -> None:
    while bucket and (now - bucket[0]) > window:
        bucket.popleft()


def is_rate_limited(key: str, *, now: float | None = None) -> bool:
    if not rate_limit_enabled():
        return False
    max_attempts, window = _defaults()
    stamp = time.monotonic() if now is None else now
    with _lock:
        bucket = _hits[key]
        _prune(bucket, stamp, window)
        return len(bucket) >= max_attempts


def record_failure(key: str, *, now: float | None = None) -> int:
    """Record a failed attempt; returns current count in window."""
    if not rate_limit_enabled():
        return 0
    max_attempts, window = _defaults()
    stamp = time.monotonic() if now is None else now
    with _lock:
        bucket = _hits[key]
        _prune(bucket, stamp, window)
        bucket.append(stamp)
        # Cap memory
        while len(bucket) > max_attempts + 5:
            bucket.popleft()
        return len(bucket)


def clear_failures(key: str) -> None:
    with _lock:
        _hits.pop(key, None)


def reset_for_tests() -> None:
    with _lock:
        _hits.clear()


def login_rate_key(ip: str, username: str | None = None) -> str:
    user_part = (username or '').strip().casefold()[:64] or '-'
    return f'login:{ip}:{user_part}'


def auth_endpoint_key(endpoint: str, ip: str) -> str:
    return f'{endpoint}:{ip}'
