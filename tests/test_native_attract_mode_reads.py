"""Framework-free Attract Mode public settings projection tests."""
from types import SimpleNamespace

from oneirodex.runtime_native.attract_mode_reads import AttractModeData


def test_attract_mode_projection_merges_user_overrides_without_mutating_defaults():
    defaults = {
        'filters': {'library_uuid': None, 'genres': [1], 'themes': [], 'date_from': None, 'date_to': None},
        'autoplay': {'enabled': True, 'skipFirst': 0, 'skipAfter': 0},
    }
    custom = SimpleNamespace(
        has_customized=True,
        filter_settings={'genres': [9]},
        autoplay_settings={'enabled': False, 'skipAfter': 45},
    )
    data = AttractModeData(
        global_reader=lambda: SimpleNamespace(
            attract_mode_enabled=True,
            attract_mode_idle_timeout=75,
            attract_mode_settings=defaults,
        ),
        user_reader=lambda user_id: custom if user_id == 'user-guid' else None,
    )

    result = data.payload(SimpleNamespace(user_id='user-guid'))

    assert result == {
        'enabled': True,
        'idle_timeout': 75,
        'settings': {
            'filters': {'genres': [9]},
            'autoplay': {'enabled': False, 'skipAfter': 45},
        },
    }
    assert defaults['filters']['genres'] == [1]


def test_disabled_attract_mode_is_anonymous_safe_and_skips_user_query():
    queried = []
    data = AttractModeData(
        global_reader=lambda: SimpleNamespace(attract_mode_enabled=False),
        user_reader=lambda user_id: queried.append(user_id),
    )

    assert data.payload(SimpleNamespace(user_id='private-user-id')) == {
        'enabled': False, 'idle_timeout': 0, 'settings': None,
    }
    assert queried == []


def test_missing_settings_use_the_shared_attract_mode_defaults():
    data = AttractModeData(
        global_reader=lambda: SimpleNamespace(
            attract_mode_enabled=True,
            attract_mode_idle_timeout=60,
            attract_mode_settings=None,
        ),
        user_reader=lambda _user_id: None,
    )

    assert data.payload(None)['settings'] == {
        'filters': {
            'library_uuid': None, 'genres': [], 'themes': [],
            'date_from': None, 'date_to': None,
        },
        'autoplay': {'enabled': True, 'skipFirst': 0, 'skipAfter': 0},
    }
