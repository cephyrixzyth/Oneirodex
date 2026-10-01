"""Security utilities for path validation and outbound URL checks."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from flask import current_app


#: ``/home/alice``, ``/Users/alice`` and ``C:\Users\alice`` all name a person.
#: Matches the home-directory word, its separator, and the one segment after it.
_USER_DIR_RE = re.compile(r'([Uu]sers?|[Hh]ome)([/\\])[^/\\]+')


def is_safe_path(user_path, allowed_bases):
    """Securely validate that a user-provided path is within allowed directories."""
    if not user_path or not isinstance(user_path, str):
        return False, "Invalid path format"

    user_path = user_path.strip()
    if not user_path:
        return False, "Empty path"

    if '\x00' in user_path:
        return False, "Invalid path format"

    if len(user_path) > 4096:
        return False, "Path too long"

    try:
        user_path_obj = Path(user_path).resolve(strict=False)

        for base in allowed_bases:
            if not base:
                continue

            try:
                base_path_obj = Path(base).resolve(strict=False)
                try:
                    user_path_obj.relative_to(base_path_obj)
                    return True, None
                except ValueError:
                    continue

            except (OSError, ValueError) as e:
                current_app.logger.warning(f"Invalid base path {sanitize_path_for_logging(base)}: {e}")
                continue

        return False, "Access denied - path outside allowed directories"

    except (OSError, ValueError) as e:
        current_app.logger.warning(f"Path validation error for {sanitize_path_for_logging(user_path)}: {e}")
        return False, "Invalid path format"


def get_allowed_base_directories(app):
    """Get allowed base directories from app configuration.

    Every path-sensitive route funnels through here, so the extra scan
    locations declared in ``ONEIRODEX_LIBRARY_ROOTS`` are appended in one place rather
    than being threaded through scan, download, delete, storage and export
    individually.
    """
    allowed_bases = []
    games = app.config.get('DATA_FOLDER_GAMES')
    if games:
        allowed_bases.append(games)
    config_keys = ['BASE_FOLDER_WINDOWS', 'BASE_FOLDER_POSIX']
    for key in config_keys:
        base_path = app.config.get(key)
        if base_path:
            allowed_bases.append(base_path)

    from oneirodex.utils.library_roots import library_root_paths, same_path

    for root_path in library_root_paths(app):
        # Compared as paths, not as strings: a root written "/games" and a
        # DATA_FOLDER_GAMES of "/games/" are one directory, and listing it
        # twice would only make the allowlist harder to read in logs.
        if not any(same_path(root_path, existing) for existing in allowed_bases):
            allowed_bases.append(root_path)
    return allowed_bases


def sanitize_path_for_logging(path, max_length=100):
    """Sanitize path for safe logging by truncating and masking sensitive parts."""
    if not path or not isinstance(path, str):
        return "[INVALID_PATH]"

    if len(path) > max_length:
        truncated = f"{path[:30]}...{path[-(max_length - 33):]}"
    else:
        truncated = path

    # One rule for both separators. The three it replaces were POSIX-only twice
    # over: the Windows rule was written `\\\\[Uu]sers\\\\`, which the regex
    # engine reads as *two* literal backslashes, and a Windows path has one — so
    # it never matched anything, and on a Windows host nothing was scrubbed at
    # all. Separator and casing are preserved so the log still reads naturally.
    sanitized = _USER_DIR_RE.sub(r'\1\2[USER]', truncated)

    return sanitized


def is_path_within(base, path) -> bool:
    """True when *path* resolves to somewhere strictly below *base*.

    Both sides go through ``realpath``, so a symlink anywhere in *path* that
    leaves *base* makes this False, and ``..`` segments cannot talk their way
    out. *base* is not "within" itself: callers ask about files.
    """
    try:
        real_base = Path(os.path.realpath(base))
        real_path = Path(os.path.realpath(path))
        return real_path != real_base and real_path.is_relative_to(real_base)
    except (OSError, ValueError, TypeError):
        return False


def is_plain_file_within(base, path) -> bool:
    """True for a regular file under *base* that is not itself a symlink.

    Game folders are scanned, not authored by the operator: a
    ``game.bin -> /etc/whatever`` link inside one must not be hashed, bundled,
    zipped or served. Symlinks are skipped outright (a link to another file in
    the same folder is not worth the ambiguity) and the realpath check catches
    the case where a parent directory is the link.
    """
    try:
        if os.path.islink(path) or not os.path.isfile(path):
            return False
    except (OSError, ValueError):
        return False
    return is_path_within(base, path)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address an outbound fetch has no business reaching."""
    # An IPv4-mapped IPv6 literal (``::ffff:127.0.0.1``) reports False for
    # is_loopback on its own, so unwrap it before asking.
    mapped = getattr(ip, 'ipv4_mapped', None)
    if mapped is not None:
        ip = mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        # Shared address space (RFC 6598, 100.64.0.0/10) is neither private nor
        # reserved to the ipaddress module, yet it is where Tailscale peers and
        # Alibaba's metadata service (100.100.100.200) live. Anything that is
        # not globally routable is not somewhere a public-facing fetch belongs;
        # the homelab flag reopens it for admin connectors the same way it
        # reopens RFC1918.
        or not ip.is_global
    )


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse *host* as an IP literal, including the forms ``ip_address`` rejects.

    ``http://2130706433/`` and ``http://0x7f.0.0.1/`` are both 127.0.0.1 to a
    resolver but raise ValueError in ``ipaddress``. ``inet_aton`` accepts the
    decimal, octal and hex dotted forms, which is exactly the gap.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def _resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address *host* currently resolves to. Empty when it does not resolve."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return []
    found = []
    for info in infos:
        candidate = _parse_ip_literal(info[4][0])
        if candidate is not None:
            found.append(candidate)
    return found


def is_blocked_outbound_host(hostname: str | None, *, resolve: bool = True) -> bool:
    """Block SSRF targets — localhost, link-local, and private/loopback addresses.

    Checking the *literal* only is not enough: ``http://attacker.example/`` that
    resolves to 127.0.0.1 or 169.254.169.254 passed every check here, which
    defeated ``validate_user_outbound_http_url`` entirely despite its docstring
    promising never to reach the LAN. So a name that is not itself an IP gets
    resolved and every returned address is checked.

    A host that does not resolve is *not* blocked: the fetch cannot connect
    either, and failing closed here would reject legitimate connector URLs saved
    while DNS happens to be down.

    Residual risk without a pin: this is resolve-then-connect, so a DNS rebind
    between the check and the socket still wins. ``http_safe.safe_request``
    closes that by dialing the address that just passed the check and putting
    the original hostname on ``Host`` / SNI. Callers that bypass ``safe_request``
    still have the hole.
    """
    if not hostname:
        return True
    host = hostname.strip().lower().rstrip('.')
    if host in {'localhost', 'metadata.google.internal'} or host.endswith('.local'):
        return True
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]

    literal = _parse_ip_literal(host)
    if literal is not None:
        return _is_blocked_ip(literal)

    if not resolve:
        return False

    resolved = _resolve_host(host)
    return any(_is_blocked_ip(ip) for ip in resolved)


#: Instance-metadata endpoints that are not link-local, so the ``is_link_local``
#: test misses them: Alibaba's sits in the shared address space that
#: ``_is_blocked_ip`` now refuses, and AWS's IPv6 endpoint is a ULA. Both would
#: otherwise come back when ``ALLOW_PRIVATE_LAN_URLS`` reopens private ranges.
_CLOUD_METADATA_HOSTS = frozenset({
    'metadata.google.internal',
    '169.254.169.254',
    '100.100.100.200',
    'fd00:ec2::254',
})


def is_cloud_metadata_host(hostname: str | None) -> bool:
    """True for a cloud instance-metadata endpoint, by name or by resolution.

    Kept separate from :func:`is_blocked_outbound_host` because this one stays
    blocked even when ``ALLOW_PRIVATE_LAN_URLS`` reopens RFC1918 for homelab
    connectors — reaching a NAS is the point, reaching 169.254.169.254 never is.
    """
    if not hostname:
        return True
    host = hostname.strip().lower().rstrip('.')
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
    if host in _CLOUD_METADATA_HOSTS:
        return True

    literal = _parse_ip_literal(host)
    candidates = [literal] if literal is not None else _resolve_host(host)
    for ip in candidates:
        mapped = getattr(ip, 'ipv4_mapped', None)
        if mapped is not None:
            ip = mapped
        if ip.is_link_local or str(ip) in _CLOUD_METADATA_HOSTS:
            return True
    return False


def allow_private_lan_urls_enabled() -> bool:
    """Homelab opt-in: allow private/RFC1918 hosts for *arr / Ollama connectors."""
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            return bool(current_app.config.get('ALLOW_PRIVATE_LAN_URLS'))
    except Exception:
        pass
    import os

    return os.getenv('ALLOW_PRIVATE_LAN_URLS', 'false').lower() in ('1', 'true', 'yes')


def validate_outbound_http_url(
    url: str,
    *,
    allow_http: bool = False,
    allow_private_lan: bool | None = None,
    allowed_hostnames: set[str] | None = None,
) -> tuple[bool, str]:
    """Validate an outbound http(s) URL for SSRF-sensitive server fetches."""
    if not url or not isinstance(url, str):
        return False, 'URL required'
    candidate = url.strip()
    if candidate.startswith('//'):
        candidate = 'https:' + candidate
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False, 'Invalid URL'
    if parsed.scheme not in ({'http', 'https'} if allow_http else {'https'}):
        return False, 'URL scheme not allowed'
    if not parsed.hostname:
        return False, 'URL host required'
    lan_ok = allow_private_lan_urls_enabled() if allow_private_lan is None else bool(allow_private_lan)
    if is_blocked_outbound_host(parsed.hostname):
        # Homelab installs legitimately point connectors at RFC1918 hosts, so
        # ALLOW_PRIVATE_LAN_URLS reopens those — but never cloud metadata, which
        # is checked against the *resolved* addresses too, not just the literal.
        # A name resolving to 169.254.169.254 used to walk straight through here.
        if not lan_ok or is_cloud_metadata_host(parsed.hostname):
            return False, 'URL host is not allowed'
    if allowed_hostnames is not None and parsed.hostname.lower() not in {
        h.lower() for h in allowed_hostnames
    }:
        return False, 'URL host is not on the allowlist'
    return True, candidate


def validate_connector_http_url(url: str) -> tuple[bool, str]:
    """Admin-configured *arr / Ollama base URLs — respects ALLOW_PRIVATE_LAN_URLS."""
    return validate_outbound_http_url(url, allow_http=True)


def validate_user_outbound_http_url(url: str) -> tuple[bool, str]:
    """User/indexer/metadata fetches — never LAN even if the homelab flag is on."""
    return validate_outbound_http_url(url, allow_http=True, allow_private_lan=False)


def validate_community_chat_url(url: str) -> tuple[bool, str]:
    """BYO community link — http(s); block private/localhost hosts."""
    if not url:
        return True, ''
    candidate = url.strip()
    if not (candidate.startswith('http://') or candidate.startswith('https://')):
        return False, 'Community chat URL must start with http:// or https://'
    if len(candidate) > 512:
        return False, 'Community chat URL is too long'
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False, 'Invalid community chat URL'
    if is_blocked_outbound_host(parsed.hostname):
        return False, 'Community chat URL host is not allowed'
    return True, candidate
