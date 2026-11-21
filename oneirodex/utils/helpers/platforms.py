"""LibraryPlatform name -> IGDB platforms.id map.

Bodies moved verbatim from ``oneirodex/utils/functions.py`` in wave A2.3.
"""

__all__ = ["PLATFORM_IDS", "PLATFORM_IDS_UNMAPPED", "igdb_platform_id_for"]


# IGDB platforms.id keyed by LibraryPlatform.name.
# Sources: IGDB platform dump (gist josefnpat) + tonkatsu-collections 220-id table.
# Identify and licensed-catalog refresh both read this map.
#
# Historical values kept (live identify already keyed to them — do not swap
# without a dedicated migration):
#   SEGA_MS 86 is IGDB TurboGrafx-16/PC Engine HuCard (canonical Master System is 64).
#   PCE 128 is IGDB SuperGrafx (canonical HuCard is 86). SUPERGRAFX is also 128.
#   NEOGEO 79 is IGDB Neo Geo MVS (canonical AES is 80).
PLATFORM_IDS = {
    "PCWIN": 6,
    "PCDOS": 13,
    "MAC": 14,
    "N64": 4,
    "GB": 33,
    "GBC": 22,
    "GBA": 24,
    "NDS": 20,
    "NES": 18,
    "SNES": 19,
    "NGC" : 21,
    "WII": 5,
    "N3DS": 37,
    "SWITCH": 130,
    "WII_U": 41,
    "XBOX": 11,
    "X360": 12,
    "XONE": 49,
    "XSX": 169,
    "PSX": 7,
    "PS2": 8,
    "PS3": 9,
    "PS4": 48,
    "PS5": 167,
    "PSP": 38,
    "PSVITA": 46,
    "VB": 87,
    "SEGA_MD": 29,
    "SEGA_MS": 86,
    "SEGA_CD": 78,
    "LYNX": 61,
    "SEGA_32X": 30,
    "JAGUAR": 62,
    "SEGA_GG": 35,
    "SEGA_SATURN": 32,
    "SEGA_DC": 23,
    "SEGA_SG1000": 84,
    "ATARI_7800": 60,
    "ATARI_5200": 66,
    "ATARI_2600": 59,
    "PCE": 128,
    "SUPERGRAFX": 128,
    "PCE_CD": 150,
    "PCFX": 274,
    "NGP": 119,
    "NGPC": 120,
    "NEOGEO_CD": 136,
    "NEOGEO": 79,
    "ARCADE": 52,
    "WS": 57,
    "COLECO": 68,
    "THREEDO": 50,
    "VECTREX": 70,
    "INTV": 67,
    "CHAF": 127,
    "O2EM": 133,
    "SUPERVISION": 415,
    "GX4000": 506,
    "ASTROCADE": 91,
    "ARCADIA": 473,
    "VICE_X64SC": 15,
    "VICE_X128": 15,
    "VICE_XVIC": 71,
    "VICE_XPLUS4": 94,
    "VICE_XPET": 90,
    "AMIGA": 16,
    "AMIGA_CD32": 114,
    "MSX": 27,
    "ZX_SPECTRUM": 26,
    "CPC": 25,
    "ATARI_ST": 63,
    "APPLE_II": 75,
    "ATARI_8BIT": 65,
    "X68000": 121,
    "PC_98": 149,
    "BBC_MICRO": 69,
    "POKE_MINI": 166,
    "CD_I": 117,
    "SEGA_PICO": 339,
    "JAGUAR_CD": 410,
    "GAME_WATCH": 307,
    "OTHER": None,
}

# Leaves with no confirmed IGDB platforms.id. Identify stays unfiltered;
# licensed-catalog refresh is refused. Do not invent ids for these.
PLATFORM_IDS_UNMAPPED = frozenset({
    "CREATIVISION",
    "ADVISION",
    "STUDIO2",
    "ACTIONMAX",
    "DAPHNE",
    "PINBALL",
    "OTHER",
})


def igdb_platform_id_for(platform) -> int | None:
    """IGDB platforms.id for a LibraryPlatform enum or enum name.

    Lookup is the enum *name* (``GBC``), never the display value
    (``Nintendo GameBoy Color``). Missing / OTHER / unmapped → None.
    """
    if platform is None:
        return None
    key = getattr(platform, "name", None) or str(platform).strip()
    if not key:
        return None
    value = PLATFORM_IDS.get(str(key).upper())
    return None if value is None else int(value)


# IGDB files many PC games under a sibling platform: old titles under DOS, VR
# titles under SteamVR / Oculus / Meta Quest / Windows Mixed Reality, ports under
# Linux or Mac. A PC library's ``platforms = (6)`` search never sees those, so a
# second, unfiltered pass keeps only candidates listed on one of these.
PC_FAMILY_LIBRARY_PLATFORMS = frozenset({'PCWIN', 'PCDOS'})
_PC_FAMILY_PLATFORM_MARKERS = (
    'pc (microsoft windows)', 'dos', 'linux', 'mac', 'steamvr', 'oculus',
    'meta quest', 'windows mixed reality', 'web browser',
)


def is_pc_family_library(platform) -> bool:
    key = getattr(platform, 'name', None) or str(platform or '').strip()
    return str(key).upper() in PC_FAMILY_LIBRARY_PLATFORMS


def candidate_on_pc_family(candidate) -> bool:
    """True when an IGDB candidate lists a PC-family platform (by name)."""
    for platform in (candidate or {}).get('platforms') or ():
        name = str((platform or {}).get('name') if isinstance(platform, dict) else platform).casefold()
        if any(marker == name or name.startswith(marker) for marker in _PC_FAMILY_PLATFORM_MARKERS):
            return True
    return False
