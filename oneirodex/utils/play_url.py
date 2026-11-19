"""WebRetro play URL helpers for browse tiles / details."""

from __future__ import annotations

from typing import Any

from oneirodex.platform import (
    cheat_surface_for_platform,
    core_is_browser_playable,
    mapped_core_ids,
    pcdos_browser_enabled,
    play_mode_for_platform,
)
from oneirodex.utils.browser_player import browser_play_href, play_engine_fields
from oneirodex.utils.emulator_bios import firmware_play_state
from oneirodex.utils.rom_archive import path_supports_browser_extract
from oneirodex.utils.webretro_cores import get_effective_installed_cores

# Platforms that WebRetro can launch when a bundled core is available.
WEBRETRO_PLATFORMS = frozenset({
    'NES', 'SNES', 'N64', 'GB', 'GBA', 'GBC', 'NDS', 'VB',
    'PSX', 'SEGA_MD', 'SEGA_MS', 'SEGA_CD', 'SEGA_32X', 'SEGA_GG',
    'SEGA_SATURN', 'ATARI_7800', 'ATARI_5200', 'ATARI_2600',
    'LYNX', 'JAGUAR', 'WS', 'NGP', 'COLECO', 'VECTREX',
    'THREEDO', 'NEOGEO_CD', 'INTV', 'CHAF', 'O2EM',
    'PCE', 'VICE_X64SC', 'VICE_X128', 'VICE_XVIC', 'VICE_XPLUS4', 'VICE_XPET',
    'SEGA_SG1000', 'NGPC',
    'PCDOS',
})

# Wave 19c+ — honest companion copy when no browser core ships.
COMPANION_HINTS = {
    'NGC': (
        'GameCube plays via the desktop companion or Dolphin / RetroArch (dolphin). '
        'No browser Play — WASM Dolphin is not shipped.'
    ),
    'WII': (
        'Wii plays via the desktop companion or Dolphin / RetroArch (dolphin). '
        'No browser Play — WASM Dolphin is not shipped.'
    ),
    'SEGA_DC': (
        'Dreamcast: use Flycast via desktop companion / RetroArch (flycast). '
        'Not browser-playable in this build.'
    ),
    'N3DS': (
        'Nintendo 3DS: use Citra-class / RetroArch companion (citra). '
        'Not browser-playable in this build.'
    ),
    'PS2': (
        'PS2: use PCSX2 or a RetroArch PCSX2 profile via the desktop companion. '
        'Not browser-playable.'
    ),
    'PSVITA': (
        'PS Vita: use Vita3K via the desktop companion when installed. '
        'Not browser-playable.'
    ),
    'PS3': (
        'PS3: catalog + optional BYO RPCS3 companion. No browser Play.'
    ),
    'PS4': (
        'PS4: catalog + optional BYO companion. No browser Play.'
    ),
    'XBOX': (
        'Original Xbox: catalog + optional BYO Xemu/Xenia-class companion. No browser Play.'
    ),
    'X360': (
        'Xbox 360: catalog + optional BYO Xenia companion. No browser Play.'
    ),
    'XONE': (
        'Xbox One: catalog + optional BYO companion. No browser Play.'
    ),
    'PSP': (
        'PSP: use PPSSPP or a RetroArch PPSSPP profile via the desktop companion. '
        'Not browser-playable.'
    ),
    'POKE_MINI': (
        'Pokémon Mini: use a RetroArch pokemini profile via the desktop companion. '
        'Not browser-playable.'
    ),
    'GAME_WATCH': (
        'Game & Watch: use a RetroArch gw profile via the desktop companion. '
        'Not browser-playable.'
    ),
    'CD_I': (
        'Philips CD-i: use a BYO / RetroArch companion. Not browser-playable.'
    ),
    'SEGA_PICO': (
        'Sega Pico: optional BYO companion. No browser Play.'
    ),
    'JAGUAR_CD': (
        'Jaguar CD is distinct from cart Jaguar. Use a companion CD path — '
        'virtualjaguar is the cart core. Not browser-playable.'
    ),
    'AMIGA_CD32': (
        'Amiga CD32: use PUAE / a CD32-capable companion. Not browser-playable.'
    ),
    'MSX': (
        'MSX: use blueMSX / fMSX via the desktop companion. Not browser-playable.'
    ),
    'ZX_SPECTRUM': (
        'ZX Spectrum: use Fuse via the desktop companion. Not browser-playable.'
    ),
    'CPC': (
        'Amstrad CPC: use Caprice32 (cap32) via the desktop companion. '
        'Not browser-playable. GX4000 is a separate console leaf.'
    ),
    'ATARI_ST': (
        'Atari ST: use Hatari via the desktop companion. Not browser-playable.'
    ),
    'APPLE_II': (
        'Apple II: use AppleWin / a BYO companion. Not browser-playable.'
    ),
    'ATARI_8BIT': (
        'Atari 8-bit: use atari800 via the desktop companion. '
        'Not the 5200 a5200 core. Not browser-playable.'
    ),
    'X68000': (
        'Sharp X68000: use PX68K / a BYO companion. Not browser-playable.'
    ),
    'PC_98': (
        'NEC PC-98: use Neko Project II (np2kai) via the desktop companion. '
        'Not browser-playable.'
    ),
    'BBC_MICRO': (
        'BBC Micro: use BeebEm / b2 via the desktop companion. '
        'Not browser-playable.'
    ),
}

COMPANION_PREFERRED_BLOCKERS = frozenset({
    'NGC', 'WII', 'SEGA_DC', 'N3DS', 'PS2', 'PSVITA',
})

# Honest operator path — never ship copyrighted BIOS binaries in-repo/image.
BIOS_UPLOAD_HINT = (
    'Upload legally obtained firmware via Admin → emulator BIOS (POST /api/emulator-bios), '
    'or mount a private host BIOS directory and set EMULATOR_BIOS_PATH '
    '(see bios_root() / Compose volume). '
    'Oneirodex does not ship copyrighted BIOS files.'
)


def companion_hint_for(key: str | None, cores: list[str] | None = None) -> str | None:
    if not key:
        return None
    if key in COMPANION_HINTS:
        return COMPANION_HINTS[key]
    if cores:
        return 'Use the desktop companion / RetroArch with: ' + ', '.join(cores)
    return None


def library_platform_key(game) -> str | None:
    library = getattr(game, 'library', None)
    platform = getattr(library, 'platform', None) if library is not None else None
    if platform is None:
        return None
    name = getattr(platform, 'name', None)
    if name:
        return str(name)
    return str(platform)


def browse_play_fields(game) -> dict[str, Any]:
    """Fields for GameCard play / demo links."""
    key = library_platform_key(game)
    surface = cheat_surface_for_platform(key)
    engines = play_engine_fields()

    def finish(payload: dict[str, Any]) -> dict[str, Any]:
        from oneirodex.utils.play_readiness import browser_readiness
        payload['browser_readiness'] = browser_readiness(payload)
        payload['cheat_surface'] = surface
        payload.update(engines)
        href = payload.get('play_url') or ''
        for engine in ('webretro', 'emulatorjs', 'nostalgist'):
            if href.startswith(f'/static/vendor/{engine}/'):
                payload['browser_player'] = engine
                break
        # FEAT-D5: per-system room treatment so the play surface can dress
        # itself for the era. Data only — the caller decides scope.
        try:
            from oneirodex.utils.play_rooms import room_for_platform

            payload['play_room'] = room_for_platform(key)
        except Exception:  # noqa: BLE001 — cosmetics never block play
            payload['play_room'] = None
        return payload

    mode = play_mode_for_platform(key)
    if not key:
        return finish({
            'play_url': None,
            'can_play_in_browser': False,
            'emulator_cores': [],
            'play_mode': 'none',
        })
    if mode == 'catalog':
        return finish({
            'play_url': None,
            'can_play_in_browser': False,
            'emulator_cores': [],
            'library_platform': key,
            'play_mode': 'catalog',
            'play_blocker': 'catalog_only',
        })

    # Suppress Play when on-disk path cannot be extracted for WebRetro (e.g. .tar.gz).
    disk_path = getattr(game, 'full_disk_path', None)
    if key in WEBRETRO_PLATFORMS and not str(disk_path or '').strip():
        return finish({
            'play_url': None, 'can_play_in_browser': False, 'emulator_cores': [],
            'library_platform': key, 'play_mode': 'catalog', 'play_blocker': 'missing_game_file',
            'companion_hint': 'No game file is attached to this library entry.',
        })
    if disk_path and not path_supports_browser_extract(disk_path):
        return finish({
            'play_url': None,
            'can_play_in_browser': False,
            'emulator_cores': [],
            'library_platform': key,
            'play_mode': mode if mode != 'browser' else 'companion',
            'play_blocker': 'unsupported_archive',
            'companion_hint': (
                'This file type cannot be extracted for browser play '
                '(use .zip / .7z / .rar / ROM.gz or a raw ROM).'
            ),
        })

    # Wave 19b — PC DOS: companion by default; browser only with flag + vendored WASM.
    if key == 'PCDOS':
        companion = mapped_core_ids(key)
        flag_on = pcdos_browser_enabled()
        wasm_ready = any(core_is_browser_playable(c) for c in companion)
        if not (flag_on and wasm_ready):
            blocker = 'pcdos_flag_off' if not flag_on else 'pcdos_wasm_missing'
            return finish({
                'play_url': None,
                'can_play_in_browser': False,
                'emulator_cores': [],
                'companion_cores': companion,
                'library_platform': key,
                'play_mode': 'companion',
                'play_blocker': blocker,
                'companion_hint': (
                    'PC DOS plays via desktop companion / RetroArch (dosbox_pure). '
                    'Browser play needs ENABLE_PCDOS_BROWSER=true and a vendored dosbox WASM core.'
                ),
            })

    if key not in WEBRETRO_PLATFORMS:
        companion = mapped_core_ids(key)
        if key == 'ARCADE' and mode == 'companion':
            from oneirodex.utils.emulator_profiles import resolve_emulators_for_platform

            companion = resolve_emulators_for_platform(key)['emulators']
        blocker = (
            'companion_preferred'
            if key in COMPANION_PREFERRED_BLOCKERS
            else 'companion_or_catalog'
        )
        return finish({
            'play_url': None,
            'can_play_in_browser': False,
            'emulator_cores': [],
            'companion_cores': companion,
            'library_platform': key,
            'play_mode': mode,
            'play_blocker': blocker,
            'companion_hint': companion_hint_for(key, companion),
        })
    if engines['browser_player'] == 'emulatorjs' and not (key == 'NES' and engines.get('nostalgist_nes_pilot')):
        from oneirodex.utils.emulatorjs import emulatorjs_core_for_platform, emulatorjs_play_href

        core = emulatorjs_core_for_platform(key)
        if core:
            return finish({
                'play_url': emulatorjs_play_href(game_uuid=str(game.uuid), platform_key=key, cheat_surface=surface),
                'can_play_in_browser': True, 'emulator_core': core, 'emulator_cores': [core],
                'library_platform': key, 'play_mode': 'browser', 'bios': None,
                'bios_required': False, 'firmware_missing': False,
            })
    try:
        from oneirodex.utils.emulator_profiles import resolve_emulators_for_platform

        resolved = resolve_emulators_for_platform(key)
        cores = [
            core
            for core in (resolved.get('emulators') or [])
            if core_is_browser_playable(core)
        ]
        preferred = resolved.get('preferred')
        if preferred and core_is_browser_playable(preferred) and preferred in cores:
            cores = [preferred] + [c for c in cores if c != preferred]
    except Exception:
        cores = []
        preferred = None

    if not cores:
        companion = mapped_core_ids(key)
        return finish({
            'play_url': None,
            'can_play_in_browser': False,
            'emulator_cores': [],
            'companion_cores': companion,
            'library_platform': key,
            'play_mode': mode if mode != 'browser' else 'companion',
            'play_blocker': 'no_browser_core',
            'companion_hint': companion_hint_for(key, companion),
        })

    core = cores[0]
    state = firmware_play_state(key, core)
    bios_required = bool(state['bios_required'])
    firmware_missing = bool(state['firmware_missing'])
    bios_hint = None
    if bios_required:
        # Only loadable (firmware-root) files count as present — a nested
        # dump is on disk and still will not boot.
        if firmware_missing:
            bios_hint = {
                'core': core,
                'ready': False,
                'missing': list(state['required']),
                'bios_required': True,
                'firmware_missing': True,
                'message': (
                    f'{core} needs BIOS under Admin → emulator BIOS '
                    f'(missing: {", ".join(state["required"])})'
                ),
                'hint': BIOS_UPLOAD_HINT,
            }
        else:
            bios_hint = {
                'core': core,
                'ready': True,
                'present': list(state['present']),
                'missing': list(state['missing']),
                'bios_required': True,
                'firmware_missing': False,
                'message': None,
                'hint': None,
            }

    n64_note = None
    if key == 'N64':
        n64_note = 'N64 WebRetro cores can be flaky on some titles — try the other core in Emulator profiles if play fails.'

    # Engine id on the payload comes from play_engine_fields() in finish().
    # NES may launch the Nostalgist host when nostalgist_nes_pilot is on (BP-1).
    return finish({
        'play_url': browser_play_href(
            game_uuid=str(game.uuid),
            core=core,
            platform_key=key,
        ),
        'can_play_in_browser': True,
        'emulator_cores': cores,
        'emulator_core': core,
        'library_platform': key,
        'webretro_installed_cores': sorted(get_effective_installed_cores()),
        'bios': bios_hint,
        'bios_required': bios_required,
        'firmware_missing': firmware_missing,
        'n64_note': n64_note,
        'play_mode': 'browser',
    })
