"""Provider transport failures must not leak RetroAchievements API keys."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from oneirodex.utils import retroachievements as ra


def test_member_progress_logs_safe_ra_transport_error(caplog, monkeypatch):
    api_key = 'synthetic-ra-key-do-not-log'
    caplog.set_level('INFO', logger='oneirodex.utils.retroachievements')
    monkeypatch.setattr('oneirodex.utils.security.is_blocked_outbound_host', lambda *_a, **_k: False)

    with (
        patch.object(ra, 'configured', return_value=True),
        patch.object(ra, 'credentials', return_value=('test-player', api_key)),
        patch.object(
            ra,
            'safe_request',
            side_effect=requests.ConnectionError(
                f'failed https://retroachievements.org/API/endpoint.php?y={api_key}'
            ),
        ) as mock_request,
    ):
        result = ra.fetch_member_progress('test-player', 123)

    assert result is None
    assert 'RetroAchievements request failed (ConnectionError)' in caplog.text
    assert api_key not in caplog.text
    assert mock_request.call_args.kwargs['validator']('http://api.example/path')[0] is False


def test_ra_http_error_keeps_status_without_request_url():
    api_key = 'synthetic-ra-key-do-not-log'
    error = requests.HTTPError(
        f'401 Client Error for https://retroachievements.org/API/game.php?y={api_key}'
    )
    error.response = SimpleNamespace(status_code=401)
    response = MagicMock()
    response.raise_for_status.side_effect = error

    with (
        patch.object(ra, 'credentials', return_value=('test-player', api_key)),
        patch.object(ra, 'safe_request', return_value=response),
    ):
        try:
            ra._api_get('game.php', {})
        except RuntimeError as raised:
            assert str(raised) == 'RetroAchievements request failed (HTTPError) (401)'
            assert raised.__suppress_context__ is True
            assert api_key not in str(raised)
        else:
            raise AssertionError('Expected sanitized RetroAchievements request failure')
