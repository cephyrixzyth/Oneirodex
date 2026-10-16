"""Public site origin for invite / share links.

Admin Settings → Site URL is preferred when it is a real non-loopback host.
When that is still the install default, fall back to the host the client
actually reached — but only when that host is one we trust, because these
origins end up inside emails carrying registration and reset tokens. See
`oneirodex.utils.trusted_host` for why the raw `request.url_root` is not safe
to use here.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.trusted_host import (
    host_is_trusted,
    parse_trusted_hosts,
    trusted_origin_from_request,
)

_LOCAL_SITE_DEFAULTS = frozenset({
    '',
    'http://127.0.0.1',
    'http://127.0.0.1:5006',
    'http://localhost',
    'http://localhost:5006',
})


def configured_site_url() -> str:
    # Reading Site URL touches the DB, and this function sits in the password
    # reset path — an unreadable settings row (or no app context, as in a unit
    # test or a worker) must not be what stops a member resetting their
    # password. Falling through is safe: the caller then uses the *trusted*
    # request origin, never an attacker-supplied one.
    try:
        settings = global_settings_row()
    except Exception:
        return ''
    return ((settings.site_url if settings else None) or '').strip().rstrip('/')


def is_local_site_url(url: str) -> bool:
    cleaned = (url or '').strip().rstrip('/')
    if cleaned in _LOCAL_SITE_DEFAULTS:
        return True
    return cleaned.startswith('http://127.0.0.1') or cleaned.startswith('http://localhost')


def public_origin() -> str:
    configured = configured_site_url()
    if configured and not is_local_site_url(configured):
        return configured
    root = trusted_origin_from_request()
    if root:
        return root
    return configured or 'http://127.0.0.1'


def public_origin_for_request(request, config) -> str:
    """Resolve a trusted origin from a native ASGI request without Flask hooks."""
    configured = configured_site_url()
    if configured and not is_local_site_url(configured):
        return configured

    raw_origin = str(request.base_url or '').rstrip('/')
    host = str(request.headers.get('host') or '')
    try:
        parsed = urlsplit(raw_origin)
        port = parsed.port
    except ValueError:
        return configured or 'http://127.0.0.1'
    if (
        parsed.scheme not in {'http', 'https'}
        or not parsed.hostname
        or (port is not None and not 1 <= port <= 65535)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.netloc.casefold() != host.casefold())
    ):
        return configured or 'http://127.0.0.1'

    allowed = parse_trusted_hosts(config.get('TRUSTED_LINK_HOSTS'))
    if not allowed:
        allowed = parse_trusted_hosts(os.getenv('TRUSTED_LINK_HOSTS', ''))
    if not host_is_trusted(host, allowed):
        return configured or 'http://127.0.0.1'
    return raw_origin


def invite_url(token: str) -> str:
    return f'{public_origin()}/register?token={token}'


def site_url_is_configured() -> bool:
    """True when Settings has a non-loopback Site URL (not just request host)."""
    return not is_local_site_url(configured_site_url())
