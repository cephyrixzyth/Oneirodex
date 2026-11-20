from enum import Enum as PyEnum

class LibraryPlatform(PyEnum):
    OTHER = "Other"
    PCWIN = "PC Windows"
    PCDOS = "PC DOS"
    MAC = "Mac"
    NES = "Nintendo Entertainment System (NES)"
    SNES = "Super Nintendo Entertainment System (SNES)"
    NGC = "Nintendo GameCube"
    N64 = "Nintendo 64"
    GB = "Nintendo GameBoy"
    GBA = "Nintendo GameBoy Advance"
    GBC = "Nintendo GameBoy Color"
    NDS = "Nintendo DS"
    VB = "Nintendo Virtual Boy"
    WII = "Nintendo Wii"
    N3DS = "Nintendo 3DS"
    SEGA_MD = "Sega Mega Drive/Genesis (MD)"
    SEGA_MS = "Sega Master System (MS)"
    SEGA_CD = "Sega CD"
    SEGA_32X = "Sega 32X"
    SEGA_GG = "Sega Game Gear (GG)"
    SEGA_SATURN = "Sega Saturn"
    SEGA_DC = "Sega Dreamcast"
    ATARI_7800 = "Atari 7800"
    ATARI_5200 = "Atari 5200"
    ATARI_2600 = "Atari 2600"
    LYNX = "Atari Lynx"
    JAGUAR = "Atari Jaguar"
    PCE = "PC Engine"
    PCFX = "PC-FX"
    NGP = "Neo Geo Pocket"
    WS = "WonderSwan"
    COLECO = "ColecoVision"
    THREEDO = "3DO"
    VECTREX = "Vectrex"
    VICE_X64SC = "Commodore 64"
    VICE_X128 = "Commodore 128"
    VICE_XVIC = "Commodore VIC-20"
    VICE_XPLUS4 = "Commodore Plus/4"
    VICE_XPET = "Commodore PET"
    XBOX = "Xbox"
    X360 = "Xbox 360"
    XONE = "Xbox One"
    XSX = "Xbox Series X"
    PSX = "Sony Playstation (PSX)"
    PS2 = "Sony PS2"
    PS3 = "Sony PS3"
    PS4 = "Sony PS4"
    PS5 = "Sony PS5"
    PSP = "Sony PSP"
    PSVITA = "Sony PS Vita"
    INTV = "Intellivision"
    CHAF = "Fairchild Channel F"
    O2EM = "Magnavox Odyssey 2"
    NEOGEO_CD = "Neo Geo CD"
    NEOGEO = "Neo Geo AES"
    SWITCH = "Nintendo Switch"
    ARCADE = "Arcade"
    # Console-gaming leaf systems present in real libraries but previously
    # unrepresentable — a folder of these had nowhere to land.
    AMIGA = "Commodore Amiga"
    SEGA_SG1000 = "Sega SG-1000"
    SUPERGRAFX = "PC Engine SuperGrafx"
    PCE_CD = "PC Engine CD / TurboGrafx-CD"
    NGPC = "Neo Geo Pocket Color"
    SUPERVISION = "Watara Supervision"
    GX4000 = "Amstrad GX4000"
    ASTROCADE = "Bally Astrocade"
    ARCADIA = "Emerson Arcadia 2001"
    CREATIVISION = "VTech CreatiVision"
    ADVISION = "Entex Adventure Vision"
    STUDIO2 = "RCA Studio II"
    ACTIONMAX = "WoW Action Max"
    DAPHNE = "Daphne (laserdisc)"
    PINBALL = "Pinball (Future Pinball / VP)"
    # Locked console wave (do not OTHER). Catalog/companion honesty only —
    # none of these ship a WebRetro WASM core in this build.
    WII_U = "Nintendo Wii U"
    POKE_MINI = "Pokémon Mini"
    GAME_WATCH = "Nintendo Game & Watch"
    CD_I = "Philips CD-i"
    SEGA_PICO = "Sega Pico"
    JAGUAR_CD = "Atari Jaguar CD"
    AMIGA_CD32 = "Commodore Amiga CD32"
    # Home-computer follow-on (ever-made report). Companion; no WebRetro WASM.
    MSX = "MSX"
    ZX_SPECTRUM = "ZX Spectrum"
    CPC = "Amstrad CPC"
    ATARI_ST = "Atari ST"
    APPLE_II = "Apple II"
    ATARI_8BIT = "Atari 8-bit"
    X68000 = "Sharp X68000"
    PC_98 = "NEC PC-98"
    BBC_MICRO = "BBC Micro"


class Emulator(PyEnum):
    """Libretro core IDs. Prefer good-standing cores that ship in WebRetro WASM."""

    DOSBOX = "dosbox"
    DOSBOX_PURE = "dosbox_pure"
    GENESIS_PLUS_GX = "genesis_plus_gx"
    YABAUSE = "yabause"
    STELLA = "stella"
    STELLA2014 = "stella2014"
    A5200 = "a5200"
    A2600 = "a2600"
    A7800 = "a7800"
    PROSYSTEM = "prosystem"
    VIRTUALJAGUAR = "virtualjaguar"
    HANDY = "handy"
    OPERA = "opera"
    MEDNAFEN_GBA = "mednafen_gba"
    NEOCD = "neocd"
    NESTOPIA = "nestopia"
    MUPEN64PLUS_NEXT = "mupen64plus_next"
    PARALLEL_N64 = "parallel_n64"
    MELODS = "melonds"
    DOLPHIN = "dolphin"
    MEDNAFEN_WSWAN = "mednafen_wswan"
    MEDNAFEN_NGP = "mednafen_ngp"
    MEDNAFEN_VB = "mednafen_vb"
    SNES9X = "snes9x"
    MEDNAFEN_PSX_HW = "mednafen_psx_hw"
    GEARCOLECO = "gearcoleco"
    VECX = "vecx"
    MGBA = "mgba"
    O2EM = "o2em"
    FREEINTV = "freeintv"
    FREECHAF = "freechaf"

    # Wave 19a — companion cores (browser only when WASM is in WEBRETR_INSTALLED_CORES)
    MEDNAFEN_PCE_FAST = "mednafen_pce_fast"
    MEDNAFEN_SUPERGRAFX = "mednafen_supergrafx"
    VICE_X64 = "vice_x64"

    # Wave 19d–e — native / RetroArch companion profiles (not in WebRetro WASM set)
    FLYCAST = "flycast"
    CITRA = "citra"
    PCSX2 = "pcsx2"
    VITA3K = "vita3k"

    # Console-gaming leaf cores. Companion/native unless listed in
    # WEBRETR_INSTALLED_CORES — browser play stays honest about what it can run.
    PUAE = "puae"                       # Commodore Amiga
    MEDNAFEN_PCE = "mednafen_pce"       # PC Engine incl. CD
    GEARSYSTEM = "gearsystem"           # Sega SG-1000 / MS / GG
    POTATOR = "potator"                 # Watara Supervision
    CAP32 = "cap32"                     # Amstrad CPC / GX4000
    FUSE = "fuse"                       # ZX Spectrum
    BLUEMSX = "bluemsx"                 # MSX
    HATARI = "hatari"                   # Atari ST
    ATARI800 = "atari800"               # Atari 8-bit (400/800/XL/XE) — not 5200 a5200
    PX68K = "px68k"                     # Sharp X68000
    NP2KAI = "np2kai"                   # NEC PC-98
    GW = "gw"                           # Nintendo Game & Watch — not in WebRetro WASM
    MAME2003_PLUS = "mame2003_plus"     # Astrocade / Arcadia / misc arcade
    CRVISION = "crvision"               # VTech CreatiVision
    DAPHNE = "daphne"                   # Laserdisc
    MAME = "mame"                       # Full MAME for the long tail

    # Legacy aliases kept for admin profiles that still store old enum-style values.
    SEGA_MD = "genesis_plus_gx"
    SEGA_MS = "genesis_plus_gx"
    SEGA_CD = "genesis_plus_gx"
    SEGA_32X = "genesis_plus_gx"
    SEGA_GG = "genesis_plus_gx"
    SEGA_SATURN = "yabause"
    LYNX = "handy"
    THREEDO = "opera"
    PSX = "mednafen_psx_hw"
    COLECO = "gearcoleco"
    VECTREX = "vecx"
    GB = "mgba"
    GBA = "mgba"
    GBC = "mgba"


# Cores provisioned under oneirodex/static/vendor/webretro/cores (WebRetro
# installedCores). These are no longer committed — they are fetched at first
# boot (FETCH_WEBRETRO_CORES_ON_BOOT) or by scripts/fetch-webretro-cores.sh,
# because their GPL / non-commercial terms make vendoring them the wrong call.
# The set is therefore "what a provisioned install runs", and boot warns when
# the fetch is off and they are absent — see utils/webretro_core_install.py.
WEBRETR_INSTALLED_CORES = frozenset({
    'a5200', 'freechaf', 'freeintv', 'gearcoleco', 'genesis_plus_gx', 'handy',
    'mednafen_ngp', 'mednafen_psx_hw', 'mednafen_vb', 'mednafen_wswan', 'melonds',
    'mgba', 'mupen64plus_next', 'neocd', 'nestopia', 'o2em', 'opera', 'parallel_n64',
    'prosystem', 'snes9x', 'stella2014', 'vecx', 'virtualjaguar', 'yabause',
})


platform_emulator_mapping = {
    LibraryPlatform.OTHER: [],
    LibraryPlatform.PCWIN: [],
    LibraryPlatform.MAC: [],
    # DOS cores are not in the current WebRetro WASM bundle — keep mapping for
    # native/companion profiles but they are gated out of browser play.
    LibraryPlatform.PCDOS: [Emulator.DOSBOX_PURE, Emulator.DOSBOX],
    LibraryPlatform.NES: [Emulator.NESTOPIA],
    LibraryPlatform.SNES: [Emulator.SNES9X],
    LibraryPlatform.N64: [Emulator.MUPEN64PLUS_NEXT, Emulator.PARALLEL_N64],
    LibraryPlatform.GB: [Emulator.MGBA],
    LibraryPlatform.GBA: [Emulator.MGBA],
    LibraryPlatform.GBC: [Emulator.MGBA],
    LibraryPlatform.NDS: [Emulator.MELODS],
    LibraryPlatform.VB: [Emulator.MEDNAFEN_VB],
    LibraryPlatform.PSX: [Emulator.MEDNAFEN_PSX_HW],
    LibraryPlatform.SEGA_MD: [Emulator.GENESIS_PLUS_GX],
    LibraryPlatform.SEGA_MS: [Emulator.GENESIS_PLUS_GX],
    LibraryPlatform.SEGA_CD: [Emulator.GENESIS_PLUS_GX],
    LibraryPlatform.SEGA_32X: [Emulator.GENESIS_PLUS_GX],
    LibraryPlatform.SEGA_GG: [Emulator.GENESIS_PLUS_GX],
    LibraryPlatform.SEGA_SATURN: [Emulator.YABAUSE],
    LibraryPlatform.ATARI_7800: [Emulator.PROSYSTEM],
    LibraryPlatform.ATARI_5200: [Emulator.A5200],
    LibraryPlatform.ATARI_2600: [Emulator.STELLA2014],
    LibraryPlatform.LYNX: [Emulator.HANDY],
    LibraryPlatform.JAGUAR: [Emulator.VIRTUALJAGUAR],
    LibraryPlatform.WS: [Emulator.MEDNAFEN_WSWAN],
    LibraryPlatform.NGP: [Emulator.MEDNAFEN_NGP],
    LibraryPlatform.COLECO: [Emulator.GEARCOLECO],
    LibraryPlatform.VECTREX: [Emulator.VECX],
    LibraryPlatform.THREEDO: [Emulator.OPERA],
    LibraryPlatform.NEOGEO_CD: [Emulator.NEOCD],
    LibraryPlatform.INTV: [Emulator.FREEINTV],
    LibraryPlatform.CHAF: [Emulator.FREECHAF],
    LibraryPlatform.O2EM: [Emulator.O2EM],
    # Wave 19a — companion mapped; browser gated by WEBRETR_INSTALLED_CORES (WASM not shipped yet)
    LibraryPlatform.PCE: [Emulator.MEDNAFEN_PCE_FAST, Emulator.MEDNAFEN_SUPERGRAFX],
    LibraryPlatform.PCFX: [],
    LibraryPlatform.VICE_X64SC: [Emulator.VICE_X64],
    LibraryPlatform.VICE_X128: [Emulator.VICE_X64],
    LibraryPlatform.VICE_XVIC: [Emulator.VICE_X64],
    LibraryPlatform.VICE_XPLUS4: [Emulator.VICE_X64],
    LibraryPlatform.VICE_XPET: [Emulator.VICE_X64],
    # Wave 19 — companion / catalog first (no WASM yet)
    LibraryPlatform.NGC: [Emulator.DOLPHIN],
    LibraryPlatform.WII: [Emulator.DOLPHIN],
    LibraryPlatform.SEGA_DC: [Emulator.FLYCAST],
    LibraryPlatform.N3DS: [Emulator.CITRA],
    LibraryPlatform.PS2: [Emulator.PCSX2],
    LibraryPlatform.PSVITA: [Emulator.VITA3K],
    LibraryPlatform.PS3: [],
    LibraryPlatform.PS4: [],
    LibraryPlatform.PS5: [],
    LibraryPlatform.PSP: [],  # companion BYO (PPSSPP) — no WebRetro core
    LibraryPlatform.XBOX: [],
    LibraryPlatform.X360: [],
    LibraryPlatform.XONE: [],
    LibraryPlatform.XSX: [],
    # LOCKED console leaf enums — catalog/companion honesty; never NEOCD for cart AES
    LibraryPlatform.NEOGEO: [],
    LibraryPlatform.SWITCH: [],
    LibraryPlatform.ARCADE: [],
    # Console-gaming leaf systems. Cores are companion/native — none of these
    # WASM builds ship in WebRetro yet, so browser play stays gated by
    # WEBRETR_INSTALLED_CORES rather than promising a session it cannot start.
    LibraryPlatform.AMIGA: [Emulator.PUAE],
    LibraryPlatform.SEGA_SG1000: [Emulator.GEARSYSTEM, Emulator.GENESIS_PLUS_GX],
    LibraryPlatform.SUPERGRAFX: [Emulator.MEDNAFEN_SUPERGRAFX],
    LibraryPlatform.PCE_CD: [Emulator.MEDNAFEN_PCE, Emulator.MEDNAFEN_PCE_FAST],
    LibraryPlatform.NGPC: [Emulator.MEDNAFEN_NGP],
    LibraryPlatform.SUPERVISION: [Emulator.POTATOR],
    LibraryPlatform.GX4000: [Emulator.CAP32],
    LibraryPlatform.ASTROCADE: [Emulator.MAME2003_PLUS, Emulator.MAME],
    LibraryPlatform.ARCADIA: [Emulator.MAME2003_PLUS, Emulator.MAME],
    LibraryPlatform.CREATIVISION: [Emulator.CRVISION, Emulator.MAME],
    LibraryPlatform.ADVISION: [Emulator.MAME],
    LibraryPlatform.STUDIO2: [Emulator.MAME],
    LibraryPlatform.ACTIONMAX: [],   # no emulation path — catalog only
    LibraryPlatform.DAPHNE: [Emulator.DAPHNE],
    LibraryPlatform.PINBALL: [],     # Future Pinball / VP are native Windows apps
    # Locked console wave — no WebRetro. Wii U is Cemu-class, not Dolphin.
    # Jaguar CD must not share the cart virtualjaguar core.
    LibraryPlatform.WII_U: [],
    LibraryPlatform.POKE_MINI: [],
    LibraryPlatform.GAME_WATCH: [Emulator.GW],
    LibraryPlatform.CD_I: [],
    LibraryPlatform.SEGA_PICO: [],
    LibraryPlatform.JAGUAR_CD: [],
    LibraryPlatform.AMIGA_CD32: [Emulator.PUAE],
    LibraryPlatform.MSX: [Emulator.BLUEMSX],
    LibraryPlatform.ZX_SPECTRUM: [Emulator.FUSE],
    LibraryPlatform.CPC: [Emulator.CAP32],
    LibraryPlatform.ATARI_ST: [Emulator.HATARI],
    LibraryPlatform.APPLE_II: [],  # AppleWin / linapple BYO — no libretro in this build
    LibraryPlatform.ATARI_8BIT: [Emulator.ATARI800],
    LibraryPlatform.X68000: [Emulator.PX68K],
    LibraryPlatform.PC_98: [Emulator.NP2KAI],
    LibraryPlatform.BBC_MICRO: [],  # BeebEm / b2 BYO — no libretro in this build
}


# Native PC / desktop family — cheat UI is pc_wand (not RetroArch .cht).
# PCDOS keeps DOSBox cores for play, but GM Wave 19 locks cheats to pc_wand.
NATIVE_PC_PLATFORMS = frozenset({'PCWIN', 'PCDOS', 'MAC', 'OTHER'})

# Catalog-only: no Play CTA (current-gen bar + Switch / Arcade / Neo Geo AES).
# ACTIONMAX has no emulation path at all (VHS-driven light gun); PINBALL titles
# are native Windows apps, not ROMs — both stay honest catalog entries.
CATALOG_ONLY_PLATFORMS = frozenset({
    'PS5', 'XSX',
    'SWITCH', 'ARCADE', 'NEOGEO',
    'ACTIONMAX', 'PINBALL',
    'WII_U',
})

# Prefer companion / native; browser cores not shipped (or not suitable).
COMPANION_PREFERRED_PLATFORMS = frozenset({
    'NGC', 'WII', 'PS2', 'PSVITA', 'SEGA_DC', 'N3DS', 'PCDOS',
    'PCE', 'PCFX', 'VICE_X64SC', 'VICE_X128', 'VICE_XVIC', 'VICE_XPLUS4', 'VICE_XPET',
    'PS3', 'PS4', 'PSP', 'XBOX', 'X360', 'XONE',
    'AMIGA', 'SEGA_SG1000', 'SUPERGRAFX', 'PCE_CD', 'NGPC', 'SUPERVISION',
    'GX4000', 'ASTROCADE', 'ARCADIA', 'CREATIVISION', 'ADVISION', 'STUDIO2',
    'DAPHNE',
    'POKE_MINI', 'GAME_WATCH', 'CD_I', 'SEGA_PICO', 'JAGUAR_CD', 'AMIGA_CD32',
    'MSX', 'ZX_SPECTRUM', 'CPC', 'ATARI_ST', 'APPLE_II',
    'ATARI_8BIT', 'X68000', 'PC_98', 'BBC_MICRO',
})

# Keys that currently have WebRetro WASM (mirrors play_url.WEBRETRO_PLATFORMS).
# PCE / VICE listed so browser unlocks automatically once their WASM is vendored.
# SG-1000 / NGPC share shipped cores (genesis_plus_gx / mednafen_ngp).
WEBRETRO_BROWSER_KEYS = frozenset({
    'NES', 'SNES', 'N64', 'GB', 'GBA', 'GBC', 'NDS', 'VB',
    'PSX', 'SEGA_MD', 'SEGA_MS', 'SEGA_CD', 'SEGA_32X', 'SEGA_GG',
    'SEGA_SATURN', 'ATARI_7800', 'ATARI_5200', 'ATARI_2600',
    'LYNX', 'JAGUAR', 'WS', 'NGP', 'COLECO', 'VECTREX',
    'THREEDO', 'NEOGEO_CD', 'INTV', 'CHAF', 'O2EM',
    'PCE', 'VICE_X64SC', 'VICE_X128', 'VICE_XVIC', 'VICE_XPLUS4', 'VICE_XPET',
    'SEGA_SG1000', 'NGPC',
})


def core_is_browser_playable(core_id: str | None) -> bool:
    if not core_id:
        return False
    from oneirodex.utils.webretro_cores import get_effective_installed_cores

    return str(core_id) in get_effective_installed_cores()


def mapped_core_ids(key: str | None) -> list[str]:
    if not key:
        return []
    try:
        plat = LibraryPlatform[key]
    except KeyError:
        return []
    cores: list[str] = []
    for emu in platform_emulator_mapping.get(plat, []) or []:
        cores.append(emu.value if hasattr(emu, 'value') else str(emu))
    return cores


def cheat_surface_for_platform(key: str | None) -> str:
    """UI cheat surface: retroarch | pc_wand | none.

    Wave 19 GM lock:
    - NATIVE_PC (PCWIN/PCDOS/MAC/OTHER) → pc_wand (hide RetroArch .cht until wand ships)
    - else if platform_emulator_mapping non-empty → retroarch
    - else → none
    """
    if not key:
        return 'none'
    if key in NATIVE_PC_PLATFORMS:
        return 'pc_wand'
    if mapped_core_ids(key):
        return 'retroarch'
    return 'none'


def pcdos_browser_enabled() -> bool:
    """Operator opt-in — DOS WASM is large; default stays companion-only."""
    try:
        from flask import current_app, has_app_context

        if not has_app_context():
            return False
        return bool(current_app.config.get('ENABLE_PCDOS_BROWSER'))
    except Exception:
        return False


# INSP-43 (v11 H4b): the arcade shelf *is* the platform -- there is no MAME
# enum. These cores are offered to the operator in Admin -> Emulators, but
# deliberately NOT through ``platform_emulator_mapping``: ARCADE is a locked,
# no-WASM platform, and anything reading that mapping may conclude a browser
# session is possible. Companion-only, chosen by hand, and until one is chosen
# the shelf stays catalogue. No ROMs, no dumps, no set files.
ARCADE_COMPANION_CORES = (Emulator.MAME2003_PLUS, Emulator.MAME)


def arcade_core_override_configured() -> bool:
    """True when the operator picked an arcade core in Admin -> Emulators.

    ARCADE ships catalog-only: MAME set handling is the operator's business
    and promising Play with no core chosen would be a lie. Choosing a core is
    the opt-in that turns the shelf into a companion-playable one.
    """
    try:
        from oneirodex.utils.emulator_profiles import get_emulator_profiles

        return bool((get_emulator_profiles() or {}).get('ARCADE'))
    except Exception:  # noqa: BLE001 -- a settings hiccup keeps the honest default
        return False


def play_mode_for_platform(key: str | None) -> str:
    """browser | companion | catalog | none

    Browser wins when a mapped core is in WEBRETR_INSTALLED_CORES (so PCE/C64 flip
    to browser once WASM is vendored). PCDOS additionally requires ENABLE_PCDOS_BROWSER.
    """
    if not key:
        return 'none'
    if key in CATALOG_ONLY_PLATFORMS:
        # INSP-43: the one platform whose lock an operator can lift, by
        # configuring a core. Everything else in the set stays catalog.
        if key == 'ARCADE' and arcade_core_override_configured():
            return 'companion'
        return 'catalog'
    mapped = mapped_core_ids(key)
    has_wasm = bool(mapped) and any(core_is_browser_playable(c) for c in mapped)
    if key == 'PCDOS':
        if pcdos_browser_enabled() and has_wasm:
            return 'browser'
        return 'companion'
    if has_wasm:
        return 'browser'
    if key in COMPANION_PREFERRED_PLATFORMS or key in ('PCWIN', 'MAC', 'OTHER'):
        return 'companion'
    if key in WEBRETRO_BROWSER_KEYS:
        return 'browser'
    return 'companion'


def platforms_for_play_mode(mode: str) -> list[LibraryPlatform]:
    """LibraryPlatform values whose honest play path matches ``mode``."""
    wanted = (mode or '').strip().lower()
    if wanted not in ('browser', 'companion', 'catalog'):
        return []
    return [plat for plat in LibraryPlatform if play_mode_for_platform(plat.name) == wanted]
