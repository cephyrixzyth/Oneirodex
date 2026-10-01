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

import pytest
import requests

from oneirodex.utils import security
from oneirodex.utils.http_safe import (
    BlockedOutboundUrl,
    safe_get,
    safe_request,
)
from oneirodex.utils.security import (
    is_blocked_outbound_host,
    is_cloud_metadata_host,
    validate_connector_http_url,
    validate_user_outbound_http_url,
)


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
