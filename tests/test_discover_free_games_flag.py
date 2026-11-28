"""The Discover Free games row obeys ENABLE_FREE_GAMES in the native runtime.

Flask is a dev-only dependency, so the old ``flask.current_app`` lookup raised
ImportError in the Docker image and the switch always read as on.
"""
from __future__ import annotations

import builtins

import pytest

from oneirodex.runtime_native.runtime_context import runtime_config_scope
from oneirodex.utils import discover_providers


@pytest.fixture
def no_flask(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'flask' or name.startswith('flask.'):
            raise ImportError('flask is not installed in the image')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)


@pytest.mark.parametrize('value, expected', [
    (False, False), (True, True), ('false', False), ('0', False), ('true', True),
])
def test_native_config_switch_is_obeyed_without_flask(no_flask, value, expected):
    with runtime_config_scope({'ENABLE_FREE_GAMES': value}):
        assert discover_providers._free_games_enabled() is expected


def test_switched_off_row_is_empty(no_flask):
    with runtime_config_scope({'ENABLE_FREE_GAMES': False}):
        assert discover_providers._free_game_items(None, 10) == []


def test_env_is_used_without_any_config(no_flask, monkeypatch):
    monkeypatch.setenv('ENABLE_FREE_GAMES', 'false')
    with runtime_config_scope(None):
        assert discover_providers._free_games_enabled() is False
    monkeypatch.setenv('ENABLE_FREE_GAMES', 'true')
    with runtime_config_scope(None):
        assert discover_providers._free_games_enabled() is True
