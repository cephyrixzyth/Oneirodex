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

import logging
from copy import copy
from typing import Callable
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from requests.utils import select_proxy

from oneirodex.utils import security

logger = logging.getLogger(__name__)

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


def _keeps_credentials(old: str, new: str) -> bool:
    """True when a redirect from *old* to *new* may keep credentials, headers and body.

    Same origin, plus the one move ``requests`` itself allows across origins: an
    ``http`` to ``https`` upgrade of the same host on the default ports (a
    reverse proxy answering ``308`` to its TLS listener). A change of host,
    port, or an ``https`` to ``http`` downgrade is still another origin.
    """
    before, after = _origin(old), _origin(new)
    if before == after:
        return True
    return (
        before[0] == 'http' and after[0] == 'https'
        and before[1] == after[1]
        and before[2] == 80 and after[2] == 443
    )


def _userinfo(url: str):
    """``(username, password)`` embedded in *url*, or None when it has none."""
    parsed = urlparse(url)
    if parsed.username is None and parsed.password is None:
        return None
    return parsed.username, parsed.password


#: What may stay unescaped in URL userinfo (RFC 3986 sub-delims, ``:``, ``@``, and
#: the ``%`` of an escape that is already there).
_USERINFO_SAFE = "%!$&'()*+,;=:@"


def _userinfo_text(username, password) -> str:
    """``user[:password]`` ready to go in front of a host.

    ``urlparse`` hands userinfo back as written, and ``requests`` parses the URL
    again with different rules (it ends the authority at a backslash, which
    Python does not). Anything RFC 3986 keeps out of userinfo is therefore
    percent-encoded rather than copied, so what was a credential cannot turn
    into part of the host; existing ``%XX`` escapes are kept.
    """
    text = quote(username or '', safe=_USERINFO_SAFE)
    if password is not None:
        text += ':' + quote(password, safe=_USERINFO_SAFE)
    return text


def _with_userinfo(url: str, info) -> str:
    """*url* with the userinfo *info* put back in front of its host."""
    username, password = info
    parsed = urlparse(url)
    hostport = parsed.netloc.rpartition('@')[2]
    auth = _userinfo_text(username, password)
    return urlunparse((parsed.scheme, f'{auth}@{hostport}', parsed.path, parsed.params, parsed.query, parsed.fragment))


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


class ResponseTooLarge(requests.RequestException):
    """Raised when a streamed response exceeds its caller-supplied byte cap."""


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
    # Whatever the validator thought of the host, the URL that goes to
    # ``requests`` must name the same host to it as it does to ``urlparse`` (a
    # backslash in the userinfo or a ``%31`` in the host splits them). Applies to
    # every hop, including a redirect ``Location``, and to a validator that does
    # not check it itself.
    if not security.url_authority_is_unambiguous(result):
        raise BlockedOutboundUrl(url, 'Invalid URL')
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
        hostport = f'{_userinfo_text(parsed.username, parsed.password)}@{hostport}'
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
    when the URL already used a literal IP.

    A name that does not resolve is refused, not passed through: letting
    ``requests`` look it up again at connect time would be the unvalidated,
    unpinned dial this function exists to prevent (a resolver that answers the
    validator's lookups with NODATA and the connect-time lookup with
    169.254.169.254).
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return url, None
    if security._parse_ip_literal(host) is not None:
        return url, None

    addrs = security._resolve_host(host)
    if not addrs:
        raise BlockedOutboundUrl(url, 'URL host could not be resolved')

    last_reason = 'URL host is not allowed'
    for ip in addrs:
        candidate = _replace_host_with_ip(url, str(ip))
        ok, cleaned = validator(candidate)
        if ok:
            return cleaned, host
        last_reason = cleaned
    raise BlockedOutboundUrl(url, last_reason)


def _proxy_rules(caller):
    """The Session whose proxy rules *caller* sends with, or None for a stand-in that has none.

    ``requests.request`` builds a fresh Session for every call, so the module
    itself means a default one (environment trusted, no proxies of its own).
    """
    if isinstance(caller, requests.Session):
        return caller
    if caller is requests:
        return requests.Session()
    return None


def _proxies_for(rules, explicit: dict, url: str) -> dict:
    """The ``proxies`` mapping ``requests`` would settle on for *url*.

    Asks ``Session.merge_environment_settings``, the call ``Session.request``
    itself makes, so ``HTTP(S)_PROXY``, ``ALL_PROXY`` and ``NO_PROXY`` (host
    names, suffixes and CIDR ranges) behave exactly as they do for any other
    ``requests`` caller, honouring the session's ``trust_env`` and ``proxies``
    and an explicit ``proxies=`` argument.
    """
    proxies = dict(explicit)
    if rules is not None:
        return rules.merge_environment_settings(url, proxies, None, None, None)['proxies']
    return {key: value for key, value in proxies.items() if value is not None}


def _without_proxy(proxies: dict, url: str) -> dict:
    """*proxies* with every entry ``requests`` would match to *url* switched off."""
    parsed = urlparse(url)
    off = dict(proxies)
    for key in (f'{parsed.scheme}://{parsed.hostname}', parsed.scheme, f'all://{parsed.hostname}', 'all'):
        off[key] = None
    return off


def _plan_hop(url: str, validator: Validator, rules, explicit: dict) -> tuple[str, str | None, dict | None]:
    """How to send one hop: ``(connect_url, original_hostname, proxies)``.

    Whether a proxy applies is decided on the name the URL carries. Through a
    proxy the hostname is sent as it is: the proxy resolves and dials it, a TLS
    tunnel needs it for SNI, and the name is the only thing ``NO_PROXY`` can
    match. The name still passed the validator before this point, but pinning
    cannot protect a hop that the proxy, not this process, connects, so
    protection against DNS rebinding then rests with the proxy.

    Without a proxy the hop is pinned to the address the validator accepted. A
    proxy variable set for the environment would otherwise be applied to that
    address (``NO_PROXY=nas.lan`` does not match ``10.0.0.5``), so in that case
    ``proxies`` switches it off for the pinned URL. ``proxies`` is None when
    ``requests`` should be left to its own devices.
    """
    proxies = _proxies_for(rules, explicit, url)
    if select_proxy(url, proxies) is not None:
        return url, None, proxies
    connect_url, tls_name = _pin_checked_address(url, validator)
    if connect_url != url and select_proxy(connect_url, _proxies_for(rules, explicit, connect_url)) is not None:
        return connect_url, tls_name, _without_proxy(proxies, connect_url)
    return connect_url, tls_name, None


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
    # Proxy rules come from the caller as it was handed in: a cross-origin hop
    # below sends with a stripped copy, but still follows the same environment.
    proxy_rules = _proxy_rules(caller)
    explicit_proxies = dict(kwargs.get('proxies') or {})
    for _ in range(max_redirects + 1):
        connect_url, tls_name, hop_proxies = _plan_hop(current, validator, proxy_rules, explicit_proxies)
        req_kwargs = dict(kwargs)
        if hop_proxies is not None:
            req_kwargs['proxies'] = hop_proxies
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
            cross_origin = not _keeps_credentials(current, target)
            if cross_origin and response.status_code in (307, 308) and any(
                kwargs.get(key) is not None for key in ('data', 'json', 'files')
            ):
                # OAuth/device-auth bodies contain secrets too. Header stripping
                # cannot make their replay to a new origin safe.
                raise BlockedOutboundUrl(target, 'Cross-origin request body replay is not allowed')
            # A Location must not inject new URL credentials, even with a permissive
            # validator. Credentials the connector URL already carried
            # (``http://user:pw@proxy.lan``) are the exception, and only for a hop
            # that keeps them: ``urljoin`` copies them onto a relative Location, an
            # absolute Location drops them, and either way the next hop must send
            # what the first one did. Another origin never receives them.
            current_info, target_info = _userinfo(current), _userinfo(target)
            if cross_origin:
                if target_info is not None:
                    raise BlockedOutboundUrl(target, 'Redirect credentials are not allowed')
            elif target_info is None:
                if current_info is not None:
                    target = _with_userinfo(target, current_info)
            elif target_info != current_info:
                raise BlockedOutboundUrl(target, 'Redirect credentials are not allowed')
            kwargs.pop('params', None)
            headers = dict(kwargs.get('headers') or {})
            if isinstance(caller, requests.Session):
                # Detach request defaults, but keep caller-owned transport adapters open.
                redirected = copy(caller)
                redirected.params = {}
                redirected.headers = caller.headers.copy()
                if cross_origin:
                    # Proxies are not frozen here: every hop asks again, by the
                    # name it is going to (see _plan_hop).
                    settings = caller.merge_environment_settings(target, {}, kwargs.get('stream'),
                                                                 kwargs.get('verify'), None)
                    kwargs.setdefault('verify', settings['verify'])
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
                dropped = sorted(
                    {k for k in headers if k.lower() not in _REDIRECT_HEADERS}
                    # ``_NoRedirectAuth`` is what an earlier hop left behind, not
                    # something the caller sent.
                    | {k for k in ('auth', 'cookies', 'cert')
                       if kwargs.get(k) is not None and not isinstance(kwargs.get(k), _NoRedirectAuth)}
                    | ({'URL credentials'} if current_info is not None else set())
                )
                if dropped:
                    # Names only, never values or the URL: a connector that
                    # starts failing with 401 after its server began redirecting
                    # to another origin should say why.
                    logger.warning(
                        'Redirect from %s to %s is another origin; dropped: %s',
                        urlparse(current).hostname, urlparse(target).hostname, ', '.join(dropped),
                    )
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


def read_response_limited(response: requests.Response, max_bytes: int) -> bytes:
    """Read a streamed response while enforcing a cap on decoded body bytes.

    Callers that need this guarantee must request ``stream=True`` and pass a
    caller-owned ``requests.Session`` to :func:`safe_request`; the returned
    response can then be consumed before the session is closed. The fallback
    for lightweight response doubles keeps unit tests and adapters compatible.
    """
    if max_bytes <= 0:
        raise ValueError('max_bytes must be positive')
    length = getattr(response, 'headers', {}).get('Content-Length')
    try:
        if length is not None and int(length) > max_bytes:
            raise ResponseTooLarge(f'Response exceeds {max_bytes} bytes')
    except (TypeError, ValueError):
        pass

    iterator = getattr(response, 'iter_content', None)
    if not callable(iterator):
        body = response.content
        if len(body) > max_bytes:
            raise ResponseTooLarge(f'Response exceeds {max_bytes} bytes')
        return body

    body = bytearray()
    try:
        for chunk in iterator(chunk_size=min(64 * 1024, max_bytes + 1)):
            if not chunk:
                continue
            if len(body) + len(chunk) > max_bytes:
                raise ResponseTooLarge(f'Response exceeds {max_bytes} bytes')
            body.extend(chunk)
    except ResponseTooLarge:
        response.close()
        raise
    return bytes(body)
