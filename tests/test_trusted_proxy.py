from pathlib import Path
from types import SimpleNamespace

from starlette.datastructures import Headers
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Response

from oneirodex.utils.trusted_proxy import (
    forwarded_client_ip,
    trusted_forwarded_for,
    trusted_proxy_peer,
)
from oneirodex.utils.proxy import apply_proxy_fix
from oneirodex.runtime_native.password_reset_confirm import _trusted_public_origin

ROOT = Path(__file__).resolve().parents[1]


def _request(peer, forwarded):
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=Headers({'X-Forwarded-For': forwarded}),
    )


def test_forwarded_ip_is_ignored_for_untrusted_peer_even_when_proxy_hops_enabled():
    request = _request('192.0.2.8', '198.51.100.4')

    assert not trusted_proxy_peer(request, {'TRUSTED_PROXY_CIDRS': '192.0.2.16/28'})
    assert forwarded_client_ip(
        request,
        {'TRUSTED_PROXIES': 1, 'TRUSTED_PROXY_CIDRS': '10.10.0.0/24'},
    ) == '192.0.2.8'


def test_forwarded_ip_is_used_for_allowlisted_proxy_peer():
    request = _request('10.10.0.8', '203.0.113.7, 198.51.100.4')

    assert trusted_proxy_peer(request, {'TRUSTED_PROXY_CIDRS': '10.10.0.0/24'})
    assert forwarded_client_ip(
        request,
        {'TRUSTED_PROXIES': 1, 'TRUSTED_PROXY_CIDRS': '10.10.0.0/24'},
    ) == '198.51.100.4'


def test_session_fingerprint_forwarding_requires_allowlisted_immediate_peer():
    config = {'TRUSTED_PROXIES': 1, 'TRUSTED_PROXY_CIDRS': '10.10.0.0/24'}
    request = _request('192.0.2.8', '203.0.113.7, 198.51.100.4')

    assert trusted_forwarded_for(request, config) is None

    request.client.host = '10.10.0.8'
    assert trusted_forwarded_for(request, config) == '198.51.100.4'
    assert trusted_forwarded_for(
        request,
        {'TRUSTED_PROXIES': 0, 'TRUSTED_PROXY_CIDRS': '10.10.0.0/24'},
    ) is None


def test_invalid_forwarded_ip_falls_back_to_proxy_peer():
    request = _request('10.10.0.8', 'attacker-controlled-value')

    assert forwarded_client_ip(
        request,
        {'TRUSTED_PROXIES': 1, 'TRUSTED_PROXY_CIDRS': '10.10.0.0/24'},
    ) == '10.10.0.8'


def test_flask_proxy_fix_is_gated_by_immediate_peer_cidr():
    observed = []

    def original_app(environ, start_response):
        observed.append((environ['REMOTE_ADDR'], environ.get('wsgi.url_scheme')))
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'ok']

    app = SimpleNamespace(
        config={'TRUSTED_PROXIES': 1, 'TRUSTED_PROXY_CIDRS': '10.10.0.0/24'},
        wsgi_app=original_app,
    )
    assert apply_proxy_fix(app)

    for peer in ('192.0.2.8', '10.10.0.8'):
        environ = EnvironBuilder(
            path='/',
            headers={'X-Forwarded-For': '198.51.100.4', 'X-Forwarded-Proto': 'https'},
            environ_base={'REMOTE_ADDR': peer},
        ).get_environ()
        Response.from_app(app.wsgi_app, environ)

    assert observed == [('192.0.2.8', 'http'), ('198.51.100.4', 'https')]


def test_supported_launchers_disable_uvicorn_implicit_proxy_rewriting():
    for path in ('startweb.sh', 'startweb-docker.sh', 'startweb_windows.cmd'):
        assert '--no-proxy-headers' in (ROOT / path).read_text(encoding='utf-8')
    assert 'proxy_headers=False' in (ROOT / 'scripts/serve_capture.py').read_text(encoding='utf-8')
    assert '--no-proxy-headers' in (ROOT / 'oneirodex_standalone/launcher.py').read_text(encoding='utf-8')


def test_password_reset_origin_ignores_forwarded_host_from_untrusted_peer(monkeypatch):
    from oneirodex.utils import global_settings, trusted_host

    monkeypatch.setattr(global_settings, 'global_settings_row', lambda: SimpleNamespace(site_url=''))
    monkeypatch.setattr(trusted_host, 'parse_trusted_hosts', lambda _raw: {'library.example'})
    monkeypatch.setattr(trusted_host, 'host_is_trusted', lambda host, allowed: host in allowed)
    config = {
        'TRUSTED_PROXIES': 1,
        'TRUSTED_PROXY_CIDRS': '10.10.0.0/24',
        'TRUSTED_LINK_HOSTS': 'library.example',
    }

    request = SimpleNamespace(
        client=SimpleNamespace(host='192.0.2.8'),
        url=SimpleNamespace(scheme='http'),
        headers=Headers({
            'host': 'internal',
            'X-Forwarded-Host': 'library.example',
            'X-Forwarded-Proto': 'https',
        }),
    )
    assert _trusted_public_origin(request, config) == 'http://127.0.0.1'

    request.client.host = '10.10.0.8'
    assert _trusted_public_origin(request, config) == 'https://library.example'
