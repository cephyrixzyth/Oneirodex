"""Outbound HTTP that keeps its promise across redirects.

The SSRF validators in :mod:`oneirodex.utils.security` check the URL a caller
*asked for*. ``requests`` follows redirects by default, so the URL actually
fetched could be a different one entirely — a validated host answering ``302
Location: http://169.254.169.254/`` walked straight past every check in the
tree. There was no ``allow_redirects=False`` anywhere in application code.

So redirects are followed here instead, one hop at a time, revalidating before
each one. Same behaviour a caller already expects; the difference is that the
policy applies to every hop rather than only the first.

A second hole sat behind the first: the host check is resolve-then-connect, so
a name that is public at check time can rebind to a private address before the
socket opens. Each hop is therefore dialed by the address that just passed the
validator, with the original hostname restored on ``Host`` / SNI so TLS and
virtual hosts still work.

Callers pass the validator that matches their trust level — usually
``validate_user_outbound_http_url`` (never LAN) for provider/indexer/metadata
fetches, or ``validate_connector_http_url`` (LAN allowed when the homelab flag
is on) for admin-configured connectors.
"""

from __future__ import annotations

from copy import copy
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter

from oneirodex.utils import security

DEFAULT_MAX_REDIRECTS = 5

Validator = Callable[[str], tuple[bool, str]]

# Unknown headers may be provider credentials (for example Nexus's `apikey`).
_REDIRECT_HEADERS = frozenset({
    'accept', 'accept-encoding', 'accept-language', 'user-agent', 'range',
    'if-range', 'if-none-match', 'if-modified-since',
    'content-type', 'content-length', 'transfer-encoding',
})


def _origin(url):
    parsed = urlparse(url)
    return parsed.scheme.lower(), parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)


def _body_positions(kwargs):
    """Record stream positions before the first send for method-preserving hops."""
    values = [kwargs.get('data')]
    files = kwargs.get('files') or {}
    for _, value in (files.items() if hasattr(files, 'items') else files):
        values.append(value[1] if isinstance(value, (tuple, list)) else value)
    positions = []
    for value in values:
        if hasattr(value, 'read'):
            try:
                positions.append((value, value.tell()))
            except (AttributeError, OSError):
                positions.append((value, None))
        elif value is not None and not isinstance(value, (str, bytes, bytearray, dict, list, tuple)):
            positions.append((value, None))
    return positions


def _rewind_body(positions):
    for stream, position in positions:
        try:
            if position is None:
                raise OSError
            stream.seek(position)
        except (AttributeError, OSError, ValueError):
            raise requests.exceptions.UnrewindableBodyError('Cannot replay redirect request body') from None


class BlockedOutboundUrl(requests.RequestException):
    """A hop in the redirect chain failed the validator."""

    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f'Blocked outbound URL: {reason}')


class _HostHeaderSSLAdapter(HTTPAdapter):
    """Verify TLS against the Host header while the URL host is a pinned IP."""

    def send(self, request, **kwargs):
        pool_kw = self.poolmanager.connection_pool_kw
        hostname = None
        parsed = urlparse(request.url) if request.url else None
        if parsed is not None and parsed.scheme == 'https':
            host_header = request.headers.get('Host') or request.headers.get('host')
            if host_header:
                hostname = _hostname_from_host_header(host_header)
        pushed = {}
        if hostname:
            pushed['assert_hostname'] = pool_kw.get('assert_hostname')
            pushed['server_hostname'] = pool_kw.get('server_hostname')
            pool_kw['assert_hostname'] = hostname
            pool_kw['server_hostname'] = hostname
        try:
            return super().send(request, **kwargs)
        finally:
            if hostname:
                for key, old in pushed.items():
                    if old is None:
                        pool_kw.pop(key, None)
                    else:
                        pool_kw[key] = old


def _hostname_from_host_header(value: str) -> str:
    value = value.strip()
    if value.startswith('['):
        end = value.find(']')
        return value[1:end] if end != -1 else value
    if value.count(':') == 1:
        return value.split(':', 1)[0]
    return value


def _validated(url: str, validator: Validator) -> str:
    ok, result = validator(url)
    if not ok:
        raise BlockedOutboundUrl(url, result)
    return result


def _host_header(parsed) -> str:
    host = parsed.hostname or ''
    if ':' in host:
        host = f'[{host}]'
    port = parsed.port
    if port is None:
        return host
    default = 443 if parsed.scheme == 'https' else 80
    if port == default:
        return host
    return f'{host}:{port}'


def _replace_host_with_ip(url: str, ip: str) -> str:
    parsed = urlparse(url)
    hostport = f'[{ip}]' if ':' in ip else ip
    if parsed.port is not None:
        hostport = f'{hostport}:{parsed.port}'
    if parsed.username is not None:
        auth = parsed.username
        if parsed.password is not None:
            auth += f':{parsed.password}'
        hostport = f'{auth}@{hostport}'
    return urlunparse((
        parsed.scheme,
        hostport,
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))


def _pin_checked_address(url: str, validator: Validator) -> tuple[str, str | None]:
    """Dial the address the validator just accepted, not whatever DNS says next.

    Returns ``(connect_url, original_hostname)``. *original_hostname* is None
    when the URL already used a literal IP, or when the name does not resolve
    — unresolvable hosts are allowed by the validator and fail at connect.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return url, None
    if security._parse_ip_literal(host) is not None:
        return url, None

    addrs = security._resolve_host(host)
    if not addrs:
        return url, None

    last_reason = 'URL host is not allowed'
    for ip in addrs:
        candidate = _replace_host_with_ip(url, str(ip))
        ok, cleaned = validator(candidate)
        if ok:
            return cleaned, host
        last_reason = cleaned
    raise BlockedOutboundUrl(url, last_reason)


def _ensure_pin_adapter(session: requests.Session) -> None:
    adapter = session.get_adapter('https://example.invalid')
    if isinstance(adapter, _HostHeaderSSLAdapter):
        return
    session.mount('https://', _HostHeaderSSLAdapter())


def safe_request(
    method: str,
    url: str,
    *,
    validator: Validator,
    session: requests.Session | None = None,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    **kwargs,
) -> requests.Response:
    """Perform *method* on *url*, revalidating every redirect hop.

    Raises :class:`BlockedOutboundUrl` if the initial URL or any hop is
    rejected, and ``requests.TooManyRedirects`` past *max_redirects*.
    """
    kwargs.pop('allow_redirects', None)
    caller = session or requests
    if isinstance(caller, requests.Session):
        _ensure_pin_adapter(caller)
    origin = url
    current = _validated(url, validator)
    return _request_loop(
        method, current, validator=validator, caller=caller,
        max_redirects=max_redirects, kwargs=kwargs, origin=origin,
    )


def _send(caller, method: str, url: str, tls_name: str | None, req_kwargs: dict):
    """Dispatch one hop, wrapping a throwaway Session only for HTTPS SNI pin."""
    needs_tls_pin = bool(tls_name) and urlparse(url).scheme == 'https'
    if needs_tls_pin and caller is requests:
        with requests.Session() as owned:
            _ensure_pin_adapter(owned)
            response = owned.request(method, url, allow_redirects=False, **req_kwargs)
            # Body must be read before the pool closes with the context.
            response.content
            return response
    return caller.request(method, url, allow_redirects=False, **req_kwargs)


def _request_loop(
    method: str,
    current: str,
    *,
    validator: Validator,
    caller,
    max_redirects: int,
    kwargs: dict,
    origin: str,
) -> requests.Response:
    method = method.upper()
    positions = _body_positions(kwargs)
    for _ in range(max_redirects + 1):
        connect_url, tls_name = _pin_checked_address(current, validator)
        req_kwargs = dict(kwargs)
        if tls_name:
            headers = dict(req_kwargs.get('headers') or {})
            headers = {k: v for k, v in headers.items() if k.lower() != 'host'}
            headers['Host'] = _host_header(urlparse(current))
            req_kwargs['headers'] = headers

        response = _send(caller, method, connect_url, tls_name, req_kwargs)
        if not response.is_redirect:
            return response

        location = response.headers.get('Location')
        if not location:
            return response

        # Relative Location is legal and common; resolve against the hop we
        # were given (the hostname URL), then validate the absolute result.
        # Joining against the pinned IP would drop the name on the next hop.
        try:
            target = _validated(urljoin(current, location), validator)
            cross_origin = _origin(current) != _origin(target)
            if cross_origin and response.status_code in (307, 308) and any(
                kwargs.get(key) is not None for key in ('data', 'json', 'files')
            ):
                # OAuth/device-auth bodies contain secrets too. Header stripping
                # cannot make their replay to a new origin safe.
                raise BlockedOutboundUrl(target, 'Cross-origin request body replay is not allowed')
            # A Location must not inject new URL credentials, even with a permissive validator.
            if urlparse(target).username is not None:
                raise BlockedOutboundUrl(target, 'Redirect credentials are not allowed')
            kwargs.pop('params', None)
            headers = dict(kwargs.get('headers') or {})
            if isinstance(caller, requests.Session):
                # Detach request defaults, but keep caller-owned transport adapters open.
                redirected = copy(caller)
                redirected.params = {}
                redirected.headers = caller.headers.copy()
                if cross_origin:
                    settings = caller.merge_environment_settings(target, kwargs.get('proxies') or {},
                                                                 kwargs.get('stream'), kwargs.get('verify'), None)
                    kwargs.setdefault('verify', settings['verify'])
                    kwargs.setdefault('proxies', settings['proxies'])
                    redirected.trust_env = False
                    redirected.auth = None
                    redirected.cert = None
                    redirected.cookies = requests.cookies.RequestsCookieJar()
                    redirected.hooks = requests.hooks.default_hooks()
                    redirected.headers = requests.structures.CaseInsensitiveDict({
                        k: v for k, v in redirected.headers.items() if k.lower() in _REDIRECT_HEADERS
                    })
                caller = redirected
            if cross_origin:
                headers = {k: v for k, v in headers.items() if k.lower() in _REDIRECT_HEADERS}
                for key in ('auth', 'cookies', 'hooks', 'cert'):
                    kwargs.pop(key, None)
                # A module-level call must also suppress automatic netrc credentials.
                kwargs['auth'] = _NoRedirectAuth()
            if response.status_code not in (307, 308):
                if method != 'HEAD' and (response.status_code in (302, 303) or
                                         response.status_code == 301 and method == 'POST'):
                    method = 'GET'
                for key in ('data', 'json', 'files'):
                    kwargs.pop(key, None)
                body_headers = {'content-type', 'content-length', 'transfer-encoding'}
                headers = {k: v for k, v in headers.items() if k.lower() not in body_headers}
                if isinstance(caller, requests.Session):
                    for key in list(caller.headers):
                        if key.lower() in body_headers:
                            del caller.headers[key]
                positions = []
            else:
                _rewind_body(positions)
            kwargs['headers'] = headers
            current = target
        finally:
            # Release redirect responses, including rejected destinations.
            if hasattr(response, 'close'):
                response.close()

    raise requests.TooManyRedirects(
        f'Exceeded {max_redirects} redirects'
    )


class _NoRedirectAuth(requests.auth.AuthBase):
    def __call__(self, request):
        return request


def safe_get(url: str, *, validator: Validator, **kwargs) -> requests.Response:
    """``safe_request('GET', …)``."""
    return safe_request('GET', url, validator=validator, **kwargs)
