"""Household game server registry helpers and health probes."""

from __future__ import annotations

import logging
import re
import socket
from typing import Any
from urllib.parse import urlparse

import requests

from oneirodex.utils.http_safe import BlockedOutboundUrl, safe_request
from oneirodex.utils.security import validate_connector_http_url

logger = logging.getLogger(__name__)

_CONNECT_RE = re.compile(
    r'^(?:(?:tcp|udp)://)?(?P<host>[^:\s]+)(?::(?P<port>\d+))?$',
    re.I,
)


def parse_connect_string(connect_string: str | None) -> tuple[str | None, int | None]:
    """Parse host:port from a connect string."""
    raw = (connect_string or '').strip()
    if not raw:
        return None, None
    if '://' in raw:
        parsed = urlparse(raw)
        host = parsed.hostname
        port = parsed.port
        if host and port:
            return host, port
        if host:
            return host, None
    match = _CONNECT_RE.match(raw)
    if not match:
        return None, None
    host = match.group('host')
    port_text = match.group('port')
    port = int(port_text) if port_text else None
    return host, port


def probe_server_health(
    connect_string: str | None,
    health_url: str | None,
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Best-effort HTTP or TCP health check for a registered server."""
    url = (health_url or '').strip()
    if url.lower().startswith(('http://', 'https://')):
        try:
            # Admin-set URL, member-triggered probe: every hop (the redirects
            # ``urlopen`` used to follow unchecked) goes through the same
            # LAN-aware policy the other admin connectors use. Household game
            # servers live on the LAN, so private ranges stay reachable while
            # ALLOW_PRIVATE_LAN_URLS is on; cloud metadata never is.
            response = safe_request(
                'GET', url, validator=validate_connector_http_url, timeout=timeout,
            )
            try:
                status = int(response.status_code)
            finally:
                response.close()
            reachable = 200 <= status < 400
            return {
                'reachable': reachable,
                'method': 'http',
                'status_code': status,
                'error': None if reachable else f'HTTP {status}',
            }
        except (requests.RequestException, OSError, ValueError, TimeoutError) as exc:
            # Fixed text: the exception string names hosts, ports and resolver
            # failures, and this goes back to every member who asks for status.
            logger.info('game server health probe failed: %s', type(exc).__name__)
            return {
                'reachable': False,
                'method': 'http',
                'status_code': None,
                'error': (
                    'Health URL is not allowed by the outbound policy'
                    if isinstance(exc, BlockedOutboundUrl)
                    else 'Health URL unreachable'
                ),
            }

    host, port = parse_connect_string(connect_string)
    if not host:
        return {
            'reachable': None,
            'method': None,
            'status_code': None,
            'error': 'No health URL or connect string',
        }
    if port is None:
        port = 25565
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return {
                'reachable': True,
                'method': 'tcp',
                'status_code': None,
                'error': None,
            }
    except OSError as exc:
        logger.info('game server tcp probe failed: %s', type(exc).__name__)
        return {
            'reachable': False,
            'method': 'tcp',
            'status_code': None,
            'error': 'Connection failed',
        }
