"""Phase 2 of the security/legal playbook — the two SSRF bypasses (S2).

Before this, ``validate_user_outbound_http_url`` promised "never LAN even if the
homelab flag is on" and could be walked past two ways: a hostname that *resolves*
to a private address was never resolved, and a redirect to anywhere at all was
followed without a second look.

``safe_request`` now also dials the address that passed that check, so a DNS
rebind between the check and the socket cannot steer the connection onto
loopback or link-local. Homelab ``ALLOW_PRIVATE_LAN_URLS`` must still reach
RFC1918 connectors — that case is pinned below.

See docs/strategy/security-legal-playbook.md (S2).
"""

from __future__ import annotations

import ipaddress
import io
import socketserver
import threading
from types import SimpleNamespace

import pytest
import requests
from requests.utils import select_proxy

from oneirodex.utils import security
from oneirodex.utils.http_safe import (
    BlockedOutboundUrl,
    ResponseTooLarge,
    read_response_limited,
    safe_get,
    safe_request,
)
from oneirodex.utils.security import (
    _embedded_ipv4,
    _is_blocked_ip,
    is_blocked_outbound_host,
    is_cloud_metadata_host,
    validate_connector_http_url,
    validate_user_outbound_http_url,
)


class _ChunkedResponse:
    def __init__(self, chunks, headers=None):
        self.chunks = chunks
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


def test_read_response_limited_caps_streamed_decoded_body_and_closes():
    response = _ChunkedResponse([b'abcd', b'efgh'])
    with pytest.raises(ResponseTooLarge):
        read_response_limited(response, 6)
    assert response.closed is True


def test_read_response_limited_accepts_exact_limit_and_rejects_declared_length():
    response = _ChunkedResponse([b'ab', b'cd'])
    assert read_response_limited(response, 4) == b'abcd'
    oversized = _ChunkedResponse([b''], headers={'Content-Length': '5'})
    with pytest.raises(ResponseTooLarge):
        read_response_limited(oversized, 4)


PUBLIC = '93.184.216.34'


@pytest.fixture(autouse=True)
def no_real_dns(monkeypatch):
    """Every name resolves to one public address, so nothing here touches the network.

    ``safe_request`` refuses a name that does not resolve (the pin cannot dial
    it), so the redirect tests need a resolvable default. Tests about
    resolution itself override this with ``resolves``.
    """
    monkeypatch.setattr(security, '_resolve_host', lambda host: [ipaddress.ip_address(PUBLIC)])


@pytest.fixture
def resolves(monkeypatch):
    """Pin DNS so these tests never depend on the network."""

    def _install(mapping: dict[str, list[str]]):
        def fake(host):
            return [ipaddress.ip_address(a) for a in mapping.get(host, [])]

        monkeypatch.setattr(security, '_resolve_host', fake)

    return _install


# --- bypass 1: the host check was DNS-blind --------------------------------

def test_hostname_resolving_to_loopback_is_blocked(resolves):
    resolves({'sneaky.example': ['127.0.0.1']})
    assert is_blocked_outbound_host('sneaky.example') is True


def test_hostname_resolving_to_rfc1918_is_blocked(resolves):
    resolves({'nas.example': ['192.168.1.10']})
    ok, _ = validate_user_outbound_http_url('http://nas.example/x')
    assert ok is False


def test_hostname_resolving_to_metadata_is_blocked(resolves):
    resolves({'harmless.example': ['169.254.169.254']})
    ok, _ = validate_user_outbound_http_url('http://harmless.example/latest/meta-data/')
    assert ok is False


def test_public_hostname_still_allowed(resolves):
    resolves({'api.example.com': ['93.184.216.34']})
    ok, cleaned = validate_user_outbound_http_url('https://api.example.com/v1')
    assert ok is True
    assert cleaned == 'https://api.example.com/v1'


def test_unresolvable_host_is_not_blocked(resolves):
    """The fetch cannot connect either; failing closed would reject good saves."""
    resolves({})
    assert is_blocked_outbound_host('does-not-resolve.invalid') is False


def test_resolve_can_be_switched_off(resolves):
    resolves({'sneaky.example': ['127.0.0.1']})
    assert is_blocked_outbound_host('sneaky.example', resolve=False) is False


# --- literal forms ipaddress rejects ---------------------------------------

@pytest.mark.parametrize('host', [
    '2130706433',      # decimal 127.0.0.1
    '0x7f.0.0.1',      # hex-dotted
    '127.1',           # short form
    '::ffff:127.0.0.1',  # IPv4-mapped IPv6
])
def test_alternate_loopback_literals_are_blocked(host):
    assert is_blocked_outbound_host(host) is True


def test_plain_loopback_and_localhost_still_blocked():
    assert is_blocked_outbound_host('127.0.0.1') is True
    assert is_blocked_outbound_host('localhost') is True
    assert is_blocked_outbound_host('box.local') is True


# --- the homelab carve-out must survive ------------------------------------

def test_lan_connector_still_allowed_when_flag_on(monkeypatch):
    """ALLOW_PRIVATE_LAN_URLS is why Unraid installs work. Do not regress it."""
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    ok, cleaned = validate_connector_http_url('http://192.168.1.50:9696')
    assert ok is True
    assert cleaned == 'http://192.168.1.50:9696'


def test_metadata_still_blocked_when_lan_flag_on(monkeypatch):
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    ok, _ = validate_connector_http_url('http://169.254.169.254/latest/')
    assert ok is False


def test_metadata_by_name_blocked_when_lan_flag_on(monkeypatch, resolves):
    """The carve-out used to inspect only the literal string."""
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    resolves({'looks-fine.example': ['169.254.169.254']})
    ok, _ = validate_connector_http_url('http://looks-fine.example/')
    assert ok is False


def test_cloud_metadata_host_names(resolves):
    resolves({})
    assert is_cloud_metadata_host('metadata.google.internal') is True
    assert is_cloud_metadata_host('169.254.169.254') is True
    assert is_cloud_metadata_host('example.com') is False


# --- bypass 2: redirects were followed unchecked ---------------------------

class _FakeResponse:
    def __init__(self, status_code=200, location=None):
        self.status_code = status_code
        self.headers = {'Location': location} if location else {}

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308) and 'Location' in self.headers


class _FakeSession:
    """Records every URL actually requested, and replays a scripted chain."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []
        self.last_kwargs = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        self.last_kwargs = kwargs
        return self._script.pop(0) if self._script else _FakeResponse()


def _allow_all(url):
    return True, url


def test_redirect_hops_are_revalidated(resolves):
    """A validated host answering 302 -> private used to be followed."""
    resolves({'good.example': ['93.184.216.34']})
    session = _FakeSession([_FakeResponse(302, 'http://169.254.169.254/latest/')])

    with pytest.raises(BlockedOutboundUrl):
        safe_get(
            'https://good.example/art.png',
            validator=validate_user_outbound_http_url,
            session=session,
        )

    # Dialed the checked address, not the name — and not the private hop.
    assert session.calls == [('GET', 'https://93.184.216.34/art.png')]
    assert session.last_kwargs['headers']['Host'] == 'good.example'


def test_allowed_redirect_is_followed(resolves):
    resolves({
        'good.example': ['93.184.216.34'],
        'cdn.example': ['93.184.216.35'],
    })
    session = _FakeSession([
        _FakeResponse(302, 'https://cdn.example/real.png'),
        _FakeResponse(200),
    ])

    resp = safe_get(
        'https://good.example/art.png',
        validator=validate_user_outbound_http_url,
        session=session,
    )
    assert resp.status_code == 200
    assert session.calls == [
        ('GET', 'https://93.184.216.34/art.png'),
        ('GET', 'https://93.184.216.35/real.png'),
    ]
    assert session.last_kwargs['headers']['Host'] == 'cdn.example'


def test_relative_redirect_resolves_against_current_hop():
    session = _FakeSession([_FakeResponse(302, '/moved.png'), _FakeResponse(200)])
    safe_get('https://good.example/a/art.png', validator=_allow_all, session=session)
    # Resolved against the hostname URL, then pinned: the name stays on Host.
    assert session.calls[-1] == ('GET', f'https://{PUBLIC}/moved.png')
    assert session.last_kwargs['headers']['Host'] == 'good.example'


def test_redirect_chain_is_bounded():
    session = _FakeSession([_FakeResponse(302, f'https://h{i}.example/') for i in range(12)])
    with pytest.raises(requests.TooManyRedirects):
        safe_get('https://start.example/', validator=_allow_all, session=session)


def test_initial_url_is_validated_before_any_request():
    session = _FakeSession([])
    with pytest.raises(BlockedOutboundUrl):
        safe_get(
            'http://127.0.0.1/admin',
            validator=validate_user_outbound_http_url,
            session=session,
        )
    assert session.calls == []


def test_post_body_is_not_replayed_on_a_303():
    session = _FakeSession([_FakeResponse(303, 'https://good.example/done'), _FakeResponse(200)])
    safe_request(
        'POST',
        'https://good.example/submit',
        validator=_allow_all,
        session=session,
        json={'secret': 'value'},
    )
    assert session.calls[-1][0] == 'GET'
    assert 'json' not in session.last_kwargs


def test_allow_redirects_cannot_be_forced_on():
    session = _FakeSession([_FakeResponse(200)])
    safe_get(
        'https://good.example/',
        validator=_allow_all,
        session=session,
        allow_redirects=True,
    )
    assert session.last_kwargs['allow_redirects'] is False


def test_connection_uses_the_address_that_was_checked(resolves, monkeypatch):
    """A rebind after the check must not change where we dial."""
    addrs = {'good.example': ['93.184.216.34']}

    def fake(host):
        return [ipaddress.ip_address(a) for a in addrs.get(host, [])]

    monkeypatch.setattr(security, '_resolve_host', fake)
    session = _FakeSession([_FakeResponse(200)])
    safe_get(
        'https://good.example/art.png',
        validator=validate_user_outbound_http_url,
        session=session,
    )
    addrs['good.example'] = ['127.0.0.1']
    assert session.calls == [('GET', 'https://93.184.216.34/art.png')]
    assert session.last_kwargs['headers']['Host'] == 'good.example'


def test_rebind_to_loopback_during_pin_is_blocked(resolves, monkeypatch):
    """If DNS has already flipped by the time we pick an address, fail closed."""
    addrs = {'good.example': ['93.184.216.34']}
    calls = {'n': 0}

    def fake(host):
        calls['n'] += 1
        # Validator resolves once; pin resolves again.
        if calls['n'] > 1:
            return [ipaddress.ip_address('127.0.0.1')]
        return [ipaddress.ip_address(a) for a in addrs.get(host, [])]

    monkeypatch.setattr(security, '_resolve_host', fake)
    session = _FakeSession([_FakeResponse(200)])
    with pytest.raises(BlockedOutboundUrl):
        safe_get(
            'https://good.example/art.png',
            validator=validate_user_outbound_http_url,
            session=session,
        )
    assert session.calls == []


def test_lan_connector_pin_keeps_rfc1918(monkeypatch, resolves):
    """Homelab connectors must still reach the NAS after the pin."""
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    resolves({'nas.home': ['192.168.1.50']})
    session = _FakeSession([_FakeResponse(200)])
    safe_get(
        'http://nas.home:9696/api',
        validator=validate_connector_http_url,
        session=session,
    )
    assert session.calls == [('GET', 'http://192.168.1.50:9696/api')]
    assert session.last_kwargs['headers']['Host'] == 'nas.home:9696'


def test_provider_cover_fetch_rejects_loopback():
    """Artwork providers used raw requests.get — same SSRF hole download_image closed."""
    from oneirodex.utils.providers.base import fetch_outbound_image

    with pytest.raises(ValueError, match='Blocked'):
        fetch_outbound_image('http://127.0.0.1/cover.jpg', timeout=1)


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
@pytest.mark.parametrize('method', ['POST', 'PUT', 'HEAD'])
def test_redirect_method_and_body_matrix(status, method):
    session = _FakeSession([_FakeResponse(status, '/done'), _FakeResponse()])
    safe_request(method, 'https://good.example/start', validator=_allow_all,
                 session=session, json={'payload': 1},
                 headers={'Content-Type': 'application/json', 'Content-Length': '12'})
    expected = 'GET' if method != 'HEAD' and (status in (302, 303) or status == 301 and method == 'POST') else method
    assert session.calls[-1][0] == expected
    assert ('json' in session.last_kwargs) == (status in (307, 308))
    assert ('Content-Type' in session.last_kwargs['headers']) == (status in (307, 308))


@pytest.mark.parametrize('target', ['https://foreign.example/done', 'http://good.example/done',
                                  'https://good.example:444/done'])
def test_real_session_redirect_credentials_do_not_cross_origin(monkeypatch, target, resolves):
    resolves({'good.example': ['93.184.216.34'], 'foreign.example': ['93.184.216.34']})
    calls = []
    def send(adapter, request, **kwargs):
        calls.append(request)
        response = requests.Response()
        response.status_code = 302 if len(calls) < 3 else 200
        response.headers['Location'] = target if len(calls) == 1 else 'https://good.example/return'
        response.request = request
        response.url = request.url
        response._content = b''
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    monkeypatch.setattr(requests.sessions, 'get_netrc_auth', lambda url: ('netrc', 'netrc-secret'))
    session = requests.Session()
    session.auth = ('session', 'session-secret')
    session.headers.update({'apikey': 'header-secret', 'Cookie': 'cookie-secret'})
    session.params = {'api_key': 'query-secret'}
    session.cookies.set('session', 'jar-secret')
    safe_get('https://good.example/start', validator=_allow_all, session=session,
             headers={'X-Api-Key': 'explicit-secret'}, cookies={'extra': 'extra-secret'},
             params={'key': 'explicit-query-secret'})
    assert 'Authorization' in calls[0].headers
    for request in calls[1:]:
        assert 'secret' not in str(dict(request.headers)) + request.url
        assert request.headers['Host'] == 'good.example' if request is calls[-1] else True
    assert session.auth == ('session', 'session-secret')
    assert session.headers['apikey'] == 'header-secret'
    assert session.params == {'api_key': 'query-secret'}
    assert session.cookies.get('session') == 'jar-secret'


def test_same_origin_keeps_credentials_and_stream_position():
    stream = io.BytesIO(b'prefix-payload')
    stream.seek(7)
    class Reader(_FakeSession):
        def request(self, method, url, **kwargs):
            assert kwargs['data'].read() == b'payload'
            return super().request(method, url, **kwargs)
    session = Reader([_FakeResponse(307, '/done'), _FakeResponse()])
    safe_request('POST', 'https://good.example/start', validator=_allow_all, session=session,
                 data=stream, headers={'Authorization': 'secret'}, auth=('user', 'pass'))
    assert session.last_kwargs['headers']['Authorization'] == 'secret'
    assert session.last_kwargs['auth'] == ('user', 'pass')


def test_unrewindable_body_fails_instead_of_sending_empty_body():
    session = _FakeSession([_FakeResponse(308, '/done')])
    with pytest.raises(requests.exceptions.UnrewindableBodyError):
        safe_request('POST', 'https://good.example/start', validator=_allow_all,
                     session=session, data=iter([b'payload']))
    assert len(session.calls) == 1


def test_redirect_cannot_supply_url_credentials():
    session = _FakeSession([_FakeResponse(302, 'https://user:secret@other.example/')])
    with pytest.raises(BlockedOutboundUrl, match='credentials'):
        safe_get('https://good.example/', validator=_allow_all, session=session)
    assert len(session.calls) == 1


@pytest.mark.parametrize('status', [307, 308])
@pytest.mark.parametrize('body', [{'data': {'secret': 'device-secret'}},
                                 {'json': {'source_token': 'refresh-secret'}}])
def test_credential_bodies_cannot_cross_origin(monkeypatch, status, body):
    calls = []
    def send(adapter, request, **kwargs):
        calls.append(request)
        response = requests.Response()
        response.status_code = status
        response.headers['Location'] = 'https://other.example/token'
        response.request = request
        response.url = request.url
        response._content = b''
        return response
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    with pytest.raises(BlockedOutboundUrl, match='body replay'):
        safe_request('POST', 'https://provider.example/token', validator=_allow_all, **body)
    assert len(calls) == 1


def test_multipart_file_rewound_on_same_origin_redirect():
    stream = io.BytesIO(b'payload')
    class Reader(_FakeSession):
        def request(self, method, url, **kwargs):
            assert kwargs['files']['upload'][1].read() == b'payload'
            return super().request(method, url, **kwargs)
    session = Reader([_FakeResponse(308, '/done'), _FakeResponse()])
    safe_request('POST', 'https://good.example/start', validator=_allow_all, session=session,
                 files={'upload': ('file.bin', stream)})


# --- connector URLs that embed credentials (user:pw@host) ---------------------

def test_userinfo_connector_follows_a_relative_redirect(resolves):
    """``/x`` -> ``/x/`` on a basic-auth proxy used to fail with 'Redirect credentials are not allowed'."""
    resolves({'proxy.lan': ['93.184.216.34']})
    session = _FakeSession([_FakeResponse(301, '/x/'), _FakeResponse(200)])
    resp = safe_get('http://user:pw@proxy.lan:8080/x', validator=_allow_all, session=session)
    assert resp.status_code == 200
    assert session.calls == [
        ('GET', 'http://user:pw@93.184.216.34:8080/x'),
        ('GET', 'http://user:pw@93.184.216.34:8080/x/'),
    ]
    assert session.last_kwargs['headers']['Host'] == 'proxy.lan:8080'


def test_userinfo_is_carried_to_an_absolute_same_origin_redirect(resolves):
    """An absolute Location has no userinfo; the next hop must still authenticate."""
    resolves({'proxy.lan': ['93.184.216.34']})
    session = _FakeSession([_FakeResponse(301, 'http://proxy.lan:8080/x/'), _FakeResponse(200)])
    safe_get('http://user:pw@proxy.lan:8080/x', validator=_allow_all, session=session)
    assert session.calls[-1] == ('GET', 'http://user:pw@93.184.216.34:8080/x/')


def test_userinfo_is_never_sent_to_another_origin(resolves):
    resolves({'proxy.lan': ['93.184.216.34'], 'elsewhere.lan': ['93.184.216.35']})
    session = _FakeSession([_FakeResponse(302, 'http://elsewhere.lan:8080/'), _FakeResponse(200)])
    safe_get('http://user:pw@proxy.lan:8080/x', validator=_allow_all, session=session)
    assert session.calls[-1] == ('GET', 'http://93.184.216.35:8080/')
    assert '@' not in session.calls[-1][1]


@pytest.mark.parametrize('location', [
    'http://other:pw2@proxy.lan:8080/x',            # same origin, different credentials
    'http://user:pw@elsewhere.lan:8080/',           # another origin, even the very same credentials
    'https://evil:evil@elsewhere.lan/',
])
def test_a_redirect_still_cannot_introduce_or_move_url_credentials(resolves, location):
    resolves({'proxy.lan': ['93.184.216.34'], 'elsewhere.lan': ['93.184.216.35']})
    session = _FakeSession([_FakeResponse(302, location)])
    with pytest.raises(BlockedOutboundUrl, match='credentials'):
        safe_get('http://user:pw@proxy.lan:8080/x', validator=_allow_all, session=session)
    assert len(session.calls) == 1


# --- http -> https upgrade of the same host keeps its credentials -------------

@pytest.mark.parametrize('old, new, keeps', [
    ('http://h.example/a', 'https://h.example/a', True),
    ('http://h.example:80/a', 'https://h.example:443/a', True),
    ('http://H.Example/a', 'https://h.example/b', True),
    ('https://h.example/a', 'https://h.example/b', True),
    ('http://h.example:8080/a', 'https://h.example/a', False),      # not the default port
    ('http://h.example/a', 'https://h.example:8443/a', False),
    ('https://h.example/a', 'http://h.example/a', False),           # downgrade
    ('http://h.example/a', 'https://other.example/a', False),       # another host
    ('http://h.example/a', 'http://h.example:81/a', False),
])
def test_origin_rule_matches_requests_for_the_default_port_upgrade(old, new, keeps):
    from oneirodex.utils.http_safe import _keeps_credentials

    assert _keeps_credentials(old, new) is keeps


def test_http_to_https_upgrade_keeps_the_api_key_header(resolves):
    """Prowlarr behind Caddy: ``http://prowlarr.lan`` answers 308 to its TLS listener."""
    resolves({'prowlarr.lan': ['93.184.216.34']})
    session = _FakeSession([_FakeResponse(308, 'https://prowlarr.lan/api/v1/search'), _FakeResponse(200)])
    safe_get('http://prowlarr.lan/api/v1/search', validator=_allow_all, session=session,
             headers={'X-Api-Key': 'prowlarr-key'})
    assert session.calls[-1] == ('GET', f'https://{PUBLIC}/api/v1/search')
    assert session.last_kwargs['headers']['X-Api-Key'] == 'prowlarr-key'
    assert session.last_kwargs['headers']['Host'] == 'prowlarr.lan'


def test_http_to_https_upgrade_may_replay_a_body(resolves):
    """The same host on the TLS port is not 'another origin' for a 307/308 body replay."""
    resolves({'qbit.lan': ['93.184.216.34']})
    session = _FakeSession([_FakeResponse(308, 'https://qbit.lan/api/v2/auth/login'), _FakeResponse(200)])
    safe_request('POST', 'http://qbit.lan/api/v2/auth/login', validator=_allow_all, session=session,
                 data={'username': 'admin', 'password': 'pw'})
    assert session.last_kwargs['data'] == {'username': 'admin', 'password': 'pw'}


def test_real_session_http_to_https_upgrade_keeps_auth_and_headers(monkeypatch):
    calls = []

    def send(adapter, request, **kwargs):
        calls.append(request)
        response = requests.Response()
        response.status_code = 308 if len(calls) == 1 else 200
        response.headers['Location'] = 'https://good.example/start'
        response.request = request
        response.url = request.url
        response._content = b''
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', send)
    session = requests.Session()
    session.auth = ('session', 'session-secret')
    safe_get('http://good.example/start', validator=_allow_all, session=session,
             headers={'X-Api-Key': 'explicit-secret'})
    assert len(calls) == 2
    assert calls[1].url.startswith(f'https://{PUBLIC}/')
    assert calls[1].headers['X-Api-Key'] == 'explicit-secret'
    assert calls[1].headers['Authorization'] == calls[0].headers['Authorization']


def test_a_cross_origin_hop_logs_what_it_dropped_without_values(resolves, caplog):
    resolves({'good.example': ['93.184.216.34'], 'cdn.example': ['93.184.216.35']})
    session = _FakeSession([_FakeResponse(302, 'https://cdn.example/x'), _FakeResponse(200)])
    with caplog.at_level('WARNING', logger='oneirodex.utils.http_safe'):
        safe_get('https://good.example/start', validator=_allow_all, session=session,
                 headers={'X-Api-Key': 'never-in-logs', 'Accept': 'text/html'})
    assert 'X-Api-Key' in caplog.text and 'cdn.example' in caplog.text
    assert 'never-in-logs' not in caplog.text
    assert 'Accept' not in caplog.text, 'allow-listed headers are not reported as dropped'
    assert 'X-Api-Key' not in session.last_kwargs['headers']


# --- the pin fails closed -----------------------------------------------------

def test_a_name_that_does_not_resolve_is_not_dialed(resolves):
    """NODATA/SERVFAIL for the validator and the pin, then 169.254.169.254 at connect time."""
    resolves({})
    session = _FakeSession([_FakeResponse(200)])
    with pytest.raises(BlockedOutboundUrl, match='could not be resolved'):
        safe_get('https://rebind.example/latest/meta-data/', validator=validate_user_outbound_http_url,
                 session=session)
    assert session.calls == [], 'requests must never be left to resolve the hostname itself'


def test_a_redirect_to_a_name_that_does_not_resolve_is_not_followed(resolves):
    resolves({'good.example': ['93.184.216.34']})
    session = _FakeSession([_FakeResponse(302, 'https://ghost.example/x')])
    with pytest.raises(BlockedOutboundUrl, match='could not be resolved'):
        safe_get('https://good.example/start', validator=validate_user_outbound_http_url, session=session)
    assert session.calls == [('GET', 'https://93.184.216.34/start')]


def test_an_unresolvable_name_is_still_accepted_when_saving_but_not_when_used(resolves):
    """Validators stay lenient (DNS can be down when a connector is saved); the dial does not."""
    resolves({})
    assert validate_connector_http_url('http://nas.example:9696')[0] is True
    with pytest.raises(BlockedOutboundUrl):
        safe_get('http://nas.example:9696/api', validator=validate_connector_http_url, session=_FakeSession([]))


def test_ip_literals_are_unaffected_by_the_resolution_rule(resolves):
    resolves({})
    session = _FakeSession([_FakeResponse(200)])
    safe_get('https://93.184.216.34/x', validator=validate_user_outbound_http_url, session=session)
    assert session.calls == [('GET', 'https://93.184.216.34/x')]


# --- cloud metadata endpoints that look like ordinary addresses ----------------

METADATA_ENDPOINTS = [
    '169.254.169.254',   # AWS / GCP / Azure IMDS
    '100.100.100.200',   # Alibaba
    '168.63.129.16',     # Azure wire server: a global address, so only the list catches it
    '192.0.0.192',       # Oracle: "not global", but the LAN flag reopens that
    'fd00:ec2::254',     # AWS IPv6 IMDS
    'fd00:ec2::23',      # AWS IPv6 resolver
]


def _url_for(host):
    return f'http://[{host}]/latest/' if ':' in host else f'http://{host}/latest/'


@pytest.mark.parametrize('host', METADATA_ENDPOINTS)
@pytest.mark.parametrize('lan_flag', [True, False])
def test_metadata_endpoints_never_validate_whatever_the_lan_flag(monkeypatch, host, lan_flag):
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: lan_flag)
    assert is_cloud_metadata_host(host) is True
    assert is_blocked_outbound_host(host) is True
    assert validate_connector_http_url(_url_for(host))[0] is False
    assert validate_user_outbound_http_url(_url_for(host))[0] is False
    assert security.validate_community_chat_url(_url_for(host))[0] is False


@pytest.mark.parametrize('host', ['168.63.129.16', '192.0.0.192', 'fd00:ec2::23'])
def test_a_name_resolving_to_a_metadata_endpoint_is_blocked_even_with_the_lan_flag(monkeypatch, resolves, host):
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    resolves({'innocent.example': [host]})
    assert is_cloud_metadata_host('innocent.example') is True
    assert validate_connector_http_url('http://innocent.example/machine?comp=goalstate')[0] is False


def test_ipv4_mapped_and_alternate_forms_of_the_azure_endpoint_are_blocked():
    assert is_blocked_outbound_host('::ffff:168.63.129.16') is True
    assert is_blocked_outbound_host('2822734096') is True     # decimal 168.63.129.16
    assert is_cloud_metadata_host('0xa8.0x3f.0x81.0x10') is True


def test_neighbouring_public_addresses_are_not_collateral_damage(resolves):
    resolves({})
    assert validate_user_outbound_http_url('https://168.63.129.17/')[0] is True
    assert validate_user_outbound_http_url('https://168.63.129.15/')[0] is True


# --- one URL, one host: urlparse and urllib3 must agree -----------------------
#
# ``urlparse`` ends the authority at / ? # and urllib3 (so ``requests``) also at a
# backslash. In ``http://127.0.0.1\@example.com/`` the validators and the pin saw
# ``example.com`` while ``requests`` dialed 127.0.0.1.

AMBIGUOUS_URLS = [
    'http://127.0.0.1\\@example.com/x',
    'http://169.254.169.254\\@example.com/latest/meta-data/',
    'https://127.0.0.1:8443\\@example.com/',
    'http://localhost\\.example.com/',
    'http://user:pa\\ss@example.com/',
    'http://exa mple.com/',
    'http://example.com:99999/',
    'http://example.com:port/',
    # ``requests`` decodes escaped unreserved characters in the host, so these dial
    # 127.0.0.1 and localhost while ``urlparse`` sees an unresolvable name.
    'http://127.0.0.%31/',
    'http://%31%32%37.0.0.1/',
    'http://localhost%2e/',
]


class _Recorder:
    """A loopback HTTP server that records every request head; 200 for a request, 502 for CONNECT.

    Doubles as an origin server and as a forward proxy: a proxy is sent the
    absolute URL (``GET http://host/x``) or ``CONNECT host:port``.
    """

    def __init__(self):
        recorder = self
        self.seen: list[tuple[str, str, dict]] = []

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                line = self.rfile.readline().decode('latin-1').strip()
                headers = {}
                while True:
                    raw = self.rfile.readline().decode('latin-1')
                    if raw in ('', '\r\n', '\n'):
                        break
                    name, _, value = raw.partition(':')
                    headers[name.strip().lower()] = value.strip()
                method, target, _ = line.split(' ', 2)
                recorder.seen.append((method, target, headers))
                if method == 'CONNECT':
                    self.wfile.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                else:
                    self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok')

        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f'http://127.0.0.1:{self.port}'

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


@pytest.mark.parametrize('url', AMBIGUOUS_URLS)
@pytest.mark.parametrize('validator', [validate_connector_http_url, validate_user_outbound_http_url])
def test_a_url_the_parsers_disagree_about_is_not_valid(monkeypatch, url, validator):
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    assert validator(url) == (False, 'Invalid URL')


@pytest.mark.parametrize('url', [
    'http://user:pa^ss@example.com/',
    'http://user:p|w@example.com/',
    'http://user:p{w}@example.com/',
    'http://us er@example.com/',
    'http://exa<mple.com/',
])
def test_characters_rfc_3986_keeps_out_of_an_authority_are_refused(url):
    """Both parsers agree on the host here; the URL is still not one we hand to a fetch."""
    assert validate_user_outbound_http_url(url) == (False, 'Invalid URL')


def test_a_community_link_with_a_split_authority_is_refused():
    assert security.validate_community_chat_url('http://127.0.0.1\\@example.com/')[0] is False


@pytest.mark.parametrize('url', [
    'https://example.com/a?b=c#d',
    'http://user:pw@example.com:8080/x',
    'http://us%40er:p%3Aw@example.com/',      # escaped userinfo is ordinary
    'http://a@b@example.com/',                 # both parsers split at the last @
    'https://[2001:4860:4860::8888]:8443/x',
    'https://EXAMPLE.com./',
    'https://bücher.example/x',                # internationalised host names keep working
    'http://example.com:/x',
])
def test_ordinary_urls_are_unambiguous(url):
    assert security.url_authority_is_unambiguous(url) is True


@pytest.mark.parametrize('url', AMBIGUOUS_URLS)
def test_safe_get_refuses_an_ambiguous_url_whatever_the_validator_says(url):
    session = _FakeSession([_FakeResponse(200)])
    with pytest.raises(BlockedOutboundUrl, match='Invalid URL'):
        safe_get(url, validator=_allow_all, session=session)
    assert session.calls == []


@pytest.mark.parametrize('validator', [validate_user_outbound_http_url, _allow_all])
@pytest.mark.parametrize('location', [
    'http://127.0.0.1\\@good.example/x',
    '//127.0.0.1\\@good.example/x',
    'http://good.example:notaport/x',     # was a bare ValueError out of the origin check
])
def test_a_redirect_location_the_parsers_disagree_about_is_not_followed(validator, location):
    session = _FakeSession([_FakeResponse(302, location), _FakeResponse(200)])
    with pytest.raises(BlockedOutboundUrl, match='Invalid URL'):
        safe_get('https://good.example/start', validator=validator, session=session)
    assert session.calls == [('GET', f'https://{PUBLIC}/start')]


@pytest.mark.parametrize('url', ['http://127.0.0.%31/x', 'http://localhost%2e/x', 'http://%31%32%37.0.0.1/x'])
def test_an_escaped_host_cannot_ride_a_proxy_to_loopback(monkeypatch, url):
    """With a proxy the name is sent as written; ``requests`` would first decode it to 127.0.0.1."""
    for name in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)
    with _Recorder() as proxy:
        monkeypatch.setenv('http_proxy', proxy.url)
        with pytest.raises(BlockedOutboundUrl):
            safe_get(url, validator=validate_user_outbound_http_url, timeout=5)
    assert proxy.seen == []


def test_a_backslash_cannot_aim_a_real_fetch_at_loopback():
    """The live repro: the validator saw example.com, urllib3 dialed this server and returned its body."""
    with _Recorder() as origin:
        with pytest.raises(BlockedOutboundUrl):
            safe_get(f'http://127.0.0.1:{origin.port}\\@example.com/secret',
                     validator=validate_user_outbound_http_url, timeout=5)
    assert origin.seen == []


def test_the_pinned_url_does_not_copy_raw_userinfo():
    from oneirodex.utils.http_safe import _replace_host_with_ip

    assert _replace_host_with_ip('http://us er:p w^@h.example:81/x?y=1', '10.0.0.1') == (
        'http://us%20er:p%20w%5E@10.0.0.1:81/x?y=1'
    )
    # What was already escaped stays as it was written.
    assert _replace_host_with_ip('http://us%40er:p%3Aw@h.example/', '10.0.0.1') == (
        'http://us%40er:p%3Aw@10.0.0.1/'
    )


# --- proxies: the name decides, the pin only applies when no proxy does --------

@pytest.fixture
def proxy_env(monkeypatch):
    """Clear every proxy variable, then let the test set the ones it wants."""
    for name in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)

    def apply(**values):
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    return apply


class _Wire:
    """What reaches the transport: request URL, Host header and the proxies the adapter was handed."""

    def __init__(self):
        self.sent: list[SimpleNamespace] = []
        self.script: list[tuple[str | None, int]] = []   # (Location, status), consumed in order

    def send(self, adapter, request, **kwargs):
        self.sent.append(SimpleNamespace(url=request.url, host=request.headers.get('Host'),
                                         proxies=kwargs.get('proxies') or {}))
        location, status = self.script.pop(0) if self.script else (None, 200)
        response = requests.Response()
        response.status_code = status
        if location:
            response.headers['Location'] = location
        response.request = request
        response.url = request.url
        response._content = b''
        return response


@pytest.fixture
def wire(monkeypatch):
    transport = _Wire()
    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send',
                        lambda adapter, request, **kwargs: transport.send(adapter, request, **kwargs))
    return transport


def test_a_proxied_http_fetch_sends_the_hostname_to_the_proxy(proxy_env):
    """It used to send ``GET http://<ip>/x``: a name-based virtual host behind the proxy broke."""
    with _Recorder() as proxy:
        proxy_env(http_proxy=proxy.url)
        response = safe_get('http://good.example/x?y=1', validator=validate_user_outbound_http_url, timeout=5)
    assert response.status_code == 200
    [(method, target, headers)] = proxy.seen
    assert (method, target) == ('GET', 'http://good.example/x?y=1')
    assert headers['host'] == 'good.example'


def test_a_proxied_https_fetch_tunnels_to_the_hostname(proxy_env):
    """It used to ``CONNECT <ip>:443`` with no SNI, so TLS through a proxy failed."""
    with _Recorder() as proxy:
        proxy_env(https_proxy=proxy.url)
        with pytest.raises(requests.exceptions.ProxyError):
            safe_get('https://good.example/x', validator=validate_user_outbound_http_url, timeout=5)
    assert [(method, target) for method, target, _ in proxy.seen] == [('CONNECT', 'good.example:443')]


def test_a_proxied_name_is_still_validated_first(proxy_env, resolves):
    resolves({'sneaky.example': ['127.0.0.1']})
    with _Recorder() as proxy:
        proxy_env(http_proxy=proxy.url)
        with pytest.raises(BlockedOutboundUrl):
            safe_get('http://sneaky.example/x', validator=validate_user_outbound_http_url, timeout=5)
    assert proxy.seen == []


@pytest.mark.parametrize('no_proxy', ['nas.lan', '.lan', '*'])
def test_no_proxy_is_decided_by_the_name_and_the_dial_stays_pinned(proxy_env, resolves, monkeypatch, no_proxy):
    """``NO_PROXY=nas.lan`` does not match the pinned 10.x address, so the call went to the proxy."""
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    resolves({'nas.lan': ['127.0.0.1']})
    with _Recorder() as proxy, _Recorder() as nas:
        proxy_env(http_proxy=proxy.url, no_proxy=no_proxy)
        response = safe_get(f'http://nas.lan:{nas.port}/api', validator=validate_connector_http_url,
                            headers={'X-Api-Key': 'key'}, timeout=5)
    assert response.status_code == 200
    assert proxy.seen == [], 'the API key must not travel through a proxy NO_PROXY excludes'
    [(method, target, headers)] = nas.seen
    assert (method, target) == ('GET', '/api')
    assert headers['host'] == f'nas.lan:{nas.port}'


def test_a_session_with_its_own_proxies_sends_the_hostname(wire):
    session = requests.Session()
    session.proxies = {'https': 'http://proxy.example:3128'}
    safe_get('https://good.example/x', validator=validate_user_outbound_http_url, session=session)
    [sent] = wire.sent
    assert sent.url == 'https://good.example/x'
    assert select_proxy(sent.url, sent.proxies) == 'http://proxy.example:3128'


def test_an_explicit_proxies_argument_is_honoured_by_name(wire):
    safe_get('http://good.example/x', validator=validate_user_outbound_http_url,
             proxies={'http': 'http://proxy.example:3128'})
    [sent] = wire.sent
    assert sent.url == 'http://good.example/x'
    assert select_proxy(sent.url, sent.proxies) == 'http://proxy.example:3128'


def test_a_session_that_ignores_the_environment_is_pinned_and_unproxied(wire, proxy_env):
    proxy_env(https_proxy='http://proxy.example:3128')
    session = requests.Session()
    session.trust_env = False
    safe_get('https://good.example/x', validator=validate_user_outbound_http_url, session=session)
    [sent] = wire.sent
    assert sent.url == f'https://{PUBLIC}/x'
    assert sent.host == 'good.example'
    assert select_proxy(sent.url, sent.proxies) is None


def test_each_redirect_hop_decides_its_own_proxy(wire, proxy_env):
    proxy_env(http_proxy='http://proxy.example:3128', no_proxy='cdn.example')
    wire.script.append(('http://cdn.example/y', 302))
    safe_get('http://good.example/x', validator=validate_user_outbound_http_url)
    first, second = wire.sent
    assert first.url == 'http://good.example/x'
    assert select_proxy(first.url, first.proxies) == 'http://proxy.example:3128'
    assert second.url == f'http://{PUBLIC}/y' and second.host == 'cdn.example'
    assert select_proxy(second.url, second.proxies) is None


def test_a_redirect_into_a_proxied_name_keeps_using_the_proxy_by_name(wire, proxy_env):
    """The session copy used for another origin ignores the environment, so the proxy is passed explicitly."""
    proxy_env(http_proxy='http://proxy.example:3128', no_proxy='good.example')
    wire.script.append(('http://cdn.example/y', 302))
    safe_get('http://good.example/x', validator=validate_user_outbound_http_url, session=requests.Session())
    first, second = wire.sent
    assert first.url == f'http://{PUBLIC}/x'
    assert select_proxy(first.url, first.proxies) is None
    assert second.url == 'http://cdn.example/y'
    assert select_proxy(second.url, second.proxies) == 'http://proxy.example:3128'


# --- cloud metadata wrapped in an IPv6 address --------------------------------
#
# 169.254.169.254 spelled as the IPv6 forms a translator or relay would carry.
# RFC 6052 section 2.2 spreads the IPv4 address around the reserved byte 8 for the
# shorter prefix lengths, so each /48-contained length gets its own spelling.

WRAPPED_METADATA = [
    '64:ff9b::a9fe:a9fe',                       # NAT64 well-known prefix (/96)
    '64:ff9b:1::a9fe:a9fe',                     # RFC 8215 local-use block, /96 form
    '64:ff9b:1:0:a9:fea9:fe00:0',               # ... /64 form
    '64:ff9b:1:a9:fe:a9fe::',                   # ... /56 form
    '64:ff9b:1:a9fe:a9:fe00::',                 # ... /48 form
    '2002:a9fe:a9fe::1',                        # 6to4
    '2001:0:4136:e378:8000:63bf:5601:5601',     # Teredo, wrapped address is the obfuscated client
    '2001:0:a9fe:a9fe:8000:63bf:3f57:fefd',     # Teredo, wrapped address is the server
    '::a9fe:a9fe',                              # IPv4-compatible
    '::ffff:0:a9fe:a9fe',                       # SIIT / IPv4-translated
    '::ffff:a9fe:a9fe',                         # IPv4-mapped
]


@pytest.mark.parametrize('lan_flag', [True, False])
@pytest.mark.parametrize('host', WRAPPED_METADATA)
def test_metadata_wrapped_in_ipv6_never_validates_whatever_the_lan_flag(monkeypatch, host, lan_flag):
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: lan_flag)
    assert is_cloud_metadata_host(host) is True
    assert validate_connector_http_url(_url_for(host))[0] is False
    assert validate_user_outbound_http_url(_url_for(host))[0] is False


@pytest.mark.parametrize('host', [
    '64:ff9b::6464:64c8', '2002:6464:64c8::1', '::6464:64c8',            # 100.100.100.200
    '64:ff9b::a83f:8110', '2002:a83f:8110::1', '::ffff:0:a83f:8110',     # 168.63.129.16
    '64:ff9b::c000:c0', '64:ff9b:1::c000:c0',                            # 192.0.0.192
])
def test_the_other_listed_endpoints_are_caught_inside_a_wrapper_too(monkeypatch, host):
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    assert is_cloud_metadata_host(host) is True
    assert validate_connector_http_url(_url_for(host))[0] is False


def test_a_name_that_resolves_to_a_wrapped_metadata_address_is_blocked_with_the_lan_flag(monkeypatch, resolves):
    """DNS64 answers with exactly these."""
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    resolves({'dns64.example': ['64:ff9b::a9fe:a9fe']})
    assert is_cloud_metadata_host('dns64.example') is True
    assert validate_connector_http_url('http://dns64.example/latest/')[0] is False


def test_a_wrapped_address_that_is_not_metadata_is_not_called_metadata(monkeypatch):
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    # 192.168.1.50 behind NAT64, 6to4 and IPv4-compatible: LAN, which the flag may reopen.
    for host in ('64:ff9b::c0a8:132', '2002:c0a8:132::1', '::c0a8:132'):
        assert is_cloud_metadata_host(host) is False
        assert validate_connector_http_url(_url_for(host))[0] is True, host


@pytest.mark.parametrize('address', [
    # RFC 6052 section 2.4 examples for 192.0.2.33, one per prefix length (48, 56, 64, 96);
    # the prefix itself is irrelevant to where the octets sit.
    '64:ff9b:1:c000:2:2100::',
    '64:ff9b:1:3c0:0:221::',
    '64:ff9b:1:344:c0:2:2100::',
    '64:ff9b:1::c000:221',
])
def test_local_use_nat64_addresses_are_unwrapped_at_each_rfc_6052_position(address):
    assert ipaddress.IPv4Address('192.0.2.33') in _embedded_ipv4(ipaddress.ip_address(address))


def test_embedded_ipv4_covers_each_wrapper_exactly():
    def wrapped(text):
        return {str(a) for a in _embedded_ipv4(ipaddress.ip_address(text))}

    assert wrapped('64:ff9b::a9fe:a9fe') == {'169.254.169.254'}
    assert wrapped('2002:a9fe:a9fe::1') == {'169.254.169.254'}
    assert wrapped('2001:0:4136:e378:8000:63bf:5601:5601') == {'65.54.227.120', '169.254.169.254'}
    assert wrapped('::a9fe:a9fe') == {'169.254.169.254'}
    assert wrapped('::ffff:0:a9fe:a9fe') == {'169.254.169.254'}
    assert wrapped('::ffff:a9fe:a9fe') == {'169.254.169.254'}
    assert wrapped('2606:4700:4700::1111') == set()       # an ordinary global address wraps nothing
    assert wrapped('8.8.8.8') == set()


@pytest.mark.parametrize('addr', ['64:ff9b:1::1', '64:ff9b:1:ffff:ffff:ffff:ffff:ffff', '64:ff9b:1:1234::5678'])
def test_the_local_use_nat64_block_is_always_blocked(addr):
    assert _is_blocked_ip(ipaddress.ip_address(addr)) is True


@pytest.mark.parametrize('addr', ['64:ff9b::a9fe:a9fe', '2002:a9fe:a9fe::1', '::a9fe:a9fe', '::ffff:0:7f00:1'])
def test_wrapped_blocked_addresses_stay_blocked(addr):
    assert _is_blocked_ip(ipaddress.ip_address(addr)) is True


def test_a_wrapper_the_ipaddress_tables_call_public_is_blocked_for_what_it_wraps(monkeypatch):
    """How ``ipaddress`` classifies these prefixes has changed between Python versions; the wrapped address decides."""
    monkeypatch.setattr(security, '_is_blocked_address', lambda ip: str(ip) in ('169.254.169.254', '10.0.0.1'))
    for addr in ('64:ff9b::a9fe:a9fe', '2002:a9fe:a9fe::1', '::a9fe:a9fe', '::ffff:0:a9fe:a9fe',
                 '2001:0:4136:e378:8000:63bf:5601:5601', '2001:0:a9fe:a9fe:8000:63bf:3f57:fefd',
                 '64:ff9b:1:a9fe:a9:fe00::', '64:ff9b:1:a9:fe:a9fe::', '64:ff9b:1:0:a9:fea9:fe00:0'):
        assert _is_blocked_ip(ipaddress.ip_address(addr)) is True, addr
    assert _is_blocked_ip(ipaddress.ip_address('64:ff9b::808:808')) is False      # NAT64 of 8.8.8.8, under that stub
    # The local-use block is somebody's translator whatever the tables say.
    assert _is_blocked_ip(ipaddress.ip_address('64:ff9b:1::808:808')) is True


# --- the dropped-credentials log ----------------------------------------------

def test_a_second_cross_origin_hop_does_not_report_the_auth_the_first_one_installed(resolves, caplog):
    resolves({name: ['93.184.216.34'] for name in ('good.example', 'cdn.example', 'edge.example')})
    session = _FakeSession([_FakeResponse(302, 'https://cdn.example/x'),
                            _FakeResponse(302, 'https://edge.example/y'),
                            _FakeResponse(200)])
    with caplog.at_level('WARNING', logger='oneirodex.utils.http_safe'):
        safe_get('https://good.example/start', validator=_allow_all, session=session,
                 headers={'X-Api-Key': 'never-in-logs'})
    lines = [record.getMessage() for record in caplog.records if 'dropped' in record.getMessage()]
    assert len(lines) == 1, lines
    assert 'X-Api-Key' in lines[0] and 'auth' not in lines[0]


def test_auth_the_caller_really_sent_is_still_reported(resolves, caplog):
    resolves({'good.example': ['93.184.216.34'], 'cdn.example': ['93.184.216.35']})
    session = _FakeSession([_FakeResponse(302, 'https://cdn.example/x'), _FakeResponse(200)])
    with caplog.at_level('WARNING', logger='oneirodex.utils.http_safe'):
        safe_get('https://good.example/start', validator=_allow_all, session=session, auth=('user', 'pw'))
    assert 'dropped: auth' in caplog.text
    assert 'pw' not in caplog.text
