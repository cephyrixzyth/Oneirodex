"""Standalone update/patch packages are not games (found in a real scan export).

On a household library, `Beast of Reincarnation update 1.0.7.0 - 1.0.8.0` was
imported as the game "Beast of Reincarnation" (so the real game folder was then
flagged a duplicate of its own update), and `Alan Wake 2 update 1.2.8 - 1.2.10`
was imported as *Alan Wake*. Names below are taken from that export.
"""
import pytest

from oneirodex.utils.game_name_parse import looks_like_patch_package


@pytest.mark.parametrize('name', [
    'Beast of Reincarnation update 1.0.7.0 - 1.0.8.0',
    'Alan Wake 2 update 1.2.8 - 1.2.10',
    'Grim Dawn Update_from_v1.3.0.0_to_v1.3.0.3-ElAmigos',
    'Aliens_Fireteam_Elite_2_Update_from_v1.0.0_to_v1.0.2a-ElAmigos',
    'Automobilista 2 Update from_v1.6.9.8_to_v1.6.9.91',
    'Dragon Ball Sparking ZERO Update_from_v29.07.2026_to_v04.09.2026',
    'The Witcher 3 Wild_Hunt_Remastered_Update_from_v5.00b_to_v5.00c-ElAmigos',
    'Sengoku Dynasty Update v1.2.3.0',
    'MX vs ATV Legends Motocross World Tour Update v5.09 incl DLC',
    'Vampire The Masquerade Bloodlines 1 Unofficial Patch (82662)',
])
def test_standalone_update_packages_are_detected(name):
    assert looks_like_patch_package(name)


@pytest.mark.parametrize('name', [
    # A full release that bundles updates is a game.
    'Call of Cthulhu (incl. Update 2)',
    'Black Clover Quartet Knights (Incl  Update 5)',
    'Strider (Incl  Update 1)',
    'Dragon\'s Dogma Dark Arisen (Incl Update 7)',
    # Titles that merely contain the words.
    'Update Quest',
    'Patch Quest 2',
    'Cyberpunk 2077 Ultimate Edition',
    'Hades II',
    '',
])
def test_full_releases_and_ordinary_titles_are_not(name):
    assert not looks_like_patch_package(name)


def test_none_and_non_strings_are_safe():
    assert looks_like_patch_package(None) is False
    assert looks_like_patch_package(123) is False
