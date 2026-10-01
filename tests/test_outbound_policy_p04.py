"""Outbound policy for admin-configured URLs, key-free logs, and the CGNAT gap.

* LOW: ``_is_blocked_ip`` let 100.64.0.0/10 (Tailscale, Alibaba metadata) through.
* LOW: *arr connector failures logged ``exc`` and a requests error carries
  ``?apikey=...``.
* LOW: game-server health, Ollama, *arr hubs, download clients and the ambient
  bridges were validated once at save time and then fetched with default
  redirects; errors went back to members as ``str(exc)``.
"""

from __future__ import annotations

import ipaddress
import logging
import socket

import pytest
import requests

from oneirodex.utils import ai_assist, ambient_lighting, arr_connectors
from oneirodex.utils.game_servers import probe_server_health
from oneirodex.utils.http_safe import BlockedOutboundUrl
from oneirodex.utils.security import (
    _is_blocked_ip,
    is_blocked_outbound_host,
    is_cloud_metadata_host,
    validate_outbound_http_url,
    validate_user_outbound_http_url,
)

METADATA = 'http://169.254.169.254/latest/meta-data/'


def _response(status: int, location: str | None = None, body: bytes = b'') -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp._content_consumed = True
    resp.encoding = 'utf-8'
    if location:
        resp.headers['Location'] = location
    return resp


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    @property
    def text(self) -> str:
        return '\n'.join(self.lines)


@pytest.fixture
def capture():
    """Collect a module logger's records directly (independent of propagation)."""
    handlers: list[tuple[logging.Logger, _Records]] = []

    def attach(name: str) -> _Records:
        logger = logging.getLogger(name)
        handler = _Records()
        logger.addHandler(handler)
        handlers.append((logger, handler))
        return handler

    yield attach
    for logger, handler in handlers:
        logger.removeHandler(handler)


# --------------------------------------------------------------------------
# CGNAT
# --------------------------------------------------------------------------

@pytest.mark.parametrize('addr', [
    '100.64.0.0', '100.64.0.1', '100.100.100.200', '100.127.255.255', '::ffff:100.64.0.1',
])
def test_shared_address_space_is_blocked(addr):
    assert _is_blocked_ip(ipaddress.ip_address(addr)) is True


@pytest.mark.parametrize('addr', [
    '100.63.255.255', '100.128.0.0', '8.8.8.8', '1.1.1.1', '2001:4860:4860::8888',
])
def test_neighbouring_public_space_is_not_blocked(addr):
    assert _is_blocked_ip(ipaddress.ip_address(addr)) is False


@pytest.mark.parametrize('addr', ['10.0.0.1', '127.0.0.1', '169.254.1.1', '0.0.0.0', '224.0.0.1', 'fd00::1', '::1'])
def test_existing_blocks_still_hold(addr):
    assert _is_blocked_ip(ipaddress.ip_address(addr)) is True


def test_user_and_indexer_fetches_never_reach_cgnat_even_with_the_lan_flag(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    with app.app_context():
        for url in ('http://100.64.3.4/x', 'http://100.100.100.200/latest/meta-data/'):
            ok, _ = validate_user_outbound_http_url(url)
            assert ok is False, url


def test_connector_urls_reach_a_tailscale_peer_only_with_the_lan_flag(app, monkeypatch):
    url = 'http://100.64.3.4:8080/'
    assert validate_outbound_http_url(url, allow_http=True, allow_private_lan=False)[0] is False
    assert validate_outbound_http_url(url, allow_http=True, allow_private_lan=True)[0] is True


@pytest.mark.parametrize('url', ['http://100.100.100.200/latest/meta-data/', 'http://[fd00:ec2::254]/latest/'])
def test_metadata_endpoints_stay_blocked_when_the_lan_flag_reopens_private_ranges(url):
    assert validate_outbound_http_url(url, allow_http=True, allow_private_lan=True)[0] is False


def test_metadata_host_helper_knows_the_non_link_local_endpoints():
    assert is_cloud_metadata_host('100.100.100.200') is True
    assert is_cloud_metadata_host('fd00:ec2::254') is True
    assert is_cloud_metadata_host('100.64.3.4') is False
    assert is_blocked_outbound_host('100.64.3.4', resolve=False) is True
    assert is_blocked_outbound_host('8.8.8.8', resolve=False) is False


def test_public_https_target_is_unaffected():
    assert validate_outbound_http_url('https://8.8.8.8/x', allow_http=False, allow_private_lan=False)[0] is True


# --------------------------------------------------------------------------
# key-free logs (*arr connectors)
# --------------------------------------------------------------------------

def test_url_for_log_drops_query_userinfo_and_fragment():
    assert arr_connectors._url_for_log('http://u:p@jackett:9117/api/v2.0/x?apikey=SECRET&q=1#frag') == (
        'http://jackett:9117/api/v2.0/x'
    )
    assert arr_connectors._url_for_log('not a url') == ''
    assert arr_connectors._url_for_log(None) == ''


def test_exc_for_log_never_carries_the_query_string():
    request = requests.Request(
        'GET', 'http://jackett:9117/api/v2.0/indexers/all/results?apikey=SECRETKEY&Query=zelda',
    ).prepare()
    exc = requests.ConnectionError(
        "HTTPConnectionPool(host='jackett', port=9117): Max retries exceeded with url: "
        '/api/v2.0/indexers/all/results?apikey=SECRETKEY&Query=zelda',
        request=request,
    )
    text = arr_connectors._exc_for_log(exc)
    assert 'SECRETKEY' not in text and 'apikey' not in text
    assert text.startswith('ConnectionError')
    assert 'jackett:9117/api/v2.0/indexers/all/results' in text


def test_exc_for_log_scrubs_credential_parameters_from_other_errors():
    text = arr_connectors._exc_for_log(ValueError('bad url http://x/?apikey=SECRETKEY&token=T0K3N&q=1'))
    assert 'SECRETKEY' not in text and 'T0K3N' not in text
    assert 'apikey=***' in text and 'token=***' in text and 'q=1' in text


def _hub_cfg(**overrides):
    cfg = {
        'prowlarr_url': '', 'prowlarr_api_key': '',
        'jackett_url': 'http://jackett:9117', 'jackett_api_key': 'SECRETKEY',
    }
    cfg.update(overrides)
    return cfg


def test_search_failures_do_not_write_the_api_key_to_the_log(monkeypatch, capture):
    records = capture('oneirodex.utils.arr_connectors')
    secret_url = 'http://jackett:9117/api/v2.0/indexers/all/results?apikey=SECRETKEY&Query=zelda'

    def boom(*args, **kwargs):
        raise requests.ConnectionError(
            f"HTTPConnectionPool(host='jackett', port=9117): Max retries exceeded with url: {secret_url[18:]}",
            request=requests.Request('GET', secret_url).prepare(),
        )

    monkeypatch.setattr(arr_connectors, 'get_arr_config', lambda: _hub_cfg())
    monkeypatch.setattr(arr_connectors, 'ready_native_indexers', lambda: [])
    monkeypatch.setattr(arr_connectors, 'fetch_with_challenge_retry', boom)

    assert arr_connectors.search_indexers('zelda') == []

    assert 'Jackett search failed' in records.text
    assert 'ConnectionError' in records.text
    assert 'SECRETKEY' not in records.text


def test_native_indexer_and_prowlarr_failures_are_key_free_too(monkeypatch, capture):
    records = capture('oneirodex.utils.arr_connectors')

    def boom(*args, **kwargs):
        raise requests.ConnectionError('failed: https://idx.example/api?apikey=SECRETKEY&t=search')

    monkeypatch.setattr(arr_connectors, 'get_arr_config', lambda: _hub_cfg(
        jackett_url='', jackett_api_key='', prowlarr_url='http://prowlarr:9696', prowlarr_api_key='SECRETKEY',
    ))
    monkeypatch.setattr(arr_connectors, 'ready_native_indexers', lambda: [
        {'name': 'idx', 'url': 'https://idx.example', 'api_key': 'SECRETKEY'},
    ])
    monkeypatch.setattr(arr_connectors, 'fetch_with_challenge_retry', boom)

    arr_connectors.search_indexers('zelda')

    assert 'Native indexer idx search failed' in records.text
    assert 'Prowlarr search failed' in records.text
    assert 'SECRETKEY' not in records.text


# --------------------------------------------------------------------------
# game server health probe
# --------------------------------------------------------------------------

def _patch_requests(monkeypatch, handler):
    calls: list[str] = []

    def fake(method, url, **kwargs):
        calls.append(url)
        return handler(len(calls), url)

    monkeypatch.setattr(requests, 'request', fake)
    return calls


def test_health_probe_revalidates_every_redirect_hop(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    calls = _patch_requests(monkeypatch, lambda n, url: _response(302, METADATA) if n == 1 else _response(200))
    with app.app_context():
        result = probe_server_health(None, 'http://192.168.1.10:8080/health')
    assert calls == ['http://192.168.1.10:8080/health'], 'the metadata hop was never requested'
    assert result == {
        'reachable': False,
        'method': 'http',
        'status_code': None,
        'error': 'Health URL is not allowed by the outbound policy',
    }


def test_health_probe_still_works_for_a_valid_lan_target(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    _patch_requests(monkeypatch, lambda n, url: _response(200))
    with app.app_context():
        result = probe_server_health(None, 'http://192.168.1.10:8080/health')
    assert result['reachable'] is True and result['status_code'] == 200 and result['error'] is None


def test_health_probe_reports_non_2xx_without_exception_text(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    _patch_requests(monkeypatch, lambda n, url: _response(503))
    with app.app_context():
        result = probe_server_health(None, 'http://192.168.1.10:8080/health')
    assert result['reachable'] is False and result['status_code'] == 503 and result['error'] == 'HTTP 503'


def test_health_probe_refuses_the_lan_when_the_flag_is_off(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', False)
    calls = _patch_requests(monkeypatch, lambda n, url: _response(200))
    with app.app_context():
        result = probe_server_health(None, 'http://192.168.1.10:8080/health')
    assert calls == []
    assert result['error'] == 'Health URL is not allowed by the outbound policy'


def test_health_probe_errors_are_fixed_text(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)

    def boom(n, url):
        raise requests.ConnectionError("HTTPConnectionPool(host='10.1.2.3', port=80): /srv/secret/path refused")

    _patch_requests(monkeypatch, boom)
    with app.app_context():
        result = probe_server_health(None, 'http://192.168.1.10:8080/health')
    assert result['error'] == 'Health URL unreachable'
    assert '/srv/secret' not in str(result)


def test_tcp_probe_error_is_fixed_text(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError(111, '/var/run/secret/path: connection refused')

    monkeypatch.setattr(socket, 'create_connection', boom)
    result = probe_server_health('10.0.0.5:25565', None)
    assert result['method'] == 'tcp' and result['reachable'] is False
    assert result['error'] == 'Connection failed'
    assert '/var/run' not in str(result)


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------

@pytest.fixture
def ollama_app(app, db_session, monkeypatch):
    monkeypatch.setitem(app.config, 'ENABLE_AI_ASSIST', True)
    monkeypatch.setitem(app.config, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    return app


def test_default_loopback_ollama_stays_reachable_when_the_lan_flag_is_off(ollama_app, monkeypatch):
    monkeypatch.setitem(ollama_app.config, 'ALLOW_PRIVATE_LAN_URLS', False)
    calls = _patch_requests(monkeypatch, lambda n, url: _response(200))
    with ollama_app.app_context():
        status = ai_assist.ollama_status()
    assert calls == ['http://127.0.0.1:11434/api/tags']
    assert status['reachable'] is True and status['error'] is None


def test_ollama_redirect_to_cloud_metadata_is_refused(ollama_app, monkeypatch):
    calls = _patch_requests(monkeypatch, lambda n, url: _response(302, METADATA) if n == 1 else _response(200))
    with ollama_app.app_context():
        status = ai_assist.ollama_status()
    assert len(calls) == 1
    assert status['reachable'] is False
    assert status['error'] == 'Ollama URL is not allowed by the outbound policy'


def test_ollama_errors_are_fixed_text(ollama_app, monkeypatch):
    def boom(n, url):
        raise requests.ConnectionError("HTTPConnectionPool(host='127.0.0.1', port=11434): refused at /srv/x")

    _patch_requests(monkeypatch, boom)
    with ollama_app.app_context():
        assert ai_assist.ollama_status()['error'] == 'Ollama unreachable'
        with pytest.raises(ConnectionError) as exc:
            ai_assist._chat('system', 'user')
    assert str(exc.value) == 'Ollama unreachable'


def test_a_saved_ollama_url_is_held_to_the_connector_policy_at_use_time(ollama_app, global_settings, db_session, monkeypatch):
    global_settings.ollama_base_url = 'http://192.168.1.5:11434'
    db_session.commit()

    monkeypatch.setitem(ollama_app.config, 'ALLOW_PRIVATE_LAN_URLS', False)
    calls = _patch_requests(monkeypatch, lambda n, url: _response(200))
    with ollama_app.app_context():
        blocked = ai_assist.ollama_status()
    assert calls == [] and blocked['error'] == 'Ollama URL is not allowed by the outbound policy'

    monkeypatch.setitem(ollama_app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    with ollama_app.app_context():
        allowed = ai_assist.ollama_status()
    assert calls == ['http://192.168.1.5:11434/api/tags'] and allowed['reachable'] is True


# --------------------------------------------------------------------------
# *arr hubs and download clients
# --------------------------------------------------------------------------

LAN_CFG = {
    'prowlarr_url': 'http://192.168.1.30:9696', 'prowlarr_api_key': 'k',
    'qbittorrent_url': 'http://192.168.1.31:8080', 'qbittorrent_username': 'admin', 'qbittorrent_password': 'pw',
    'sabnzbd_url': 'http://192.168.1.32:8080', 'sabnzbd_api_key': 'k',
}


def test_prowlarr_search_revalidates_redirect_hops(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    calls = _patch_requests(monkeypatch, lambda n, url: _response(302, METADATA) if n == 1 else _response(200, body=b'[]'))
    with app.app_context():
        with pytest.raises(BlockedOutboundUrl):
            arr_connectors._search_prowlarr(LAN_CFG, 'zelda', limit=5)
    assert len(calls) == 1


def test_jackett_search_revalidates_redirect_hops(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    cfg = {'jackett_url': 'http://192.168.1.33:9117', 'jackett_api_key': 'SECRETKEY'}
    calls = _patch_requests(monkeypatch, lambda n, url: _response(302, METADATA) if n == 1 else _response(200, body=b'{}'))
    with app.app_context():
        with pytest.raises(BlockedOutboundUrl):
            arr_connectors._search_jackett(cfg, 'zelda', limit=5)
    assert len(calls) == 1


def test_prowlarr_search_still_works_for_a_lan_hub(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    body = b'[{"title": "Zelda", "indexer": "x", "size": 5, "seeders": 3, "downloadUrl": "magnet:?xt=1"}]'
    _patch_requests(monkeypatch, lambda n, url: _response(200, body=body))
    with app.app_context():
        hits = arr_connectors._search_prowlarr(LAN_CFG, 'zelda', limit=5)
    assert [h.title for h in hits] == ['Zelda']


def test_qbittorrent_login_redirect_to_metadata_is_refused(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    monkeypatch.setattr(arr_connectors, 'get_arr_config', lambda: dict(LAN_CFG))
    seen: list[str] = []

    def fake(self, method, url, **kwargs):
        seen.append(url)
        return _response(302, METADATA)

    monkeypatch.setattr(requests.Session, 'request', fake)
    with app.app_context():
        with pytest.raises(BlockedOutboundUrl):
            arr_connectors.qbittorrent_add_url('magnet:?xt=urn:btih:abc')
    assert seen == ['http://192.168.1.31:8080/api/v2/auth/login']


def test_qbittorrent_add_still_works_for_a_lan_client(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    monkeypatch.setattr(arr_connectors, 'get_arr_config', lambda: dict(LAN_CFG))
    seen: list[tuple[str, str]] = []

    def fake(self, method, url, **kwargs):
        seen.append((method, url))
        return _response(200, body=b'Ok.')

    monkeypatch.setattr(requests.Session, 'request', fake)
    with app.app_context():
        result = arr_connectors.qbittorrent_add_url('magnet:?xt=urn:btih:abc')
    assert result['status'] == 'queued'
    assert [m for m, _ in seen] == ['POST', 'POST']


def test_sabnzbd_add_revalidates_redirect_hops(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    monkeypatch.setattr(arr_connectors, 'get_arr_config', lambda: dict(LAN_CFG))
    calls = _patch_requests(monkeypatch, lambda n, url: _response(302, METADATA) if n == 1 else _response(200))
    with app.app_context():
        with pytest.raises(BlockedOutboundUrl):
            arr_connectors.sabnzbd_add_url('https://example.com/a.nzb')
    assert len(calls) == 1


# --------------------------------------------------------------------------
# ambient lighting
# --------------------------------------------------------------------------

def test_hyperion_redirect_to_cloud_metadata_is_refused(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    seen: list[str] = []

    def fake(self, method, url, **kwargs):
        seen.append(url)
        return _response(302, METADATA)

    monkeypatch.setattr(requests.Session, 'request', fake)
    client = ambient_lighting.HyperionClient('http://192.168.1.20:8090')
    with app.app_context():
        with pytest.raises(BlockedOutboundUrl):
            client.set_color((1, 2, 3))
    assert seen == ['http://192.168.1.20:8090/json-rpc']


def test_home_assistant_redirect_to_cloud_metadata_is_refused(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    seen: list[str] = []

    def fake(self, method, url, **kwargs):
        seen.append(url)
        return _response(307, METADATA)

    monkeypatch.setattr(requests.Session, 'request', fake)
    client = ambient_lighting.HomeAssistantClient('http://192.168.1.21:8123', 'token')
    with app.app_context():
        with pytest.raises(BlockedOutboundUrl):
            client.turn_on_scene('scene.play')
    assert seen == ['http://192.168.1.21:8123/api/services/scene/turn_on']


def test_ambient_failure_text_is_fixed_for_transport_errors():
    assert ambient_lighting._failure_text(BlockedOutboundUrl(METADATA, 'x')) == (
        'Lighting URL is not allowed by the outbound policy'
    )
    assert ambient_lighting._failure_text(requests.ConnectionError('http://h/?token=abc /srv/x')) == (
        'Lighting bridge unreachable'
    )
    assert ambient_lighting._failure_text(RuntimeError('Hyperion HTTP 500')) == 'Hyperion HTTP 500'
