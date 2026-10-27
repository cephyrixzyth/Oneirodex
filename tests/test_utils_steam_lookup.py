"""Tests for Steam App ID title lookup (mocked HTTP)."""

from unittest.mock import MagicMock, patch

from oneirodex.utils.steam_lookup import fetch_steam_title_by_app_id
import pytest

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- Steam lookup adapter.


@patch('oneirodex.utils.steam_lookup.safe_request')
def test_fetch_steam_title_success(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {'89881': {'success': True, 'data': {'name': 'Barony'}}},
    )
    assert fetch_steam_title_by_app_id(89881) == 'Barony'


@patch('oneirodex.utils.steam_lookup.safe_request')
def test_fetch_steam_title_missing_app(mock_get):
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {'1': {'success': False}},
    )
    assert fetch_steam_title_by_app_id(1) is None


@patch('oneirodex.utils.steam_lookup.safe_request')
def test_fetch_steam_title_network_error(mock_get):
    import requests
    mock_get.side_effect = requests.RequestException('boom')
    assert fetch_steam_title_by_app_id(89881) is None


def test_fetch_steam_title_invalid_id():
    assert fetch_steam_title_by_app_id(0) is None
    assert fetch_steam_title_by_app_id(-5) is None
