"""Full-color AI system marks for the Systems hub (per platform × theme).

Stance matches :mod:`oneirodex.utils.ai_artwork`:

* Off unless ``ENABLE_AI_ARTWORK`` is truthy and ``AI_ARTWORK_URL`` is set.
* Prompts carry only catalogue facts (platform name, form factor) plus theme
  palette / era keywords derived from preset tokens — never paths, usernames,
  or library layout.
* Idempotent writes under ``static/library/system-marks/<theme>/<platform>.webp``.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

from oneirodex.platform import LibraryPlatform
from oneirodex.utils.ai_artwork import (
    ArtworkGenerationError,
    ai_artwork_enabled,
    get_generator,
)
from oneirodex.utils.preset_themes import (
    PRESET_BY_SLUG,
    PRESET_SLUGS,
    era_for_theme,
    preset_tokens,
)
from oneirodex.utils.library_paths import library_dir

MARK_SIZE = 256
# Generate larger then downscale — SD reads hardware shape better at 512.
GEN_SIZE = 512
MARK_TIMEOUT = 180.0
PROMPT_MAX = 1500
_SAFE_SLUG = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')

_NEGATIVE = (
    'text, watermark, signature, letters, words, typography, brand logo, '
    'blurry, lowres, jpeg artifacts, abstract geometry, pattern tiles, '
    'busy collage, multiple consoles, duplicate object, split screen, '
    'frame, border, UI chrome, photoreal hands, people, face, room interior, '
    'cluttered background, random shapes, unrecognizable blob'
)

_ERA_LIGHT = {
    'wood_den_80s': 'warm CRT amber rim light',
    'teen_bedroom_90s': 'saturated neon edge light',
    'carpet_den_late_90s': 'soft lamp fill, muted plastics',
    'media_center_00s': 'cool silver media-centre light',
    'arcade_cabinet': 'arcade neon rim light',
    'desk': 'cool monitor desk light',
}

# Distinctive hardware look per LibraryPlatform.name.lower() — the model must
# recognise a real console/handheld, not invent an abstract motif.
_PLATFORM_LOOK: dict[str, str] = {
    'other': 'generic grey game cartridge standing upright',
    'pcwin': 'beige Windows-era PC tower beside a CRT monitor',
    'pcdos': '1980s beige PC XT tower with CRT monitor',
    'mac': 'classic compact Macintosh computer with CRT',
    'nes': 'grey Nintendo NES front-loading console with red power LED',
    'snes': 'purple-grey Super Nintendo console with dual cartridge slot contour',
    'ngc': 'indigo purple GameCube console cube with handle grip',
    'n64': 'dark grey Nintendo 64 console with unique controller port cluster',
    'gb': 'original grey Nintendo Game Boy handheld with greenish LCD',
    'gba': 'indigo Nintendo Game Boy Advance handheld landscape form',
    'gbc': 'clear purple Nintendo Game Boy Color handheld',
    'nds': 'Nintendo DS dual-screen clamshell handheld open',
    'vb': 'red and black Nintendo Virtual Boy headset stand',
    'wii': 'white Nintendo Wii console slim standing',
    'n3ds': 'Nintendo 3DS dual-screen hinged handheld open',
    'sega_md': 'black Sega Genesis Mega Drive console with raised cartridge slot',
    'sega_ms': 'black Sega Master System console with cartridge door',
    'sega_cd': 'Sega CD add-on deck attached under Mega Drive',
    'sega_32x': 'black Sega 32X pyramid addon on Genesis',
    'sega_gg': 'Sega Game Gear handheld with colour LCD bezel',
    'sega_saturn': 'grey Sega Saturn dual-speed CD console',
    'sega_dc': 'white Sega Dreamcast swirl-lid console',
    'atari_7800': 'black Atari 7800 console with woodgrain faceplate',
    'atari_5200': 'large beige Atari 5200 console with keypad controllers',
    'atari_2600': 'black Atari 2600 woodgrain console with joystick',
    'lynx': 'Atari Lynx landscape handheld with curved body',
    'jaguar': 'black Atari Jaguar console with unique controller',
    'pce': 'white PC Engine / TurboGrafx-16 compact console',
    'pcfx': 'black NEC PC-FX console tower',
    'ngp': 'Neo Geo Pocket handheld monochrome',
    'ws': 'Bandai WonderSwan handheld unique sideways form',
    'coleco': 'ColecoVision console with controller holster',
    'threedo': 'black 3DO Interactive Multiplayer disc console',
    'vectrex': 'Vectrex vector arcade cabinet with built-in screen',
    'vice_x64sc': 'beige Commodore 64 home computer keyboard',
    'vice_x128': 'beige Commodore 128 computer keyboard',
    'vice_xvic': 'beige Commodore VIC-20 computer',
    'vice_xplus4': 'dark Commodore Plus/4 computer',
    'vice_xpet': 'Commodore PET all-in-one with built-in CRT',
    'xbox': 'original green and black Xbox console',
    'x360': 'white Xbox 360 console',
    'xone': 'black Xbox One console',
    'xsx': 'black Xbox Series X tall tower console',
    'psx': 'grey original PlayStation console with CD lid',
    'ps2': 'black PlayStation 2 fat console',
    'ps3': 'black PlayStation 3 console',
    'ps4': 'black PlayStation 4 console',
    'ps5': 'white and black PlayStation 5 tall console',
    'psp': 'black Sony PSP handheld with analog nub',
    'psvita': 'black Sony PS Vita OLED handheld',
    'intv': 'woodgrain Intellivision console',
    'chaf': 'Fairchild Channel F console with yellow controller',
    'o2em': 'Magnavox Odyssey 2 console with membrane keyboard',
    'neogeo_cd': 'Neo Geo CD console',
    'neogeo': 'black Neo Geo AES cartridge console',
    'switch': 'Nintendo Switch hybrid handheld with neon Joy-Cons',
    'arcade': 'upright arcade cabinet with marquee and joystick',
    'amiga': 'beige Commodore Amiga computer',
    'sega_sg1000': 'black Sega SG-1000 console',
    'supergrafx': 'PC Engine SuperGrafx console',
    'pce_cd': 'PC Engine CD / TurboGrafx-CD deck',
    'ngpc': 'Neo Geo Pocket Color handheld',
    'supervision': 'Watara Supervision handheld',
    'gx4000': 'Amstrad GX4000 console',
    'astrocade': 'Bally Astrocade console',
    'arcadia': 'Emerson Arcadia 2001 console',
    'creativision': 'VTech CreatiVision console cartridge',
    'advision': 'Entex Adventure Vision tabletop',
    'studio2': 'RCA Studio II console',
    'actionmax': 'Action Max light-gun VHS game system',
    'daphne': 'laserdisc arcade cabinet',
    'pinball': 'pinball machine cabinet with flippers and playfield glass',
}


def platform_ids() -> list[str]:
    return [member.name.lower() for member in LibraryPlatform]


def platform_choices() -> list[dict[str, str]]:
    """Id + display label for the Art Studio lab picker."""
    return [{'id': member.name.lower(), 'label': member.value} for member in LibraryPlatform]


def theme_slugs() -> list[str]:
    return ['default', *PRESET_SLUGS]


def _validate_slug(value: str, *, kind: str) -> str:
    slug = (value or '').strip().lower()
    if not _SAFE_SLUG.match(slug):
        raise ValueError(f'Invalid {kind} slug')
    return slug


def marks_root(package_root: str | Path | None = None) -> Path:
    return Path(library_dir(package_root)) / 'system-marks'


def theme_dir(theme: str, package_root: str | Path | None = None) -> Path:
    slug = _validate_slug(theme, kind='theme')
    if slug != 'default' and slug not in PRESET_BY_SLUG:
        raise ValueError(f'Unknown theme slug: {slug}')
    return marks_root(package_root) / slug


def mark_path(theme: str, platform: str, package_root: str | Path | None = None) -> Path:
    plat = _validate_slug(platform, kind='platform')
    if plat not in set(platform_ids()):
        raise ValueError(f'Unknown platform id: {plat}')
    return theme_dir(theme, package_root) / f'{plat}.webp'


def static_mark_url(theme: str, platform: str) -> str:
    theme_slug = _validate_slug(theme, kind='theme')
    plat = _validate_slug(platform, kind='platform')
    return f'/static/library/system-marks/{theme_slug}/{plat}.webp'


def mark_exists(theme: str, platform: str, package_root: str | Path | None = None) -> bool:
    try:
        return mark_path(theme, platform, package_root).is_file()
    except ValueError:
        return False


def _platform_label(platform_id: str) -> str:
    for member in LibraryPlatform:
        if member.name.lower() == platform_id:
            return member.value
    return platform_id


def _hardware_look(platform_id: str) -> str:
    return _PLATFORM_LOOK.get(platform_id, f'{_platform_label(platform_id)} game hardware')


def _theme_style_bits(theme: str) -> dict[str, str]:
    slug = _validate_slug(theme, kind='theme')
    era = era_for_theme(slug)
    light = _ERA_LIGHT.get(era, _ERA_LIGHT['wood_den_80s'])
    if slug == 'default':
        return {
            'accent': '#2fd67b',
            'bg': '#0b0d10',
            'era': era,
            'light': light,
            'label': 'Default',
        }
    preset = PRESET_BY_SLUG[slug]
    tokens = preset_tokens(preset)
    return {
        'accent': str(tokens.get('od-accent') or preset.get('btn_primary') or '#2fd67b'),
        'bg': str(tokens.get('od-bg') or '#0b0d10'),
        'era': era,
        'light': light,
        'label': str(preset.get('name') or slug),
    }


def build_system_mark_prompt(*, platform: str, theme: str) -> str:
    """Compose the txt2img prompt from platform + theme facts only."""
    plat = _validate_slug(platform, kind='platform')
    if plat not in set(platform_ids()):
        raise ValueError(f'Unknown platform id: {plat}')
    style = _theme_style_bits(theme)
    label = _platform_label(plat)
    look = _hardware_look(plat)
    # Hardware identity first; theme only tints lighting / accent.
    return (
        f'product icon of {look}, clearly recognizable {label}, '
        f'single centered object, three-quarter view, sharp silhouette, '
        f'solid dark background {style["bg"]}, subtle accent glow {style["accent"]}, '
        f'{style["light"]}, game hardware product shot, high detail, no text'
    )


def _resolve_mark_prompt(*, platform: str, theme: str, prompt: str | None = None) -> str:
    custom = (prompt or '').strip()
    if custom:
        if len(custom) > PROMPT_MAX:
            raise ValueError(f'prompt must be {PROMPT_MAX} characters or fewer')
        return custom
    return build_system_mark_prompt(platform=platform, theme=theme)


def system_mark_lab_spec(
    *,
    theme: str,
    platform: str,
    package_root: str | Path | None = None,
) -> dict[str, Any]:
    """Prompt + current file for the Art Studio one-at-a-time lab."""
    plat = _validate_slug(platform, kind='platform')
    if plat not in set(platform_ids()):
        raise ValueError(f'Unknown platform id: {plat}')
    theme_slug = _validate_slug(theme, kind='theme')
    if theme_slug != 'default' and theme_slug not in PRESET_BY_SLUG:
        raise ValueError(f'Unknown theme slug: {theme_slug}')
    return {
        'theme': theme_slug,
        'platform': plat,
        'label': _platform_label(plat),
        'prompt': build_system_mark_prompt(platform=plat, theme=theme_slug),
        'negative': _NEGATIVE,
        'url': static_mark_url(theme_slug, plat),
        'exists': mark_exists(theme_slug, plat, package_root),
    }


def _png_to_webp(png_bytes: bytes, *, size: int = MARK_SIZE) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format='WEBP', quality=88, method=4)
    return out.getvalue()


def _read_manifest(theme: str, package_root: str | Path | None = None) -> dict[str, Any]:
    path = theme_dir(theme, package_root) / 'manifest.json'
    if not path.is_file():
        return {'theme': theme, 'platforms': []}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'theme': theme, 'platforms': []}
    if not isinstance(data, dict):
        return {'theme': theme, 'platforms': []}
    platforms = data.get('platforms') or []
    if not isinstance(platforms, list):
        platforms = []
    return {
        'theme': theme,
        'platforms': [str(p).lower() for p in platforms if str(p).strip()],
    }


def _write_manifest(theme: str, platforms: list[str], package_root: str | Path | None = None) -> None:
    directory = theme_dir(theme, package_root)
    directory.mkdir(parents=True, exist_ok=True)
    unique = sorted({p.lower() for p in platforms})
    payload = {
        'theme': _validate_slug(theme, kind='theme'),
        'platforms': unique,
        'size': MARK_SIZE,
    }
    (directory / 'manifest.json').write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def list_system_marks_catalog(package_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Catalog rows for Art Studio / ops (one row per theme)."""
    rows: list[dict[str, Any]] = []
    for theme in theme_slugs():
        manifest = _read_manifest(theme, package_root)
        present = [
            pid for pid in platform_ids()
            if mark_exists(theme, pid, package_root)
        ]
        rows.append({
            'theme': theme,
            'era': era_for_theme(theme),
            'generated': len(present),
            'total': len(platform_ids()),
            'platforms': present,
            'manifest_platforms': manifest.get('platforms') or [],
            'complete': len(present) >= len(platform_ids()),
        })
    return rows


def generate_system_mark(
    *,
    theme: str,
    platform: str,
    package_root: str | Path | None = None,
    force: bool = False,
    timeout: float = MARK_TIMEOUT,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Generate one mark. Skips when the file exists unless *force*."""
    used_prompt = _resolve_mark_prompt(platform=platform, theme=theme, prompt=prompt)
    path = mark_path(theme, platform, package_root)
    if path.is_file() and not force:
        return {
            'theme': theme,
            'platform': platform,
            'url': static_mark_url(theme, platform),
            'skipped': True,
            'prompt': used_prompt,
        }

    if not ai_artwork_enabled():
        raise ArtworkGenerationError('AI artwork is disabled (ENABLE_AI_ARTWORK)')

    prompt = used_prompt
    png = get_generator().generate(
        prompt,
        width=GEN_SIZE,
        height=GEN_SIZE,
        timeout=timeout,
        negative_prompt=_NEGATIVE,
    )
    webp = _png_to_webp(png, size=MARK_SIZE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(webp)

    manifest = _read_manifest(theme, package_root)
    platforms = list(manifest.get('platforms') or [])
    plat = _validate_slug(platform, kind='platform')
    if plat not in platforms:
        platforms.append(plat)
    _write_manifest(theme, platforms, package_root)

    return {
        'theme': theme,
        'platform': platform,
        'url': static_mark_url(theme, platform),
        'skipped': False,
        'prompt': prompt,
    }


def generate_system_marks(
    *,
    themes: list[str] | None = None,
    platforms: list[str] | None = None,
    package_root: str | Path | None = None,
    force: bool = False,
    limit: int | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    """Batch generate marks. Idempotent; returns counts and per-item results."""
    theme_list = [_validate_slug(t, kind='theme') for t in (themes or theme_slugs())]
    for theme in theme_list:
        if theme != 'default' and theme not in PRESET_BY_SLUG:
            raise ValueError(f'Unknown theme slug: {theme}')
    plat_list = [_validate_slug(p, kind='platform') for p in (platforms or platform_ids())]
    known = set(platform_ids())
    for plat in plat_list:
        if plat not in known:
            raise ValueError(f'Unknown platform id: {plat}')

    results: list[dict[str, Any]] = []
    generated = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    remaining = limit
    planned = len(theme_list) * len(plat_list)
    if remaining is not None:
        planned = min(planned, remaining)
    done = 0

    for theme in theme_list:
        for plat in plat_list:
            if remaining is not None and remaining <= 0:
                break
            try:
                row = generate_system_mark(
                    theme=theme,
                    platform=plat,
                    package_root=package_root,
                    force=force,
                    prompt=prompt,
                )
                results.append({
                    'theme': row['theme'],
                    'platform': row['platform'],
                    'url': row['url'],
                    'skipped': row['skipped'],
                    'prompt': row.get('prompt') or '',
                })
                if row['skipped']:
                    skipped += 1
                    status = 'skip'
                else:
                    generated += 1
                    status = 'ok'
                    if remaining is not None:
                        remaining -= 1
            except (ArtworkGenerationError, ValueError, OSError) as exc:
                errors.append({
                    'theme': theme,
                    'platform': plat,
                    'error': str(exc),
                })
                status = f'err:{exc}'
            done += 1
            print(f'[{done}/{planned}] {theme}/{plat} {status}', flush=True)
        if remaining is not None and remaining <= 0:
            break

    return {
        'generated': generated,
        'skipped': skipped,
        'errors': errors,
        'count': len(results),
        'results': results,
    }
