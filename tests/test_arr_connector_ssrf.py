"""O7 — Acquire / *arr LAN SSRF allow-flag."""

from __future__ import annotations

import pytest

from oneirodex.utils.arr_connectors import save_arr_config
from oneirodex.utils.security import (
    validate_connector_http_url,
    validate_user_outbound_http_url,
)


def test_connector_url_respects_lan_flag(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', False)
    with app.app_context():
        ok, _ = validate_connector_http_url('http://192.168.1.50:9696')
        assert ok is False

    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    with app.app_context():
        ok, cleaned = validate_connector_http_url('http://192.168.1.50:9696')
        assert ok is True
        assert '192.168.1.50' in cleaned


def test_user_outbound_never_allows_lan_even_with_flag(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    with app.app_context():
        ok, msg = validate_user_outbound_http_url('http://10.0.0.5/file.nzb')
        assert ok is False
        assert 'not allowed' in msg.lower() or 'host' in msg.lower()


def test_save_arr_config_rejects_lan_without_flag(app, db_session, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', False)
    with app.app_context():
        with pytest.raises(ValueError, match='ALLOW_PRIVATE_LAN_URLS'):
            save_arr_config({'prowlarr_url': 'http://192.168.1.50:9696'})


def test_save_arr_config_accepts_lan_with_flag(app, db_session, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    with app.app_context():
        saved = save_arr_config({'prowlarr_url': 'http://192.168.1.50:9696/'})
        assert saved['prowlarr_url'] == 'http://192.168.1.50:9696'


def test_save_arr_config_rejects_metadata_with_flag(app, db_session, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    with app.app_context():
        with pytest.raises(ValueError, match='not allowed|host'):
            save_arr_config({'qbittorrent_url': 'http://169.254.169.254/'})


def test_save_arr_config_names_a_malformed_url_without_the_lan_hint(app, db_session, monkeypatch):
    """The LAN flag cannot fix a URL two parsers read differently; the hint sent admins the wrong way."""
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', False)
    with app.app_context():
        with pytest.raises(ValueError, match='Invalid URL') as raised:
            save_arr_config({'qbittorrent_url': 'http://192.168.1.50\\@example.com/'})
    assert 'ALLOW_PRIVATE_LAN_URLS' not in str(raised.value)
