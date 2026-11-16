"""P0-02 fixture boundaries; guard cases also run with --noconftest."""
import socket

import pytest


@pytest.mark.parametrize('url', [
    'postgresql://fixture:secret-canary@remote.example/household_test',
    'postgresql://fixture:secret-canary@127.0.0.1/household',
    'postgresql://fixture:secret-canary@127.0.0.1/household_test?host=remote.example',
    'postgresql://fixture:secret-canary@127.0.0.1:0/household_test',
    'postgresql://fixture:secret-canary@127.0.0.1:65536/household_test',
    'sqlite:///household_test',
    'not-a-url-secret-canary',
])
def test_household_fixture_rejects_unsafe_target_without_diagnostics(url):
    from tests.fixtures.household_safety import review_database_endpoint

    with pytest.raises(RuntimeError) as error:
        review_database_endpoint(url)
    assert 'secret-canary' not in str(error.value)
    assert 'remote.example' not in str(error.value)


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '[::1]'])
def test_household_fixture_accepts_explicit_loopback_test_database(host):
    from tests.fixtures.household_safety import review_database_endpoint

    assert review_database_endpoint(
        f'postgresql://fixture:secret-canary@{host}:5433/household_test',
    )[1] == 5433


@pytest.mark.parametrize('address', [
    ('store.example', 443), ('127.0.0.1', 25), ('127.0.0.1', 587),
    ('127.0.0.1', 443), ('192.0.2.10', 5432),
])
def test_household_fixture_blocks_provider_and_smtp_before_connect(monkeypatch, address):
    from tests.fixtures.household_safety import allow_database_sockets_only

    calls = []
    monkeypatch.setattr(socket.socket, 'connect', lambda *args: calls.append(args))
    allow_database_sockets_only(monkeypatch, ('127.0.0.1', 5432))
    with socket.socket() as sock:
        with pytest.raises(RuntimeError, match='fixture network boundary'):
            sock.connect(address)
    assert calls == []


def test_household_fixture_rejects_external_dns_before_resolving(monkeypatch):
    from tests.fixtures.household_safety import allow_database_sockets_only

    calls = []
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *args, **kwargs: calls.append(args))
    allow_database_sockets_only(monkeypatch, ('127.0.0.1', 5432))
    with pytest.raises(RuntimeError, match='fixture network boundary'):
        socket.getaddrinfo('store.example', 443)
    assert calls == []


def test_household_fixture_leaves_database_connection_available(monkeypatch):
    from tests.fixtures.household_safety import allow_database_sockets_only

    calls = []
    monkeypatch.setattr(socket.socket, 'connect', lambda sock, address: calls.append(address))
    allow_database_sockets_only(monkeypatch, ('127.0.0.1', 5432))
    with socket.socket() as sock:
        sock.connect(('127.0.0.1', 5432))
    assert calls == [('127.0.0.1', 5432)]
