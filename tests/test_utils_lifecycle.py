"""Unit tests for web lifecycle helpers."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from oneirodex.utils.lifecycle import (
    FRESHNESS_BEHIND_STATUSES,
    game_has_updates_available,
    web_client_connected,
    web_lifecycle_fields,
    web_lifecycle_state,
)


def test_web_client_connected_is_false_without_user():
    assert web_client_connected() is False
    assert web_client_connected(user_id=None) is False


def test_web_client_connected_override():
    assert web_lifecycle_fields(
        SimpleNamespace(freshness_status=None, updates=[]),
        client_connected=True,
    )['client_connected'] is True


def test_not_downloaded_when_no_signals():
    game = SimpleNamespace(freshness_status=None, updates=[])
    assert game_has_updates_available(game) is False
    assert web_lifecycle_state(game) == 'not_downloaded'
    assert web_lifecycle_fields(game) == {
        'lifecycle_state': 'not_downloaded',
        'client_connected': False,
        'has_updates': False,
        'updates_count': 0,
    }


def test_update_available_from_freshness_status():
    for status in FRESHNESS_BEHIND_STATUSES:
        game = SimpleNamespace(freshness_status=status, updates=[])
        assert game_has_updates_available(game) is True
        assert web_lifecycle_state(game) == 'update_available'


def test_update_available_from_updates_relation():
    game = SimpleNamespace(freshness_status=None, updates=[Mock()])
    assert game_has_updates_available(game) is True
    assert web_lifecycle_state(game) == 'update_available'


def test_update_available_from_updates_count():
    game = SimpleNamespace(freshness_status=None, updates=[])
    assert game_has_updates_available(game, updates_count=2) is True
    assert web_lifecycle_state(game, updates_count=2) == 'update_available'


def test_updates_count_zero_does_not_trigger_without_freshness():
    game = SimpleNamespace(freshness_status=None, updates=[])
    assert web_lifecycle_state(game, updates_count=0) == 'not_downloaded'


def test_serialize_discover_game_includes_lifecycle_fields(app):
    from oneirodex.routes_discover import serialize_discover_game

    game = SimpleNamespace(
        id=1,
        uuid='discover-game',
        name='Discover Game',
        summary='Summary',
        url=None,
        size=0,
        genres=[],
        first_release_date=None,
        date_identified=None,
        date_created=None,
        freshness_status='behind',
        player_perspectives=[],
    )

    # Patch the helper where the serializer resolves it, not on the legacy
    # route module that no longer owns discover serialization.
    with app.app_context(), patch(
        'oneirodex.utils.discover_projections.resolve_game_cover_url',
        return_value='/static/newstyle/default_cover.jpg',
    ):
        result = serialize_discover_game(
            game,
            None,
            is_favorite=False,
            has_local_override=False,
            user_id=None,
        )

    assert result['lifecycle_state'] == 'update_available'
    assert result['client_connected'] is False
