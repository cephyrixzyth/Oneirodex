"""A failed connector call must not hand its API key or internal address to the browser.

``acquire_download`` answered ``api_error(str(exc))``. The text of a ``requests``
failure carries the request URL, and SABnzbd (``?apikey=``) and AllDebrid take
the key in the query string; with the pinned dial the URL also holds the
internal IP the hostname resolved to. Librarians (not just admins) can call it.
"""

from __future__ import annotations

import ipaddress
import logging
from uuid import uuid4

import pytest
import requests

from oneirodex.models import User
from oneirodex.utils import security
from oneirodex.utils.arr_connectors import client_error_message

SAB_KEY = 'SABKEY-SECRET-123'
DEBRID_KEY = 'ALLDEBRID-SECRET-456'
INTERNAL_IP = '10.9.8.7'


@pytest.fixture
def librarian(db_session):
    uid = str(uuid4())
    user = User(name=f'acq_{uid[:8]}', email=f'acq_{uid[:8]}@example.com', role='admin', user_id=uid, state=True)
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def signed_in(client, librarian):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(librarian.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def sabnzbd_down(monkeypatch):
    """SABnzbd configured on a hostname, and every connection to it failing the way urllib3 words it."""
    monkeypatch.setattr('oneirodex.routes_apis.acquire.arr_module_on', lambda: True)
    monkeypatch.setattr(
        'oneirodex.utils.arr_connectors.get_arr_config',
        lambda: {'sabnzbd_url': 'http://sab.lan:8080', 'sabnzbd_api_key': SAB_KEY},
    )
    monkeypatch.setattr(security, 'allow_private_lan_urls_enabled', lambda: True)
    monkeypatch.setattr(
        security, '_resolve_host',
        lambda host: [ipaddress.ip_address(INTERNAL_IP if host == 'sab.lan' else '93.184.216.34')],
    )

    def refuse(adapter, request, **kwargs):
        raise requests.ConnectionError(
            f"HTTPConnectionPool(host='{INTERNAL_IP}', port=8080): Max retries exceeded with url: "
            f'{request.path_url} (Caused by NewConnectionError("Failed to establish a new connection"))'
        )

    monkeypatch.setattr(requests.adapters.HTTPAdapter, 'send', refuse)


def test_a_down_sabnzbd_does_not_leak_its_api_key_or_address(signed_in, sabnzbd_down, caplog):
    with caplog.at_level(logging.WARNING):
        response = signed_in.post('/api/acquire/download', json={'url': 'https://example.com/x.nzb', 'provider': 'sabnzbd'})
    assert response.status_code == 502
    body = response.get_json()
    assert body['error_code'] == 'bad_gateway'
    text = response.get_data(as_text=True)
    assert SAB_KEY not in text and INTERNAL_IP not in text and 'apikey' not in text
    assert 'Could not reach' in body['error']
    assert SAB_KEY not in caplog.text, 'the log must not hold the key either'


def test_the_connector_error_helper_wording_for_each_failure_class(caplog):
    leaky = f'/api?mode=addurl&apikey={SAB_KEY}&output=json'
    timeout = client_error_message(requests.ReadTimeout(f'Read timed out. url: {leaky}'))
    assert 'did not respond in time' in timeout and SAB_KEY not in timeout

    response = requests.Response()
    response.status_code = 401
    http = client_error_message(requests.HTTPError(f'401 Client Error: Unauthorized for url: https://x?apikey={DEBRID_KEY}',
                                                   response=response))
    assert '401' in http and DEBRID_KEY not in http

    other = client_error_message(requests.TooManyRedirects(f'Exceeded 5 redirects: {leaky}'))
    assert SAB_KEY not in other

    ours = client_error_message(RuntimeError(f'upstream said apikey={DEBRID_KEY} is wrong'))
    assert DEBRID_KEY not in ours and 'apikey=***' in ours

    unexpected = client_error_message(KeyError('sqlalchemy.exc: SELECT ... password'))
    assert unexpected == 'The request to the download service failed'


def test_a_blocked_destination_keeps_its_reason(signed_in, monkeypatch):
    """Validator reasons are fixed strings and useful to the operator; they pass through."""
    from oneirodex.utils.http_safe import BlockedOutboundUrl

    monkeypatch.setattr('oneirodex.routes_apis.acquire.arr_module_on', lambda: True)

    def blocked(*_a, **_k):
        raise BlockedOutboundUrl('http://169.254.169.254/?apikey=zzz', 'URL host is not allowed')

    monkeypatch.setattr('oneirodex.routes_apis.acquire.send_to_download_client', blocked)
    body = signed_in.post('/api/acquire/download', json={'url': 'magnet:?xt=urn:btih:abc', 'provider': 'qbittorrent'}).get_json()
    assert body['error'] == 'Blocked outbound URL: URL host is not allowed'
    assert 'zzz' not in str(body) and '169.254' not in str(body)


def test_a_debrid_http_error_does_not_leak_the_query_string_key(signed_in, monkeypatch):
    monkeypatch.setattr('oneirodex.routes_apis.acquire.debrid_enabled', lambda: True)
    response = requests.Response()
    response.status_code = 401

    def rejected(_magnet):
        raise requests.HTTPError(
            f'401 Client Error: Unauthorized for url: https://api.alldebrid.com/v4/magnet/upload?agent=Oneirodex&apikey={DEBRID_KEY}',
            response=response,
        )

    monkeypatch.setattr('oneirodex.routes_apis.acquire.alldebrid_upload_magnet', rejected)
    reply = signed_in.post('/api/acquire/download', json={'magnet': 'magnet:?xt=urn:btih:abc', 'provider': 'alldebrid'})
    assert reply.status_code == 502
    assert DEBRID_KEY not in reply.get_data(as_text=True)
    assert '401' in reply.get_json()['error']


def test_acquire_search_failures_do_not_echo_exception_text(signed_in, monkeypatch):
    monkeypatch.setattr('oneirodex.routes_apis.acquire.arr_module_on', lambda: True)

    def boom(_query):
        raise RuntimeError(f'Jackett query failed: ?apikey={SAB_KEY}&Query=x')

    monkeypatch.setattr('oneirodex.routes_apis.acquire.search_indexers', boom)
    reply = signed_in.get('/api/acquire/search?q=halo')
    assert reply.status_code == 502
    assert SAB_KEY not in reply.get_data(as_text=True)


def test_the_admin_download_route_no_longer_500s_or_leaks(signed_in, monkeypatch):
    """``/api/arr/download`` caught only RuntimeError; a ConnectionError escaped as a 500."""
    monkeypatch.setattr('oneirodex.routes_arr.arr_module_on', lambda: True)

    def down(_url):
        raise requests.ConnectionError(f"HTTPConnectionPool(host='{INTERNAL_IP}', port=8080): Max retries exceeded")

    monkeypatch.setattr('oneirodex.routes_arr.qbittorrent_add_url', down)
    reply = signed_in.post('/api/arr/download', json={'download_url': 'magnet:?xt=urn:btih:abc'})
    assert reply.status_code == 502
    body = reply.get_json()
    assert body['error_code'] == 'bad_gateway'
    assert INTERNAL_IP not in reply.get_data(as_text=True)
