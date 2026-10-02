"""Which ``Host`` header this install is willing to put inside an email link.

Why this exists
---------------
``send_password_reset_email`` built its link with ``url_for(..., _external=True)``
and :func:`oneirodex.utils.public_origin.public_origin` fell back to
``request.url_root``. Both derive the origin from the request's ``Host`` header,
which the *caller* controls, and neither Flask nor this app sets ``SERVER_NAME``
or validated the host anywhere.

Password reset is unauthenticated, so that was reachable by anyone: POST
``/reset_password_request`` for another member's address with
``Host: attacker.example`` and the victim receives a genuine Oneirodex email
whose reset link — carrying a working token — points at the attacker. Invite
mail had the same shape one step further in (an admin has to trigger it).

Why not a plain allowlist
-------------------------
A strict allowlist that defaults to empty would reject the normal case. A fresh
household install is reached by LAN IP (``http://192.168.50.116:5006``) with no
Site URL configured yet, and refusing that would break the very flow being
protected — the operator would have to fix Site URL *through* a login they can
no longer reset. So the default posture is "private hosts only":

* ``TRUSTED_LINK_HOSTS`` set   → exactly those hosts, nothing else.
* ``TRUSTED_LINK_HOSTS`` unset → loopback, private (RFC1918 / unique-local) and
  link-local addresses, ``localhost``, dotless LAN names, and ``.local`` /
  ``.lan`` / ``.home.arpa`` / ``.internal`` / ``.localdomain`` suffixes. The shared
  address space ``100.64.0.0/10`` (CGNAT, where Tailscale peers live) is **not**
  in that set: :mod:`ipaddress` counts it as neither private nor link-local, so a
  host reached by such an address needs ``TRUSTED_LINK_HOSTS``.

Every realistic LAN install keeps working; ``attacker.example`` stops being a
usable origin. An install genuinely published on a public hostname sets
``TRUSTED_LINK_HOSTS`` (or Site URL, which is preferred over the request host
anyway).
"""

from __future__ import annotations

import ipaddress
import os
from typing import Iterable

from flask import current_app, has_request_context, request

__all__ = [
    'parse_trusted_hosts',
    'split_host_port',
    'is_private_hostname',
    'host_is_trusted',
    'configured_trusted_hosts',
    'trusted_origin_from_request',
]

# Suffixes a household router hands out. Not exhaustive by design — anything
# else needs TRUSTED_LINK_HOSTS, which is the honest signal that the operator meant it.
_PRIVATE_SUFFIXES = ('.local', '.lan', '.home.arpa', '.internal', '.localdomain')


def parse_trusted_hosts(raw: object) -> tuple[str, ...]:
    """Parse ``TRUSTED_LINK_HOSTS`` into a lowercased tuple, order preserved.

    Accepts a comma / semicolon / whitespace separated string or an iterable.
    Entries may carry a port (``oneirodex.example:8443``); see
    :func:`host_is_trusted` for how that is matched.
    """
    if not raw:
        return ()
    if isinstance(raw, (list, tuple, set, frozenset)):
        parts: list[str] = [str(item) for item in raw]
    else:
        parts = str(raw).replace(';', ',').replace(' ', ',').split(',')

    out: list[str] = []
    for part in parts:
        cleaned = part.strip().strip('.').lower()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return tuple(out)


def split_host_port(host: object) -> tuple[str, str]:
    """Split a ``Host`` header into ``(hostname, port)``.

    Handles the bracketed IPv6 form (``[::1]:5006``) and a bare IPv6 literal,
    both of which a naive ``partition(':')`` mangles into a wrong hostname.
    """
    text = str(host or '').strip().lower()
    if not text:
        return ('', '')

    if text.startswith('['):
        end = text.find(']')
        if end == -1:
            return ('', '')
        hostname = text[1:end]
        rest = text[end + 1:]
        port = rest[1:] if rest.startswith(':') else ''
        return (hostname, port)

    if text.count(':') > 1:
        # Bare IPv6 literal — a Host header should bracket it, but do not read
        # the trailing group as a port if it does not.
        return (text, '')

    if ':' in text:
        hostname, _, port = text.partition(':')
        return (hostname, port)

    return (text, '')


def is_private_hostname(hostname: object) -> bool:
    """True for a host that can only mean "somewhere on this LAN"."""
    name = str(hostname or '').strip().strip('.').lower()
    if not name:
        return False

    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        return bool(address.is_private or address.is_loopback or address.is_link_local)

    if name == 'localhost':
        return True
    if '.' not in name:
        # A dotless name resolves through the local search domain only.
        return True
    return name.endswith(_PRIVATE_SUFFIXES)


def host_is_trusted(host: object, allowed: Iterable[str] = ()) -> bool:
    """Is this ``Host`` header one we will hand to a member in an email?

    An explicit allowlist closes the door completely: nothing outside it is
    trusted, private or not. With no allowlist configured, fall back to the
    private-host posture described in the module docstring.
    """
    hostname, port = split_host_port(host)
    if not hostname:
        return False

    entries = tuple(allowed)
    if entries:
        with_port = f'{hostname}:{port}' if port else hostname
        return any(entry in (hostname, with_port) for entry in entries)

    return is_private_hostname(hostname)


def configured_trusted_hosts() -> tuple[str, ...]:
    """``TRUSTED_LINK_HOSTS`` from app config, falling back to the environment."""
    raw: object = None
    try:
        raw = current_app.config.get('TRUSTED_LINK_HOSTS')
    except RuntimeError:
        # No application context — background worker, CLI script, import time.
        raw = None
    if not raw:
        raw = os.getenv('TRUSTED_LINK_HOSTS', '')
    return parse_trusted_hosts(raw)


def trusted_origin_from_request() -> str | None:
    """``request.url_root`` when the Host header is trusted, else ``None``.

    ``None`` is the signal to fall back to configured Site URL rather than to
    quietly use an origin an attacker chose.
    """
    if not has_request_context():
        return None
    if not host_is_trusted(request.host, configured_trusted_hosts()):
        return None
    return (request.url_root or '').rstrip('/') or None
