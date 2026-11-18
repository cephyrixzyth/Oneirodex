"""Per-system "room" treatment for the play surface (FEAT-D5).

The existing platform skins group by **brand** (Nintendo / Sony / Sega / …),
which is the right axis for library chrome. Play is a different question: what
did playing this thing actually feel like, and where were you sitting?

Two layers, on purpose:

* **Bezel** (CSS per ``data-platform``) is the *hardware* — the slab, tube, or
  handheld shell you were holding or staring at.
* **Room** (this map) is the *place and decade* — a 1990s teen bedroom for a
  SNES or a Game Boy, a wood-panel den for an NES, an arcade floor for a
  cabinet. Handhelds still get a plastic bezel; they sit in the era room, not
  in a generic daylight void.

Rooms group by **setting**, not brand: a Mega Drive and a SNES shared a
bedroom; a Neo Geo cabinet did not.

A room is data: palette + ambience + which era font to pair. Nothing here
imitates a manufacturer's trade dress; it is period *setting*, not branding.
"""

from __future__ import annotations

from oneirodex.utils.theme_fonts import font_for_platform

ROOMS: dict[str, dict] = {
    'wood_den_80s': {
        'label': '1980s wood den',
        'blurb': 'Family television, wood panel, harvest lamp.',
        'ambience': 'scanlines',
        'backdrop': '#1a1410',
        'glow': '#ffb765',
        'accent': '#e8c07d',
        'surface': 'wood',
    },
    'teen_bedroom_90s': {
        'label': '1990s teen bedroom',
        'blurb': 'Posters, carpet, afternoon window, console on the floor.',
        'ambience': 'daylight',
        'backdrop': '#1c1524',
        'glow': '#d4a574',
        'accent': '#c9a0d4',
        'surface': 'carpet',
    },
    'carpet_den_late_90s': {
        'label': 'Late-90s carpet den',
        'blurb': 'Basement rec room, disc cases, tube still in the corner.',
        'ambience': 'cool',
        'backdrop': '#121018',
        'glow': '#6a8cff',
        'accent': '#9bb0ff',
        'surface': 'carpet',
    },
    'media_center_00s': {
        'label': '2000s media centre',
        'blurb': 'Silver-black stand, tray-loading boxes, evening window.',
        'ambience': 'cool',
        'backdrop': '#0b1220',
        'glow': '#3f9bff',
        'accent': '#7fd3ff',
        'surface': 'matte',
    },
    'arcade_cabinet': {
        'label': 'Arcade floor',
        'blurb': 'Dark room, marquee overhead, coins on the bezel.',
        'ambience': 'marquee',
        'backdrop': '#08060f',
        'glow': '#ff2d6f',
        'accent': '#25e0ff',
        'surface': 'blacklight',
    },
    'desk': {
        'label': 'Computer desk',
        'blurb': 'Home computer, desk lamp, phosphor glow.',
        'ambience': 'phosphor',
        'backdrop': '#0d1410',
        'glow': '#5ef08a',
        'accent': '#a9f7c1',
        'surface': 'beige',
    },
}

DEFAULT_ROOM = 'wood_den_80s'

# LCD / handheld panels — scanlines stay off even when the room is a bedroom.
LCD_PLATFORMS: frozenset[str] = frozenset({
    'GB', 'GBC', 'GBA', 'NDS', 'N3DS', 'PSP', 'PSVITA',
    'LYNX', 'NGP', 'NGPC', 'WS', 'SUPERVISION', 'ADVISION', 'SEGA_GG',
    'POKE_MINI', 'GAME_WATCH',
})

PLATFORM_ROOMS: dict[str, str] = {
    # 1980s family television
    'NES': 'wood_den_80s',
    'SEGA_MS': 'wood_den_80s',
    'SEGA_SG1000': 'wood_den_80s',
    'GAME_WATCH': 'wood_den_80s',
    'ATARI_2600': 'wood_den_80s',
    'ATARI_5200': 'wood_den_80s',
    'ATARI_7800': 'wood_den_80s',
    'INTV': 'wood_den_80s',
    'COLECO': 'wood_den_80s',
    'CHAF': 'wood_den_80s',
    'O2EM': 'wood_den_80s',
    'VECTREX': 'wood_den_80s',
    'ASTROCADE': 'wood_den_80s',
    'ARCADIA': 'wood_den_80s',
    'CREATIVISION': 'wood_den_80s',
    'STUDIO2': 'wood_den_80s',
    'PCE': 'wood_den_80s',
    'SUPERGRAFX': 'wood_den_80s',
    'GX4000': 'wood_den_80s',

    # 1990s teen bedroom — carts and pocket systems of that decade
    'SNES': 'teen_bedroom_90s',
    'SEGA_MD': 'teen_bedroom_90s',
    'SEGA_32X': 'teen_bedroom_90s',
    'GB': 'teen_bedroom_90s',
    'GBC': 'teen_bedroom_90s',
    'SEGA_GG': 'teen_bedroom_90s',
    'LYNX': 'teen_bedroom_90s',
    'NGP': 'teen_bedroom_90s',
    'NGPC': 'teen_bedroom_90s',
    'WS': 'teen_bedroom_90s',
    'SUPERVISION': 'teen_bedroom_90s',
    'ADVISION': 'teen_bedroom_90s',
    'VB': 'teen_bedroom_90s',
    'SEGA_PICO': 'teen_bedroom_90s',

    # Late-90s carpet den / rec room
    'N64': 'carpet_den_late_90s',
    'PSX': 'carpet_den_late_90s',
    'SEGA_SATURN': 'carpet_den_late_90s',
    'SEGA_CD': 'carpet_den_late_90s',
    'JAGUAR': 'carpet_den_late_90s',
    'THREEDO': 'carpet_den_late_90s',
    'PCFX': 'carpet_den_late_90s',
    'PCE_CD': 'carpet_den_late_90s',
    'JAGUAR_CD': 'carpet_den_late_90s',
    'CD_I': 'carpet_den_late_90s',
    'AMIGA_CD32': 'carpet_den_late_90s',

    # 2000s media centre (disc boxes + later handhelds)
    'PS2': 'media_center_00s',
    'PS3': 'media_center_00s',
    'NGC': 'media_center_00s',
    'WII': 'media_center_00s',
    'SEGA_DC': 'media_center_00s',
    'SWITCH': 'media_center_00s',
    'WII_U': 'media_center_00s',
    'XBOX': 'media_center_00s',
    'X360': 'media_center_00s',
    'XONE': 'media_center_00s',
    'XSX': 'media_center_00s',
    'GBA': 'media_center_00s',
    'NDS': 'media_center_00s',
    'N3DS': 'media_center_00s',
    'PSP': 'media_center_00s',
    'PSVITA': 'media_center_00s',
    'POKE_MINI': 'media_center_00s',

    # Coin-op and cabinet-derived hardware
    'ARCADE': 'arcade_cabinet',
    'NEOGEO': 'arcade_cabinet',
    'NEOGEO_CD': 'arcade_cabinet',
    'DAPHNE': 'arcade_cabinet',
    'PINBALL': 'arcade_cabinet',

    # Computers
    'PCWIN': 'desk',
    'PCDOS': 'desk',
    'MAC': 'desk',
    'AMIGA': 'desk',
    'VICE_X64SC': 'desk',
    'VICE_X128': 'desk',
    'VICE_XVIC': 'desk',
    'VICE_XPLUS4': 'desk',
    'VICE_XPET': 'desk',
    'MSX': 'desk',
    'ZX_SPECTRUM': 'desk',
    'CPC': 'desk',
    'ATARI_ST': 'desk',
    'APPLE_II': 'desk',
    'ATARI_8BIT': 'desk',
    'X68000': 'desk',
    'PC_98': 'desk',
    'BBC_MICRO': 'desk',
}


def room_id_for_platform(platform_key: str | None) -> str:
    return PLATFORM_ROOMS.get((platform_key or '').strip().upper(), DEFAULT_ROOM)


def is_lcd_platform(platform_key: str | None) -> bool:
    """Handheld LCD panels never had CRT scanlines, even in a bedroom."""
    return (platform_key or '').strip().upper() in LCD_PLATFORMS


def room_for_platform(platform_key: str | None) -> dict:
    """Full room treatment for a platform, including its era font.

    Returns the default room for anything unmapped rather than raising — a new
    console should look plausible on day one, not break the play page.
    """
    key = (platform_key or '').strip().upper() or None
    room_id = room_id_for_platform(key)
    room = dict(ROOMS[room_id])
    font = font_for_platform(platform_key)
    room.update({
        'id': room_id,
        'platform': key,
        'font_stack': font['stack'],
        'font_label': font['label'],
        'lcd': is_lcd_platform(key),
    })
    return room


