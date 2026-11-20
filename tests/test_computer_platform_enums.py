"""Home-computer LibraryPlatform leaves (ever-made report follow-on).

MSX · ZX Spectrum · Amstrad CPC · Atari ST · Apple II ·
Atari 8-bit · Sharp X68000 · NEC PC-98 · BBC Micro.
Companion honesty; GX4000 stays the Amstrad *console*. No WebRetro WASM.
"""

from types import SimpleNamespace

from oneirodex.platform import (
    Emulator,
    LibraryPlatform,
    WEBRETRO_BROWSER_KEYS,
    WEBRETR_INSTALLED_CORES,
    mapped_core_ids,
    play_mode_for_platform,
    platform_emulator_mapping,
)
from oneirodex.utils.functions import PLATFORM_IDS
from oneirodex.utils.play_url import WEBRETRO_PLATFORMS, browse_play_fields


COMPUTER_KEYS = (
    'MSX', 'ZX_SPECTRUM', 'CPC', 'ATARI_ST', 'APPLE_II',
    'ATARI_8BIT', 'X68000', 'PC_98', 'BBC_MICRO',
)


def test_computer_leaf_enums_exist():
    assert LibraryPlatform.MSX.value == 'MSX'
    assert LibraryPlatform.ZX_SPECTRUM.value == 'ZX Spectrum'
    assert LibraryPlatform.CPC.value == 'Amstrad CPC'
    assert LibraryPlatform.ATARI_ST.value == 'Atari ST'
    assert LibraryPlatform.APPLE_II.value == 'Apple II'
    assert LibraryPlatform.ATARI_8BIT.value == 'Atari 8-bit'
    assert LibraryPlatform.X68000.value == 'Sharp X68000'
    assert LibraryPlatform.PC_98.value == 'NEC PC-98'
    assert LibraryPlatform.BBC_MICRO.value == 'BBC Micro'


def test_cpc_is_not_gx4000():
    assert LibraryPlatform.GX4000.value == 'Amstrad GX4000'
    assert LibraryPlatform.CPC is not LibraryPlatform.GX4000
    assert Emulator.CAP32 in platform_emulator_mapping[LibraryPlatform.CPC]
    assert Emulator.CAP32 in platform_emulator_mapping[LibraryPlatform.GX4000]


def test_computer_leaves_are_companion_not_browser():
    for key in COMPUTER_KEYS:
        assert key not in WEBRETRO_BROWSER_KEYS
        assert key not in WEBRETRO_PLATFORMS
        assert play_mode_for_platform(key) == 'companion'


def test_computer_core_honesty():
    assert mapped_core_ids('MSX') == ['bluemsx']
    assert mapped_core_ids('ZX_SPECTRUM') == ['fuse']
    assert mapped_core_ids('CPC') == ['cap32']
    assert mapped_core_ids('ATARI_ST') == ['hatari']
    assert mapped_core_ids('APPLE_II') == []
    assert mapped_core_ids('ATARI_8BIT') == ['atari800']
    assert mapped_core_ids('X68000') == ['px68k']
    assert mapped_core_ids('PC_98') == ['np2kai']
    assert mapped_core_ids('BBC_MICRO') == []
    for core in ('fuse', 'bluemsx', 'hatari', 'cap32', 'atari800', 'px68k', 'np2kai'):
        assert core not in WEBRETR_INSTALLED_CORES, core
    assert play_mode_for_platform('GX4000') == 'companion'
    assert mapped_core_ids('ATARI_5200') == ['a5200']


def test_browse_play_fields_computers_no_browser():
    for name in COMPUTER_KEYS:
        game = SimpleNamespace(
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            full_disk_path='fixture.rom', library=SimpleNamespace(platform=SimpleNamespace(name=name)),
        )
        fields = browse_play_fields(game)
        assert fields['can_play_in_browser'] is False, name
        assert fields['play_mode'] == 'companion', name
        assert fields['play_url'] is None, name


def test_platform_ids_wired_for_computers():
    assert PLATFORM_IDS.get('MSX') == 27
    assert PLATFORM_IDS.get('ZX_SPECTRUM') == 26
    assert PLATFORM_IDS.get('CPC') == 25
    assert PLATFORM_IDS.get('ATARI_ST') == 63
    assert PLATFORM_IDS.get('APPLE_II') == 75
    assert PLATFORM_IDS.get('ATARI_8BIT') == 65
    assert PLATFORM_IDS.get('X68000') == 121
    assert PLATFORM_IDS.get('PC_98') == 149
    assert PLATFORM_IDS.get('BBC_MICRO') == 69
