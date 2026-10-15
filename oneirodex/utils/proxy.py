"""Reverse-proxy helpers for HTTPS-aware Flask URLs behind a load balancer."""

from __future__ import annotations

from typing import Any


def parse_trusted_proxy_count(raw: str | int | None) -> int:
    """Parse TRUSTED_PROXIES env/config into a non-negative hop count (0 = disabled)."""
    if raw is None:
        return 0
    if isinstance(raw, int):
        return max(0, raw)
    value = str(raw).strip()
    if not value or value.lower() in ('0', 'false', 'no', 'off'):
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def apply_proxy_fix(app: Any) -> bool:
    """Apply forwarded headers only for peers in configured proxy CIDRs."""
    count = parse_trusted_proxy_count(app.config.get('TRUSTED_PROXIES', 0))
    if count <= 0:
        return False

    from oneirodex.utils.trusted_proxy import trusted_proxy_address
    from werkzeug.middleware.proxy_fix import ProxyFix

    original_app = app.wsgi_app
    proxy_fixed_app = ProxyFix(
        original_app,
        x_for=count,
        x_proto=count,
        x_host=count,
        x_prefix=count,
    )

    def trusted_proxy_gate(environ, start_response):
        if trusted_proxy_address(environ.get('REMOTE_ADDR'), app.config):
            return proxy_fixed_app(environ, start_response)
        return original_app(environ, start_response)

    app.wsgi_app = trusted_proxy_gate
    return True
