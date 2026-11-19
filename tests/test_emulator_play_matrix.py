"""Play-mode honesty for every LibraryPlatform — not just NES and Game Boy.

No DB. browse_play_fields is exercised with emulator-profile lookup stubbed so
the matrix does not depend on GlobalSettings.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from oneirodex.platform import (
    CATALOG_ONLY_PLATFORMS,
    COMPANION_PREFERRED_PLATFORMS,
    LibraryPlatform,
    WEBRETRO_BROWSER_KEYS,
    WEBRETR_INSTALLED_CORES,
    mapped_core_ids,
    play_mode_for_platform,
)
from oneirodex.utils.play_url import WEBRETRO_PLATFORMS, browse_play_fields

ROOT = Path(__file__).resolve().parents[1]
WEBRETRO = ROOT / 'oneirodex' / 'static' / 'vendor' / 'webretro'
FREE_ROMS = ROOT / 'samples' / 'free-roms' / 'manifest.yaml'

PLAY_MODES = frozenset({'browser', 'companion', 'catalog', 'none'})

# Cores that stutter if rewind keeps a frame buffer on single-thread WASM.
HEAVY_REWIND_CORES = frozenset({
    'mupen64plus_next',
    'parallel_n64',
    'mednafen_psx_hw',
    'mednafen_psx',
    'pcsx_rearmed',
    'yabause',
    'yabasanshiro',
    'flycast',
    'ppsspp',
})


def _game(platform: str) -> SimpleNamespace:
    return SimpleNamespace(
        uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        full_disk_path='fixture.rom', library=SimpleNamespace(platform=SimpleNamespace(name=platform)),
    )


def _stub_profiles(monkeypatch) -> None:
    def resolve(platform_name: str) -> dict:
        cores = mapped_core_ids(platform_name)
        return {
            'emulators': cores,
            'preferred': cores[0] if cores else None,
        }

    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        resolve,
    )
    monkeypatch.setattr(
        'oneirodex.utils.emulator_bios.list_bios_files',
        lambda: [],
    )


def test_every_library_platform_has_a_play_mode():
    missing = []
    for plat in LibraryPlatform:
        mode = play_mode_for_platform(plat.name)
        if mode not in PLAY_MODES:
            missing.append((plat.name, mode))
    assert missing == []


def test_catalog_only_never_offers_browser_play(monkeypatch):
    _stub_profiles(monkeypatch)
    for key in sorted(CATALOG_ONLY_PLATFORMS):
        assert play_mode_for_platform(key) == 'catalog', key
        fields = browse_play_fields(_game(key))
        assert fields['can_play_in_browser'] is False, key
        assert fields['play_mode'] == 'catalog', key
        assert fields['play_url'] is None, key
        assert fields.get('play_blocker') == 'catalog_only', key


def test_installed_webretro_cores_browser_play(monkeypatch):
    """Every shipped WASM core that maps to a platform can start a session."""
    _stub_profiles(monkeypatch)
    browser_keys = []
    for plat in LibraryPlatform:
        key = plat.name
        if play_mode_for_platform(key) != 'browser':
            continue
        fields = browse_play_fields(_game(key))
        browser_keys.append(key)
        assert fields['play_mode'] == 'browser', key
        assert fields['can_play_in_browser'] is True, (
            f'{key} is browser but can_play_in_browser={fields["can_play_in_browser"]}'
            f' blocker={fields.get("play_blocker")}'
        )
        assert fields['play_url'], key
        assert 'webretro.html' in fields['play_url'], key
        cores = fields.get('emulator_cores') or []
        assert cores, key
        assert any(c in WEBRETR_INSTALLED_CORES for c in cores), (key, cores)
    # Sanity: not only NES / GB.
    assert 'NES' in browser_keys
    assert 'SNES' in browser_keys
    assert 'SEGA_MD' in browser_keys
    assert 'SEGA_SG1000' in browser_keys
    assert 'ATARI_2600' in browser_keys
    assert 'PSX' in browser_keys
    assert 'N64' in browser_keys
    assert 'WS' in browser_keys
    assert 'NGPC' in browser_keys
    assert 'COLECO' in browser_keys
    assert len(browser_keys) >= 20


def test_browser_play_mode_keys_are_in_webretro_platforms():
    """play_mode==browser must be a key browse can actually launch."""
    drift = [
        plat.name
        for plat in LibraryPlatform
        if play_mode_for_platform(plat.name) == 'browser'
        and plat.name not in WEBRETRO_PLATFORMS
    ]
    assert drift == []


def test_companion_preferred_without_wasm_never_fakes_play(monkeypatch):
    _stub_profiles(monkeypatch)
    for key in sorted(COMPANION_PREFERRED_PLATFORMS):
        if play_mode_for_platform(key) == 'browser':
            # WASM on disk flips PCE / C64 / SG-1000 / NGPC automatically.
            continue
        fields = browse_play_fields(_game(key))
        assert fields['can_play_in_browser'] is False, key
        assert fields['play_url'] is None, key
        assert fields['play_mode'] in ('companion', 'catalog'), key


def test_webretro_key_sets_stay_aligned():
    """play_url and platform.py must agree on which keys can take a WASM core."""
    from_url = set(WEBRETRO_PLATFORMS) - {'PCDOS'}
    from_plat = set(WEBRETRO_BROWSER_KEYS)
    assert from_url == from_plat, sorted(from_url.symmetric_difference(from_plat))


def test_every_installed_core_has_a_play_skin_mapping():
    src = (WEBRETRO / 'play-skins.js').read_text(encoding='utf-8')
    core_map = dict(re.findall(r"^\s{4}([a-z0-9_]+):\s*'([A-Z0-9_]+)',", src, re.M))
    missing = sorted(c for c in WEBRETR_INSTALLED_CORES if c not in core_map)
    assert missing == [], f'play-skins CORE_TO_PLATFORM missing {missing}'


def test_every_platform_has_a_play_skin_label_and_css():
    src = (WEBRETRO / 'play-skins.js').read_text(encoding='utf-8')
    css = (WEBRETRO / 'play-skins.css').read_text(encoding='utf-8')
    labels = dict(re.findall(r"^\s{4}([A-Z0-9_]+):\s*'([^']*)',", src, re.M))
    missing_label = []
    missing_css = []
    for plat in LibraryPlatform:
        key = plat.name
        if key not in labels:
            missing_label.append(key)
        token = f'[data-platform="{key}"]'
        if token not in css:
            missing_css.append(key)
    assert missing_label == [], missing_label
    assert missing_css == [], missing_css


def test_heavy_rewind_cores_are_disabled_in_the_bridge():
    bridge = (WEBRETRO / 'od-bridge.js').read_text(encoding='utf-8')
    assert 'rewindOkForCore' in bridge
    assert 'HEAVY_REWIND_CORES' in bridge
    for core in HEAVY_REWIND_CORES:
        assert f'{core}:' in bridge or f'{core}: 1' in bridge, core


def test_audio_clock_pins_wasm_skew_not_desktop_default():
    """0.15 is deliberate for WASM jitter. Do not "correct" it back to 0.05."""
    base = (WEBRETRO / 'assets' / 'base.js').read_text(encoding='utf-8')
    assert 'audio_max_timing_skew = "0.15"' in base
    assert 'audio_sync = "true"' in base
    assert 'audio_rate_control = "true"' in base
    assert 'video_vsync = "true"' in base
    assert 'measureRefreshHz' in base or 'measuredRefreshHz' in base
    # A sample that finishes during boot must still reach retroarch.cfg:
    # afterStart applies once mainCompleted is true, and the first write waits.
    after_idx = base.index('function afterStart')
    after_chunk = base[after_idx:after_idx + 900]
    assert 'mainCompleted = true' in after_chunk
    assert 'tryApplyConfig()' in after_chunk
    assert 'waitForMeasuredRefresh' in base
    assert 'refreshRateWritten' in base


def test_free_rom_manifest_platforms_are_real():
    text = FREE_ROMS.read_text(encoding='utf-8')
    valid = {p.name.lower() for p in LibraryPlatform}
    folder_aliases = {
        'genesis': 'sega_md',
        'atari2600': 'atari_2600',
    }
    platforms = re.findall(r'^\s+platform:\s+(\S+)', text, re.M)
    unknown = sorted({
        p for p in platforms
        if folder_aliases.get(p.lower(), p.lower()) not in valid
    })
    assert unknown == [], unknown
    asserted = {
        folder_aliases.get(p.lower(), p.lower())
        for p in platforms
        if folder_aliases.get(p.lower(), p.lower()) in valid
    }
    # Sanity: more than the original NES + GB pair.
    assert 'nes' in asserted
    assert 'gb' in asserted
    assert 'snes' in asserted
    assert len(asserted) >= 6


def test_catalog_entry_without_rom_has_no_browser_launch():
    game = _game('NES')
    game.full_disk_path = None
    game.demo_url = 'https://example.invalid/demo'
    fields = browse_play_fields(game)
    assert not fields['can_play_in_browser'] and fields['play_url'] is None
    assert fields['play_blocker'] == 'missing_game_file'
    assert game.demo_url.endswith('/demo')
