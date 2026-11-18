"""Built-in released-set size estimates when DAT / IGDB cache are empty.

Keys are ``LibraryPlatform`` enum *names* (``NES``, ``SNES``), matching
``ReferenceSet.library_platform`` and ``IgdbPlatformRelease.library_platform``.

These are No-Intro / Redump–style ballpark USA (or World) set sizes so the
Libraries game-count heat can color before an operator uploads a DAT or
refreshes the licensed catalog. Real DAT ``entry_count`` and IGDB unique
titles always win over these estimates.
"""

from __future__ import annotations

# Approximate unique titles in a typical complete USA/World set.
PLATFORM_RELEASE_ESTIMATES: dict[str, int] = {
    'NES': 716,
    'SNES': 721,
    'GB': 1024,
    'GBC': 576,
    'GBA': 1543,
    'N64': 388,
    'NDS': 2800,
    'NGC': 651,
    'WII': 1400,
    'WII_U': 790,
    'N3DS': 1500,
    'SWITCH': 4500,
    'VB': 22,
    'SEGA_MD': 914,
    'SEGA_MS': 320,
    'SEGA_GG': 365,
    'SEGA_CD': 210,
    'SEGA_32X': 40,
    'SEGA_SATURN': 1100,
    'SEGA_DC': 650,
    'SEGA_SG1000': 70,
    'ATARI_2600': 510,
    'ATARI_5200': 96,
    'ATARI_7800': 59,
    'LYNX': 80,
    'JAGUAR': 50,
    'JAGUAR_CD': 13,
    'PCE': 300,
    'PCE_CD': 450,
    'SUPERGRAFX': 7,
    'PCFX': 62,
    'NGP': 76,
    'NGPC': 80,
    'NEOGEO': 148,
    'NEOGEO_CD': 100,
    'WS': 110,
    'COLECO': 140,
    'THREEDO': 250,
    'VECTREX': 40,
    'INTV': 125,
    'CHAF': 50,
    'O2EM': 50,
    'SUPERVISION': 70,
    'GX4000': 35,
    'ASTROCADE': 40,
    'ARCADIA': 30,
    'AMIGA': 3000,
    'AMIGA_CD32': 150,
    'MSX': 2000,
    'ZX_SPECTRUM': 4000,
    'CPC': 2000,
    'ATARI_ST': 2000,
    'APPLE_II': 1500,
    'ATARI_8BIT': 1000,
    'X68000': 500,
    'PC_98': 2000,
    'PSX': 2500,
    'PS2': 4000,
    'PS3': 2500,
    'PSP': 1800,
    'PSVITA': 1400,
    'XBOX': 1000,
    'X360': 2100,
    'ARCADE': 5000,
}


