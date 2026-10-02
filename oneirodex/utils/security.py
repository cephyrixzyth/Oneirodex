"""Security utilities for path validation and outbound URL checks."""

from __future__ import annotations

import errno
import ipaddress
import os
import re
import socket
import stat
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from flask import current_app
from requests.exceptions import RequestException
from requests.models import PreparedRequest


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


def is_safe_path_strict(user_path, allowed_bases):
    """``is_safe_path`` for destructive operations: the path must sit *below* a base.

    ``is_safe_path`` accepts an allowed base itself, which is right for reads
    but fatal for a delete: a ``folder_path`` equal to a library root would
    ``rmtree`` the whole library.
    """
    is_safe, error_message = is_safe_path(user_path, allowed_bases)
    if not is_safe:
        return is_safe, error_message
    try:
        resolved = Path(user_path.strip()).resolve(strict=False)
        for base in allowed_bases:
            if base and resolved == Path(base).resolve(strict=False):
                return False, "Access denied - path is a library root, not an item inside it"
    except (OSError, ValueError):
        return False, "Invalid path format"
    return True, None


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


def _mac_fold(name: str) -> str:
    """A macOS path the way its volume compares it: ignoring case and normalisation."""
    return unicodedata.normalize('NFC', name).casefold()


def _is_below(real_base, real_path) -> bool:
    """True when *real_path* is strictly below *real_base*; both already resolved."""
    base, path = str(real_base), str(real_path)
    if os.name == 'nt':
        # ``realpath`` keeps a ``\\?\`` prefix on paths it cannot shorten; the
        # descriptor lookup always strips it. Compare them without.
        base, path = _strip_nt_prefix(base), _strip_nt_prefix(path)
    elif sys.platform == 'darwin':
        # F_GETPATH reports the spelling on disk, which need not be the one the
        # library root was typed in (``~/games`` for ``~/Games``).
        base, path = _mac_fold(base), _mac_fold(path)
    base_path, below = Path(base), Path(path)
    return below != base_path and below.is_relative_to(base_path)


def _boundary(base, base_is_resolved: bool) -> str:
    """The string a file's real location is compared against.

    ``base_is_resolved`` says the caller already ran ``realpath`` on *base* and
    vetted the result at the start of its operation. It is then taken as given:
    a folder swapped for a link *after* that point makes its files look outside
    it, instead of the boundary moving to the link's target along with them.
    """
    return os.path.abspath(base) if base_is_resolved else os.path.realpath(base)


def is_path_within(base, path, *, base_is_resolved: bool = False) -> bool:
    """True when *path* resolves to somewhere strictly below *base*.

    *path* goes through ``realpath``, so a symlink anywhere in it that leaves
    *base* makes this False, and ``..`` segments cannot talk their way out.
    *base* is resolved too, unless ``base_is_resolved`` says it already was (see
    :func:`_boundary`). *base* is not "within" itself: callers ask about files.
    """
    try:
        return _is_below(_boundary(base, base_is_resolved), os.path.realpath(path))
    except (OSError, ValueError, TypeError):
        return False


def is_plain_file_within(base, path, *, base_is_resolved: bool = False) -> bool:
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
    return is_path_within(base, path, base_is_resolved=base_is_resolved)


def _path_from_proc(fd: int) -> str | None:
    """Linux: ``/proc/self/fd/N`` is a link to wherever the descriptor points."""
    try:
        target = os.readlink(f'/proc/self/fd/{fd}')
    except (OSError, ValueError):
        return None
    return target if os.path.isabs(target) else None


def _path_from_f_getpath(fd: int) -> str | None:
    """macOS: ``fcntl(F_GETPATH)`` fills a buffer with the descriptor's path."""
    if sys.platform != 'darwin':
        return None
    try:
        import fcntl

        raw = fcntl.fcntl(fd, getattr(fcntl, 'F_GETPATH', 50), bytes(1024))
    except (ImportError, OSError, ValueError):
        return None
    target = os.fsdecode(raw.split(b'\0', 1)[0])
    return target if os.path.isabs(target) else None


def _strip_nt_prefix(name: str) -> str:
    r"""``\\?\C:\x`` -> ``C:\x`` and ``\\?\UNC\srv\share\x`` -> ``\\srv\share\x``."""
    if name.startswith('\\\\?\\UNC\\'):
        return '\\\\' + name[8:]
    if name.startswith('\\\\?\\'):
        return name[4:]
    return name


def _path_from_handle(fd: int) -> str | None:
    """Windows: ``GetFinalPathNameByHandleW`` on the descriptor's OS handle."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(fd)
        final_path = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
        final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        final_path.restype = wintypes.DWORD
        size = 1024
        for _ in range(2):  # the second pass has the length the first one asked for
            buffer = ctypes.create_unicode_buffer(size)
            length = final_path(handle, buffer, size, 0)
            if length == 0:
                return None
            if length < size:
                target = _strip_nt_prefix(buffer.value)
                return target if os.path.isabs(target) else None
            size = length + 1
    except (ImportError, OSError, ValueError, AttributeError):
        pass
    return None


def _opened_path(fd: int) -> str | None:
    """The path the OS reports for an open descriptor, else None.

    Linux has ``/proc/self/fd``, macOS has ``fcntl(F_GETPATH)`` and Windows has
    ``GetFinalPathNameByHandleW``. Each is a question to the kernel about the
    *descriptor*, so the answer cannot be changed by renaming things afterwards.
    A platform with none of them (or a container without ``/proc``) gets None.
    """
    for lookup in (_path_from_proc, _path_from_f_getpath, _path_from_handle):
        located = lookup(fd)
        if located:
            return located
    return None


def open_plain_file_within(base, path, *, base_is_resolved: bool = False):
    """Open *path* for binary reading, but only if it is a plain file under *base*.

    :func:`is_plain_file_within` answers "is it safe *now*"; a folder that
    someone else can write to can change between that answer and the ``open``
    that follows (``big.bin`` swapped for a link to ``/app/.env``). This opens
    first and checks the descriptor it got, so what is read is what was vetted:

    * ``O_NOFOLLOW`` refuses a link as the last path component where the
      platform has it, and ``O_NONBLOCK`` keeps a swapped-in FIFO from hanging
      the open;
    * the descriptor must be a regular file, the path must not be a link, and
      the path must still name that same file (``samestat``), which catches a
      parent directory swapped for a link and covers Windows, which has no
      ``O_NOFOLLOW``;
    * the file must be under *base*. Where the OS can say what the descriptor
      points at (``/proc/self/fd`` on Linux, ``F_GETPATH`` on macOS,
      ``GetFinalPathNameByHandleW`` on Windows; see :func:`_opened_path`) that
      answer is checked, so a parent directory swapped for a link and back
      between the checks cannot pass. Only where none of them works is the
      path's realpath checked, and that is weaker: the path is resolved
      *after* the open, so a determined swap can still get past it. The path
      is then re-checked against the descriptor last, which narrows the window
      but does not close it.

    ``base_is_resolved=True`` takes *base* as an already-resolved path (see
    :func:`_boundary`), so a caller serving many files from one folder can
    resolve and vet the folder once instead of re-resolving it per file.

    Raises ``OSError`` for anything else; the caller decides whether that skips
    the file or stops the operation.
    """
    flags = (
        os.O_RDONLY
        | getattr(os, 'O_NOFOLLOW', 0)
        | getattr(os, 'O_BINARY', 0)
        | getattr(os, 'O_NONBLOCK', 0)
    )
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(errno.EINVAL, 'not a regular file')
        located = _opened_path(fd)
        if located is not None:
            inside = _is_below(_boundary(base, base_is_resolved), located)
        else:
            inside = is_path_within(base, path, base_is_resolved=base_is_resolved)
        if not inside:
            raise OSError(errno.EACCES, 'file is outside its folder')
        # Last, so that without a descriptor path a parent swapped back after
        # the realpath above leaves ``path`` naming a different file than ``fd``.
        if os.path.islink(path) or not os.path.samestat(opened, os.stat(path)):
            raise OSError(errno.ELOOP, 'path no longer names the file that was opened')
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


#: Instance-metadata endpoints that are not link-local, so the ``is_link_local``
#: test misses them, or that are globally routable and so pass the "not global"
#: test. Alibaba's sits in the shared address space; AWS's IPv6 endpoint and
#: its DNS resolver are ULAs; Oracle's is the IANA service-continuity block
#: (192.0.0.0/24), which the LAN flag reopens as "not global"; Azure's wire
#: server 168.63.129.16 is an ordinary public address. All of them stay
#: blocked even when ``ALLOW_PRIVATE_LAN_URLS`` reopens private ranges, and
#: ``_is_blocked_ip`` refuses them outright.
_CLOUD_METADATA_HOSTS = frozenset({
    'metadata.google.internal',
    '169.254.169.254',
    '100.100.100.200',
    '168.63.129.16',
    '192.0.0.192',
    'fd00:ec2::254',
    'fd00:ec2::23',
})


#: IPv6 prefixes that carry an IPv4 address in their low bits (RFC 6052 NAT64,
#: RFC 8215 local-use NAT64, the deprecated IPv4-compatible form, and the
#: RFC 2765/6145 SIIT "translated" form). ``ipaddress`` unwraps only the mapped,
#: 6to4 and Teredo forms on its own.
_NAT64_WELL_KNOWN = ipaddress.ip_network('64:ff9b::/96')
_NAT64_LOCAL_USE = ipaddress.ip_network('64:ff9b:1::/48')
_IPV4_COMPATIBLE = ipaddress.ip_network('::/96')
_IPV4_TRANSLATED = ipaddress.ip_network('::ffff:0:0:0/96')

#: Byte offsets of the four IPv4 octets inside a ``64:ff9b:1::/48`` address, one
#: tuple per RFC 6052 prefix length that fits in a /48 (48, 56, 64 and 96). The
#: translator picks the length, not us, and byte 8 is the reserved "u" octet.
_NAT64_LOCAL_USE_OCTETS = ((6, 7, 9, 10), (7, 9, 10, 11), (9, 10, 11, 12), (12, 13, 14, 15))


def _embedded_ipv4(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """Every IPv4 address *ip* wraps, so a rule written for the IPv4 form also covers these.

    ``http://[64:ff9b::a9fe:a9fe]/`` is 169.254.169.254 to a NAT64 gateway, and
    ``[2002:a9fe:a9fe::1]`` is the same address to a 6to4 relay; a check that
    only looks at the IPv6 spelling never asks the right question. Whether a
    given network translates them is not ours to know, so they are all treated
    as the address they wrap.
    """
    if ip.version != 6:
        return []
    found = []
    for wrapped in (ip.ipv4_mapped, ip.sixtofour):
        if wrapped is not None:
            found.append(wrapped)
    if ip.teredo is not None:
        found.extend(ip.teredo)  # (server, obfuscated client)
    octets = ip.packed
    if ip in _NAT64_WELL_KNOWN or ip in _IPV4_COMPATIBLE or ip in _IPV4_TRANSLATED:
        found.append(ipaddress.IPv4Address(octets[12:]))
    elif ip in _NAT64_LOCAL_USE:
        for positions in _NAT64_LOCAL_USE_OCTETS:
            found.append(ipaddress.IPv4Address(bytes(octets[i] for i in positions)))
    return found


def _is_blocked_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        str(ip) in _CLOUD_METADATA_HOSTS
        or ip.is_private
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


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for any address an outbound fetch has no business reaching."""
    # An IPv4-mapped IPv6 literal (``::ffff:127.0.0.1``) reports False for
    # is_loopback on its own, so unwrap it before asking.
    mapped = getattr(ip, 'ipv4_mapped', None)
    if mapped is not None:
        ip = mapped
    # The local-use NAT64 block is somebody's translator, never a public host,
    # whatever the address inside it says.
    if ip in _NAT64_LOCAL_USE:
        return True
    # A wrapper that ``ipaddress`` classifies differently on another Python
    # version must not hide a blocked IPv4 address inside it.
    return _is_blocked_address(ip) or any(_is_blocked_address(inner) for inner in _embedded_ipv4(ip))


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
        # The address itself and every IPv4 address it wraps (mapped, NAT64,
        # 6to4, Teredo, IPv4-compatible, SIIT): the LAN flag never reopens these.
        for address in (ip, *_embedded_ipv4(ip)):
            if address.is_link_local or str(address) in _CLOUD_METADATA_HOSTS:
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


#: What RFC 3986 lets into an authority (userinfo, host and port): unreserved
#: characters, sub-delims, ``:`` ``@`` ``[`` ``]`` and ``%XX`` escapes. Non-ASCII
#: passes so an internationalised host name is not refused by this test alone;
#: the comparison in :func:`url_authority_is_unambiguous` rules on those.
_AUTHORITY_RE = re.compile(r"(?:[A-Za-z0-9\-._~!$&'()*+,;=:@\[\]]|%[0-9A-Fa-f]{2}|[^\x00-\x7f])*")


def url_authority_is_unambiguous(url: str) -> bool:
    """True when ``urlparse`` and ``requests`` read the same host and port from *url*.

    The validators judge the host ``urlparse`` returns; ``requests`` dials the
    host it builds the request URL from (urllib3's parse, then percent-decoding
    of unreserved characters). They differ in ``http://127.0.0.1\\@example.com/``
    (urllib3 ends the authority at a backslash, Python does not),
    ``http://127.0.0.%31/`` and ``http://localhost%2e/``, so those passed the host
    check and the address pin alike. A URL the two disagree about, or one with
    characters RFC 3986 does not allow in an authority, is refused rather than
    interpreted.
    """
    try:
        parsed = urlparse(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return False
    if not host or not _AUTHORITY_RE.fullmatch(parsed.netloc):
        return False
    if not host.isascii():
        try:
            host = host.encode('idna').decode('ascii')
        except UnicodeError:
            return False
    try:
        # The URL requests will hand its adapter: ``prepare_url`` is what
        # ``Session.request`` runs on it.
        prepared = PreparedRequest()
        prepared.prepare_url(url, None)
        dialed = urlparse(prepared.url)
        return (dialed.hostname or '').lower() == host.lower() and dialed.port == port
    except (RequestException, ValueError):
        return False


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
    if not url_authority_is_unambiguous(candidate):
        return False, 'Invalid URL'
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
    if not url_authority_is_unambiguous(candidate):
        return False, 'Invalid community chat URL'
    return True, candidate
