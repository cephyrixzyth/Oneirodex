"""How recent each platform's hardware is, for ranking copies of one title.

The library shows one tile per row, so a household that keeps a game on three
systems sees three unrelated tiles. Collapsing them to one tile means choosing
*which* copy represents the title, and the answer asked for is "the latest
system it was released on" — hardware recency, not when the file was scanned.

`LibraryPlatform` cannot answer that. It is an arbitrary declaration order that
has been appended to over time: `SWITCH` and `ARCADE` sit after `O2EM`, and
`AMIGA` after `ARCADE`. Nothing in it encodes generation, so this table does.

The value is the platform's **launch year**, which is the ordering people mean
by "newer console". It is a ranking key, not a fact anyone reads, so precision
past the year is pointless — but the years are real, so the ordering can be
checked against the world rather than argued about.

Judgement calls worth naming, because they are the ones a reviewer will query:

* **PC (`PCWIN`, `MAC`) sorts above every console.** A PC release is the one
  that is still current, still patched, and almost always the copy someone
  means to launch. Ranking it by the year Windows shipped would bury it under a
  Dreamcast. `PCDOS` keeps its real era, because a DOS build genuinely is the
  old copy.
* **`ARCADE` and `DAPHNE` sort low.** An arcade board is the *original* release
  of anything that also exists on a console, which is what the rank is asked to
  express. `PINBALL` sits with them.
* **`OTHER` sorts lowest of all.** An unclassified library must never win the
  representative slot over a system that was actually identified.

Add a platform here whenever one is added to `LibraryPlatform`;
`tests/test_platform_recency.py` fails until you do, so the table cannot fall
silently out of step and start ranking new systems as if they were the oldest.
"""

from __future__ import annotations

from oneirodex.platform import LibraryPlatform

#: Sorts above every console — see the module docstring.
_PC_RANK = 3000

#: Sorts below every console that was actually identified.
_UNKNOWN_RANK = 0

PLATFORM_LAUNCH_YEAR: dict[str, int] = {
    # Desktop — deliberately not ordered by year. See the docstring.
    'PCWIN': _PC_RANK,
    'MAC': _PC_RANK,
    'PCDOS': 1981,

    # Nintendo
    'NES': 1983,
    'GB': 1989,
    'SNES': 1990,
    'VB': 1995,
    'N64': 1996,
    'GBC': 1998,
    'GBA': 2001,
    'NGC': 2001,
    'NDS': 2004,
    'WII': 2006,
    'N3DS': 2011,
    'WII_U': 2012,
    'SWITCH': 2017,

    # Sega
    'SEGA_SG1000': 1983,
    'SEGA_MS': 1985,
    'SEGA_MD': 1988,
    'SEGA_GG': 1990,
    'SEGA_CD': 1991,
    'SEGA_32X': 1994,
    'SEGA_SATURN': 1994,
    'SEGA_DC': 1998,
    'SEGA_PICO': 1993,

    # Sony
    'PSX': 1994,
    'PS2': 2000,
    'PSP': 2004,
    'PS3': 2006,
    'PSVITA': 2011,
    'PS4': 2013,
    'PS5': 2020,

    # Microsoft
    'XBOX': 2001,
    'X360': 2005,
    'XONE': 2013,
    'XSX': 2020,

    # Atari
    'ATARI_2600': 1977,
    'ATARI_5200': 1982,
    'ATARI_7800': 1986,
    'LYNX': 1989,
    'JAGUAR': 1993,
    'JAGUAR_CD': 1995,

    # NEC / Hudson
    'PCE': 1987,
    'PCE_CD': 1988,
    'SUPERGRAFX': 1989,
    'PCFX': 1994,

    # SNK
    'NEOGEO': 1990,
    'NEOGEO_CD': 1994,
    'NGP': 1998,
    'NGPC': 1999,

    # Bandai
    'WS': 1999,

    # Commodore / Amstrad
    'VICE_XPET': 1977,
    'VICE_XVIC': 1980,
    'VICE_X64SC': 1982,
    'VICE_XPLUS4': 1984,
    'AMIGA': 1985,
    'AMIGA_CD32': 1993,
    'APPLE_II': 1977,
    'ATARI_8BIT': 1979,
    'ZX_SPECTRUM': 1982,
    'MSX': 1983,
    'CPC': 1984,
    'ATARI_ST': 1985,
    'PC_98': 1982,
    'BBC_MICRO': 1981,
    'X68000': 1987,
    'VICE_X128': 1985,
    'GX4000': 1990,

    # Other consoles and curios
    'CHAF': 1976,
    'STUDIO2': 1977,
    'O2EM': 1978,
    'INTV': 1979,
    'ASTROCADE': 1978,
    'ARCADIA': 1982,
    'COLECO': 1982,
    'VECTREX': 1982,
    'CREATIVISION': 1982,
    'ADVISION': 1982,
    'SUPERVISION': 1992,
    'THREEDO': 1993,
    'CD_I': 1991,
    'POKE_MINI': 2001,
    'GAME_WATCH': 1980,
    'ACTIONMAX': 1987,

    # Originals rather than ports — see the docstring.
    'ARCADE': 1971,
    'DAPHNE': 1983,
    'PINBALL': 1947,

    'OTHER': _UNKNOWN_RANK,
}


def platform_rank(platform_key: str | None) -> int:
    """Ranking key for one platform; higher is newer.

    Unknown keys rank lowest rather than raising: a library created against a
    platform this table has not caught up with must not take the representative
    slot away from a system that *is* known, and must not break browse.
    """
    if not platform_key:
        return _UNKNOWN_RANK
    return PLATFORM_LAUNCH_YEAR.get(str(platform_key), _UNKNOWN_RANK)


