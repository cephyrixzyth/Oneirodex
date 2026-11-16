"""Provider transport failures must not leak RetroAchievements API keys."""

from __future__ import annotations

from unittest.mock import patch

import requests

from oneirodex.utils import retroachievements as ra


def test_member_progress_logs_safe_ra_transport_error(caplog):
    api_key = 'synthetic-ra-key-do-not-log'
    caplog.set_level('INFO', logger='oneirodex.utils.retroachievements')

    with (
        patch.object(ra, 'configured', return_value=True),
        patch.object(ra, 'credentials', return_value=('test-player', api_key)),
        patch.object(
            ra,
            'safe_request',
            side_effect=requests.ConnectionError(
                f'failed https://retroachievements.org/API/endpoint.php?y={api_key}'
            ),
        ),
    ):
        result = ra.fetch_member_progress('test-player', 123)

    assert result is None
    assert 'RetroAchievements request failed (ConnectionError)' in caplog.text
    assert api_key not in caplog.text
