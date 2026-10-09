"""EmulatorJS — browser play engine B (BP-2).

WebRetro (engine A) and EmulatorJS are two different shells over libretro
cores. EmulatorJS ships its own UI, its own core packaging (``data/cores/``,
fetched per system on first use) and a strong touch / gamepad story, which is
why the engine evaluation kept it as the second stack rather than a third
launcher over the same WASM.

The pinned release is bundled in the image under
``static/vendor/emulatorjs/data``. This module reports whether the bundle is
present, and the engine is offered only when it is. Same honesty shape as the
WebRetro cores directory: a missing loader means "not installed", never a
broken Play button.

ROMs never leave the box. The play shell hands EmulatorJS the same
``/api/downloadrom/<guid>`` URL the WebRetro room uses; cores and the loader
come from this origin.
"""

from __future__ import annotations

from pathlib import Path

from oneirodex.platform import LibraryPlatform

ENGINE_ID = 'emulatorjs'

#: Relative to ``oneirodex/static``; the Docker image bundle lands here.
DATA_DIR_RELATIVE = Path('vendor') / 'emulatorjs' / 'data'

#: The one file every EmulatorJS release has at its data root. Its presence is
#: the install signal; cores under ``data/cores/`` are fetched lazily by the
#: loader itself.
LOADER_FILENAME = 'loader.js'

#: Play shell, in the image (not the bind), so a deploy always updates it.
PLAY_SHELL_PATH = '/static/vendor/emulatorjs/play.html'

# LibraryPlatform -> EmulatorJS ``EJS_core`` system alias. Only systems whose
# EmulatorJS core is known to boot a plain dump without an operator-uploaded
# BIOS are listed; anything absent stays on WebRetro / Companion / Catalog
# exactly as today. Aliases are the documented EJS_core values (the loader
# resolves them to its bundled libretro build). Extend one row at a time,
# after a real ROM has been seen to run.
EJS_CORE_BY_PLATFORM: dict[str, str] = {
    'NES': 'nes',
    'SNES': 'snes',
    'GB': 'gb',
    'GBC': 'gb',
    'GBA': 'gba',
    'NDS': 'nds',
    'VB': 'vb',
    'N64': 'n64',
    'SEGA_MD': 'segaMD',
    'SEGA_MS': 'segaMS',
    'SEGA_GG': 'segaGG',
    'SEGA_32X': 'sega32x',
    'ATARI_2600': 'atari2600',
    'ATARI_5200': 'atari5200',
    'ATARI_7800': 'atari7800',
    'LYNX': 'lynx',
    'JAGUAR': 'jaguar',
    'PCE': 'pce',
    'NGP': 'ngp',
    'NGPC': 'ngp',
    'WS': 'ws',
    'COLECO': 'coleco',
}


def default_data_dir() -> Path:
    here = Path(__file__).resolve().parent.parent  # oneirodex/
    return here / 'static' / DATA_DIR_RELATIVE


def emulatorjs_installed(data_dir: str | Path | None = None) -> bool:
    """True when an EmulatorJS release is present at the data root."""
    root = Path(data_dir) if data_dir else default_data_dir()
    try:
        return (root / LOADER_FILENAME).is_file()
    except OSError:
        return False


def emulatorjs_core_for_platform(platform_key: str | LibraryPlatform | None) -> str | None:
    """The ``EJS_core`` alias for a library platform, or None when unsupported."""
    if platform_key is None:
        return None
    key = getattr(platform_key, 'name', None) or str(platform_key)
    return EJS_CORE_BY_PLATFORM.get(key.strip().upper())


def emulatorjs_supported_platforms() -> frozenset[str]:
    return frozenset(EJS_CORE_BY_PLATFORM)


def emulatorjs_play_href(*, game_uuid: str, platform_key: str, cheat_surface: str | None = None) -> str:
    """Play shell URL for a guid on a supported platform (caller checks support)."""
    core = emulatorjs_core_for_platform(platform_key)
    if not core:
        return ''
    params = [f'guid={game_uuid}', f'core={core}', f'platform={str(platform_key).upper()}']
    if cheat_surface:
        params.append(f'cheat_surface={cheat_surface}')
    return f'{PLAY_SHELL_PATH}?' + '&'.join(params)
