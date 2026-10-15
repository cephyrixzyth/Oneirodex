"""HTTP security response headers.

Two callers, because Oneirodex serves responses from two places:

* :func:`apply_security_headers` registers a Flask ``after_request`` for
  everything that goes through WsgiToAsgi.
* :func:`baseline_static_headers` returns the same *baseline* set as raw ASGI
  header tuples, because ``/static/*`` is served natively in ``asgi.py`` and
  never reaches Flask (see the comment there — the bridge breaks under
  concurrent asset loads).

Flask responses enforce CSP by default (``CSP_ENFORCE=true``). Executable inline
``<script>`` and inline event handlers (``onclick=``) remain prohibited in
application-authored HTML shells (ratchets in ``tests/test_no_inline_scripts.py``).
The WebRetro player is a
static document under ``/static/*`` and therefore gets the baseline only — no
CSP — so Flask ``script-src`` does not need ``'unsafe-eval'`` / ``'wasm-unsafe-eval'``.
``style-src`` still allows ``'unsafe-inline'`` for styles used by the shell and
legacy standalone documents.

Set ``CSP_ENFORCE=false`` to report without blocking.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask, Response

# Sent on every response, Flask and static alike. None of these have a
# compatibility cost for this app.
BASELINE_HEADERS: dict[str, str] = {
    # Chat attachments allow .txt/.csv/.pdf, and the cover pipeline writes
    # .gif — none of which should ever be sniffed into an active type.
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Frame-Options': 'SAMEORIGIN',
}

# Only on Flask responses — a static asset has no use for it, and the header is
# long enough that repeating it on every tile image is real bytes.
#
# Allowlisted rather than blanket-denied: `microphone`/`camera`/`display-capture`
# are the LiveKit voice lobby and screenshare, `gamepad` is controller input, and
# `fullscreen` is Big Picture. Denying those would break shipped features, which
# is the usual way this header gets reverted.
PERMISSIONS_POLICY = ', '.join([
    'accelerometer=()',
    'camera=(self)',
    'display-capture=(self)',
    'fullscreen=(self)',
    'gamepad=(self)',
    'geolocation=()',
    'gyroscope=()',
    'interest-cohort=()',
    'magnetometer=()',
    'microphone=(self)',
    'payment=()',
    'usb=()',
])


def _csp_directives() -> dict[str, str]:
    """The policy, as directive → value.

    Kept as a dict so tests can assert one directive without string-matching
    the whole header.
    """
    return {
        'default-src': "'self'",
        'script-src': "'self'",
        'style-src': "'self' 'unsafe-inline'",
        # Cover art and screenshots come from whichever metadata provider the
        # operator configured (IGDB, SteamGridDB, Giant Bomb, Meta Quest, store
        # CDNs). Enumerating them would go stale on the next provider.
        'img-src': "'self' data: blob: https:",
        'font-src': "'self' data:",
        'media-src': "'self' data: blob: https:",
        # wss: is the LiveKit voice lobby and the SSE/WebSocket surfaces.
        'connect-src': "'self' https: wss:",
        'worker-src': "'self' blob:",
        'frame-src': "'self' https:",
        'object-src': "'none'",
        'base-uri': "'self'",
        'form-action': "'self'",
        'frame-ancestors': "'self'",
    }


def build_csp() -> str:
    """Render the policy as a header value."""
    return '; '.join(f'{key} {value}' for key, value in _csp_directives().items())


def baseline_static_headers() -> list[tuple[bytes, bytes]]:
    """Baseline headers as ASGI byte tuples, for the native static handler."""
    return [
        (key.encode('ascii'), value.encode('ascii'))
        for key, value in BASELINE_HEADERS.items()
    ]


def security_header_values(config: Mapping[str, object]) -> dict[str, str]:
    """Return the shared security headers for a Flask or native ASGI response."""
    values = dict(BASELINE_HEADERS)
    values['Permissions-Policy'] = PERMISSIONS_POLICY
    if config.get('CSP_ENABLED', True):
        key = (
            'Content-Security-Policy'
            if config.get('CSP_ENFORCE', True)
            else 'Content-Security-Policy-Report-Only'
        )
        values[key] = build_csp()

    # HSTS is meaningless over plain HTTP and actively hostile on a LAN box
    # reached by IP, so it follows the same signal the secure cookie does.
    hsts_seconds = int(config.get('HSTS_SECONDS') or 0)
    if config.get('SESSION_COOKIE_SECURE') and hsts_seconds > 0:
        values['Strict-Transport-Security'] = (
            f'max-age={hsts_seconds}; includeSubDomains'
        )
    return values


def apply_security_headers(app: Flask) -> None:
    """Register the ``after_request`` that stamps every Flask response."""

    header_values = security_header_values(app.config)

    @app.after_request
    def _set_security_headers(response: Response) -> Response:
        for key, value in header_values.items():
            response.headers.setdefault(key, value)
        return response
