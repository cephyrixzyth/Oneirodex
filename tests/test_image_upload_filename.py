"""The upload route must not use caller-controlled route text as a path part."""

from __future__ import annotations

import re
from pathlib import PureWindowsPath

import pytest

from oneirodex.routes_admin_ext.game_images import _game_filename_key


@pytest.mark.parametrize(
    "game_uuid",
    [
        "123e4567-e89b-12d3-a456-426614174000",
        r"..\..\Windows\win.ini",
        r"C:\Users\Public\outside",
        "..%5c..%5coutside",
    ],
)
def test_route_value_becomes_one_safe_windows_filename_component(game_uuid):
    root = PureWindowsPath(r"C:\Oneirodex\library\images")
    filename = f"{_game_filename_key(game_uuid)}_cover_ab12.jpg"
    destination = root / filename

    assert re.fullmatch(r"[0-9a-f]{16}_cover_ab12\.jpg", filename)
    assert destination.is_relative_to(root)
