"""Unit tests for game server health probes."""

from oneirodex.utils.game_servers import parse_connect_string, probe_server_health


def test_parse_connect_string():
    assert parse_connect_string('192.168.1.10:25565') == ('192.168.1.10', 25565)
    assert parse_connect_string('tcp://games.local:7777') == ('games.local', 7777)


def test_probe_server_health_http(monkeypatch):
    class FakeResponse:
        status_code = 200

        def close(self):
            pass

    monkeypatch.setattr(
        'oneirodex.utils.game_servers.safe_request',
        lambda *args, **kwargs: FakeResponse(),
    )
    result = probe_server_health(None, 'http://127.0.0.1/health')
    assert result['reachable'] is True
    assert result['method'] == 'http'
