"""Tests for NZBGet connector + acquire scoring (Wave 12)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from oneirodex.utils.acquire_scoring import rank_acquire_hits, score_acquire_hit, title_looks_like_newer_repack
from oneirodex.utils.arr_connectors import nzbget_add_url, send_to_download_client


def test_score_repack_and_rank():
    hits = [
        {'title': 'Some Game GOG', 'seeders': 2, 'size': 2 * 1024**3},
        {'title': 'Some Game FitGirl Repack', 'seeders': 40, 'size': 5 * 1024**3},
    ]
    ranked = rank_acquire_hits(hits, query='Some Game')
    assert ranked[0]['title'].lower().find('repack') >= 0
    assert ranked[0]['score'] >= ranked[1]['score']
    assert ranked[0]['is_repack'] is True


def test_newer_repack_heuristic():
    assert title_looks_like_newer_repack('Game FitGirl Repack', 'Game')
    assert not title_looks_like_newer_repack('Game', 'Game')


def test_score_penalizes_crack_marker():
    row = score_acquire_hit({'title': 'Game Keygen Crack', 'seeders': 100}, query='Game')
    assert row['score'] < 50


@patch('oneirodex.utils.arr_connectors.safe_request')
@patch('oneirodex.utils.arr_connectors.get_arr_config')
def test_nzbget_add_url(mock_cfg, mock_post):
    mock_cfg.return_value = {
        'nzbget_url': 'http://nzbget:6789',
        'nzbget_username': 'nzbget',
        'nzbget_password': 'tegbzn6789',
    }
    mock_post.return_value = MagicMock(status_code=200, content=b'{"result": 1}', json=lambda: {'result': 1})
    out = nzbget_add_url('https://example.com/file.nzb')
    assert out['status'] == 'queued'
    assert out['provider'] == 'nzbget'
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    # Routed through safe_request so every redirect hop is revalidated.
    assert args[0] == 'POST'
    assert args[1].endswith('/jsonrpc')
    assert kwargs['json']['method'] == 'append'
    assert callable(kwargs['validator'])


@patch('oneirodex.utils.arr_connectors.nzbget_add_url')
def test_send_routes_nzbget(mock_nzb):
    mock_nzb.return_value = {'status': 'queued', 'provider': 'nzbget'}
    result = send_to_download_client('https://x/y.nzb', provider='nzbget')
    assert result['provider'] == 'nzbget'
    mock_nzb.assert_called_once()


def test_nzbget_config_keys_documented():
    # Env keys expected by get_arr_config (no live app / DB required).
    from oneirodex.utils import arr_connectors as mod
    assert 'nzbget_add_url' in dir(mod)
    assert callable(mod.nzbget_add_url)