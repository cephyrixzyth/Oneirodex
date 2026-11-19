"""Wave 19 — play_mode honesty and new platform enums (no DB)."""

from types import SimpleNamespace

from oneirodex.platform import (
    LibraryPlatform,
    cheat_surface_for_platform,
    platforms_for_play_mode,
    play_mode_for_platform,
)
from oneirodex.utils.play_url import browse_play_fields


def test_new_wave19_platforms_exist():
    assert LibraryPlatform.WII.value == 'Nintendo Wii'
    assert LibraryPlatform.N3DS.value == 'Nintendo 3DS'
    assert LibraryPlatform.SEGA_DC.value == 'Sega Dreamcast'
    assert LibraryPlatform.PSVITA.value == 'Sony PS Vita'
    assert LibraryPlatform.VICE_X64SC.value == 'Commodore 64'


def test_play_mode_matrix():
    assert play_mode_for_platform('NES') == 'browser'
    assert play_mode_for_platform('PS5') == 'catalog'
    assert play_mode_for_platform('XSX') == 'catalog'
    assert play_mode_for_platform('WII') == 'companion'
    assert play_mode_for_platform('NGC') == 'companion'
    assert play_mode_for_platform('PCE') == 'companion'
    assert play_mode_for_platform('SEGA_DC') == 'companion'
    assert play_mode_for_platform('N3DS') == 'companion'
    assert play_mode_for_platform('PSVITA') == 'companion'
    assert play_mode_for_platform('PS2') == 'companion'
    assert play_mode_for_platform(None) == 'none'


def test_platforms_for_play_mode_matches_matrix():
    catalog = {plat.name for plat in platforms_for_play_mode('catalog')}
    assert 'SWITCH' in catalog
    assert 'PS5' in catalog
    assert 'NES' not in catalog
    assert platforms_for_play_mode('nope') == []


def test_browse_play_fields_catalog_only():
    library = SimpleNamespace(platform=SimpleNamespace(name='PS5'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is False
    assert fields['play_mode'] == 'catalog'
    assert fields['play_blocker'] == 'catalog_only'
    assert fields['play_url'] is None


def test_browse_play_fields_companion_no_fake_play(monkeypatch):
    library = SimpleNamespace(platform=SimpleNamespace(name='WII'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['dolphin'], 'preferred': 'dolphin'},
    )
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is False
    assert fields['play_mode'] == 'companion'
    assert fields['play_url'] is None
    assert fields['play_blocker'] == 'companion_preferred'
    assert 'dolphin' in (fields.get('companion_cores') or [])
    assert 'Dolphin' in (fields.get('companion_hint') or '')


def test_wave19c_gamecube_companion_hint():
    library = SimpleNamespace(platform=SimpleNamespace(name='NGC'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is False
    assert fields['play_mode'] == 'companion'
    assert 'dolphin' in (fields.get('companion_cores') or [])
    assert 'GameCube' in (fields.get('companion_hint') or '')


def test_wave19d_dreamcast_and_3ds_companion():
    assert play_mode_for_platform('SEGA_DC') == 'companion'
    assert play_mode_for_platform('N3DS') == 'companion'
    dc = browse_play_fields(
        SimpleNamespace(
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            full_disk_path='fixture.rom', library=SimpleNamespace(platform=SimpleNamespace(name='SEGA_DC')),
        )
    )
    assert dc['play_blocker'] == 'companion_preferred'
    assert 'flycast' in (dc.get('companion_cores') or [])
    assert 'Flycast' in (dc.get('companion_hint') or '')
    n3 = browse_play_fields(
        SimpleNamespace(
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            full_disk_path='fixture.rom', library=SimpleNamespace(platform=SimpleNamespace(name='N3DS')),
        )
    )
    assert 'citra' in (n3.get('companion_cores') or [])


def test_wave19e_ps2_and_vita_companion():
    ps2 = browse_play_fields(
        SimpleNamespace(
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            full_disk_path='fixture.rom', library=SimpleNamespace(platform=SimpleNamespace(name='PS2')),
        )
    )
    assert ps2['play_mode'] == 'companion'
    assert 'pcsx2' in (ps2.get('companion_cores') or [])
    vita = browse_play_fields(
        SimpleNamespace(
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            full_disk_path='fixture.rom', library=SimpleNamespace(platform=SimpleNamespace(name='PSVITA')),
        )
    )
    assert 'vita3k' in (vita.get('companion_cores') or [])


def test_wave19f_catalog_current_gen():
    assert play_mode_for_platform('PS5') == 'catalog'
    assert play_mode_for_platform('XSX') == 'catalog'
    assert play_mode_for_platform('PS3') == 'companion'


def test_wave19a_pce_companion_cores_until_wasm(monkeypatch):
    library = SimpleNamespace(platform=SimpleNamespace(name='PCE'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['mednafen_pce_fast'], 'preferred': 'mednafen_pce_fast'},
    )
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is False
    assert fields['play_mode'] == 'companion'
    assert 'mednafen_pce_fast' in (fields.get('companion_cores') or [])


def test_wave19a_c64_companion_until_wasm(monkeypatch):
    assert play_mode_for_platform('VICE_X64SC') == 'companion'
    library = SimpleNamespace(platform=SimpleNamespace(name='VICE_X64SC'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['vice_x64'], 'preferred': 'vice_x64'},
    )
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is False
    assert 'vice_x64' in (fields.get('companion_cores') or [])


def test_wave19a_browser_unlocks_when_wasm_vendored(monkeypatch):
    monkeypatch.setattr(
        'oneirodex.platform.WEBRETR_INSTALLED_CORES',
        frozenset({'mednafen_pce_fast'}),
    )
    from oneirodex.platform import play_mode_for_platform as pm

    assert pm('PCE') == 'browser'


def test_wave19a_vice_browser_unlocks_when_wasm_vendored(monkeypatch):
    monkeypatch.setattr(
        'oneirodex.platform.WEBRETR_INSTALLED_CORES',
        frozenset({'vice_x64'}),
    )
    from oneirodex.platform import play_mode_for_platform as pm

    assert pm('VICE_X64SC') == 'browser'


def test_wave19b_pcdos_companion_by_default():
    assert play_mode_for_platform('PCDOS') == 'companion'
    library = SimpleNamespace(platform=SimpleNamespace(name='PCDOS'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is False
    assert fields['play_mode'] == 'companion'
    assert fields['play_blocker'] == 'pcdos_flag_off'
    assert 'dosbox_pure' in (fields.get('companion_cores') or [])
    assert fields.get('companion_hint')


def test_wave19b_pcdos_browser_when_flag_and_wasm(monkeypatch):
    monkeypatch.setattr('oneirodex.platform.pcdos_browser_enabled', lambda: True)
    monkeypatch.setattr(
        'oneirodex.platform.WEBRETR_INSTALLED_CORES',
        frozenset({'dosbox_pure'}),
    )
    monkeypatch.setattr(
        'oneirodex.platform.core_is_browser_playable',
        lambda c: c == 'dosbox_pure',
    )
    from oneirodex.platform import play_mode_for_platform as pm

    assert pm('PCDOS') == 'browser'

    monkeypatch.setattr('oneirodex.utils.play_url.pcdos_browser_enabled', lambda: True)
    monkeypatch.setattr(
        'oneirodex.utils.play_url.core_is_browser_playable',
        lambda c: c == 'dosbox_pure',
    )
    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['dosbox_pure'], 'preferred': 'dosbox_pure'},
    )
    library = SimpleNamespace(platform=SimpleNamespace(name='PCDOS'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is True
    assert fields['play_mode'] == 'browser'
    assert 'dosbox_pure' in fields['play_url']


def test_wave19b_pcdos_flag_on_but_no_wasm(monkeypatch):
    monkeypatch.setattr('oneirodex.utils.play_url.pcdos_browser_enabled', lambda: True)
    library = SimpleNamespace(platform=SimpleNamespace(name='PCDOS'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library, full_disk_path='fixture.rom')
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is False
    assert fields['play_blocker'] == 'pcdos_wasm_missing'


def test_wave19_cheat_surface_pc_vs_console():
    """GM lock: NATIVE_PC → pc_wand; mapped emu → retroarch; empty → none."""
    assert cheat_surface_for_platform('PCWIN') == 'pc_wand'
    assert cheat_surface_for_platform('PCDOS') == 'pc_wand'
    assert cheat_surface_for_platform('MAC') == 'pc_wand'
    assert cheat_surface_for_platform('OTHER') == 'pc_wand'
    assert cheat_surface_for_platform('NES') == 'retroarch'
    assert cheat_surface_for_platform('SNES') == 'retroarch'
    assert cheat_surface_for_platform('WII') == 'retroarch'
    assert cheat_surface_for_platform('PS5') == 'none'
    assert cheat_surface_for_platform('SWITCH') == 'none'
    assert cheat_surface_for_platform(None) == 'none'

    pc = browse_play_fields(
        SimpleNamespace(
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            full_disk_path='fixture.rom', library=SimpleNamespace(platform=SimpleNamespace(name='PCWIN')),
        )
    )
    assert pc['cheat_surface'] == 'pc_wand'

    nes = browse_play_fields(
        SimpleNamespace(
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            full_disk_path='fixture.rom', library=SimpleNamespace(platform=SimpleNamespace(name='NES')),
        )
    )
    assert nes['cheat_surface'] == 'retroarch'
