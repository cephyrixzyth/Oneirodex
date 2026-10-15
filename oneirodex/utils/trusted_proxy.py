"""Helpers for authenticating reverse-proxy forwarded headers."""
from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping


def trusted_proxy_address(raw_peer: str | None, config: Mapping | None = None) -> bool:
    """Return whether an immediate peer address is in configured proxy CIDRs.

    TRUSTED_PROXIES controls how many forwarded hops to read. It does not
    establish which peer is allowed to supply those headers; that boundary is
    configured separately with TRUSTED_PROXY_CIDRS.
    """
    if not raw_peer:
        return False
    try:
        peer = ipaddress.ip_address(raw_peer)
    except ValueError:
        return False

    configured = None
    if config is not None:
        configured = config.get('TRUSTED_PROXY_CIDRS')
    if configured is None:
        configured = os.getenv('TRUSTED_PROXY_CIDRS', '')
    if isinstance(configured, str):
        entries = configured.replace(';', ',').split(',')
    else:
        try:
            entries = list(configured)
        except TypeError:
            entries = []

    for entry in entries:
        try:
            network = ipaddress.ip_network(str(entry).strip(), strict=False)
        except ValueError:
            continue
        if peer.version == network.version and peer in network:
            return True
        if peer.version == 6 and peer.ipv4_mapped and network.version == 4:
            if peer.ipv4_mapped in network:
                return True
    return False


def trusted_proxy_peer(request, config: Mapping | None = None) -> bool:
    """Return whether the immediate ASGI peer is in configured proxy CIDRs."""
    client = getattr(request, 'client', None)
    return trusted_proxy_address(getattr(client, 'host', None), config)


def trusted_forwarded_for(request, config: Mapping | None = None) -> str | None:
    """Return the validated forwarded client IP for a configured proxy chain."""
    if not trusted_proxy_peer(request, config):
        return None
    try:
        trusted_hops = max(0, int((config or {}).get('TRUSTED_PROXIES') or 0))
    except (TypeError, ValueError):
        trusted_hops = 0
    if not trusted_hops:
        return None
    forwarded = forwarded_client_ip(request, config)
    peer = getattr(request, 'client', None)
    peer_address = getattr(peer, 'host', None) if peer else None
    return forwarded if forwarded != str(peer_address or 'unknown') else None


def forwarded_client_ip(request, config: Mapping | None = None) -> str:
    """Resolve a client IP only when the immediate peer is a trusted proxy."""
    client = getattr(request, 'client', None)
    address = (getattr(client, 'host', None) if client else None) or 'unknown'
    if not trusted_proxy_peer(request, config):
        return str(address)[:64]

    try:
        trusted_hops = max(0, int((config or {}).get('TRUSTED_PROXIES') or 0))
    except (TypeError, ValueError):
        trusted_hops = 0
    forwarded = request.headers.get('X-Forwarded-For')
    if trusted_hops and forwarded:
        from werkzeug.http import parse_list_header

        hops = parse_list_header(forwarded)
        if len(hops) >= trusted_hops:
            candidate = hops[-trusted_hops]
            try:
                return str(ipaddress.ip_address(candidate))[:64]
            except ValueError:
                pass
    return str(address)[:64]
