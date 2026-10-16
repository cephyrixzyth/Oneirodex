"""Parse ROM region / language tags from filenames (No-Intro style)."""

from __future__ import annotations

import os
import re
from typing import Any

from oneirodex.utils.rom_language_patterns import LANG_LIST_PAREN_RE, REGION_CAPTURE_RE

# Capture the first region-like parenthetical for storage.
_REGION_CAPTURE = REGION_CAPTURE_RE

# Language lists inside parens, e.g. (En,Fr,De) or (En,Ja)
_LANG_LIST = LANG_LIST_PAREN_RE

_REGION_NORMALIZE = {
    'u': 'USA',
    'usa': 'USA',
    'ue': 'USA',
    'ju': 'JPN',
    'j': 'JPN',
    'jp': 'JPN',
    'japan': 'JPN',
    'e': 'EUR',
    'eu': 'EUR',
    'europe': 'EUR',
    'world': 'WORLD',
    'asia': 'OTHER',
    'brazil': 'OTHER',
    'korea': 'OTHER',
    'australia': 'EUR',
    'france': 'EUR',
    'germany': 'EUR',
    'spain': 'EUR',
    'italy': 'EUR',
    'netherlands': 'EUR',
    'sweden': 'EUR',
    'china': 'OTHER',
    'hong kong': 'OTHER',
    'taiwan': 'OTHER',
    'russia': 'OTHER',
}

_LANG_NORMALIZE = {
    'en': 'en',
    'fr': 'fr',
    'de': 'de',
    'es': 'es',
    'it': 'it',
    'nl': 'nl',
    'pt': 'pt',
    'ru': 'ru',
    'ja': 'ja',
    'zh': 'zh',
    'ko': 'ko',
    'pl': 'pl',
    'sv': 'sv',
    'no': 'no',
    'da': 'da',
    'fi': 'fi',
    'hu': 'hu',
    'cs': 'cs',
    'tr': 'tr',
    'ar': 'ar',
}

_PATCH_EXTS = frozenset({'.ips', '.bps', '.ups'})

# Preferred locale → language tags that satisfy it
_LOCALE_LANGS = {
    'en': frozenset({'en'}),
    'en-us': frozenset({'en'}),
    'en-gb': frozenset({'en'}),
    'ja': frozenset({'ja'}),
    'ja-jp': frozenset({'ja'}),
    'es': frozenset({'es'}),
    'fr': frozenset({'fr'}),
    'de': frozenset({'de'}),
}


def _basename(path_or_name: str) -> str:
    raw = (path_or_name or '').strip()
    if not raw:
        return ''
    return os.path.basename(raw.replace('\\', '/'))


def normalize_region_token(token: str) -> str | None:
    key = (token or '').strip().lower()
    return _REGION_NORMALIZE.get(key)


def parse_rom_language_tags(path_or_name: str) -> dict[str, Any]:
    """Extract region + language codes from a ROM path or display name."""
    name = _basename(path_or_name)
    region = None
    m_region = _REGION_CAPTURE.search(name)
    if m_region:
        region = normalize_region_token(m_region.group(1))

    languages: list[str] = []
    for match in _LANG_LIST.finditer(name):
        for part in match.group(1).split(','):
            code = _LANG_NORMALIZE.get(part.strip().lower())
            if code and code not in languages:
                languages.append(code)

    # Heuristic: USA / World without language list → English
    if not languages and region in {'USA', 'WORLD'}:
        languages = ['en']
    # Japan without language list → Japanese
    if not languages and region == 'JPN':
        languages = ['ja']
    # Europe without list → often multi; leave empty (unknown)

    has_english = 'en' in languages
    return {
        'rom_region': region,
        'rom_languages': ','.join(languages) if languages else None,
        'has_english': has_english if languages else None,
        'languages': languages,
    }


def rom_language_fields_from_path(path_or_name: str | None) -> dict[str, Any]:
    """Return only the stored region/language fields for a dump label or path."""
    label = os.path.basename(str(path_or_name).replace('\\', '/').rstrip('/')) if path_or_name else ''
    if not label:
        return {'rom_region': None, 'rom_languages': None}
    parsed = parse_rom_language_tags(label)
    return {
        'rom_region': parsed.get('rom_region'),
        'rom_languages': parsed.get('rom_languages'),
    }


def preferred_language_codes(preferred: str | None) -> frozenset[str]:
    """Language tags that satisfy preferred_game_locale."""
    pref = (preferred or 'en-US').strip().lower() or 'en-us'
    return (
        _LOCALE_LANGS.get(pref)
        or _LOCALE_LANGS.get(pref.split('-')[0])
        or frozenset({pref.split('-')[0]})
    )


def preferred_locale_matches(preferred: str | None, languages: list[str] | None, *, region: str | None = None) -> bool | None:
    """True when ROM languages satisfy preferred_game_locale; None if unknown."""
    pref = (preferred or 'en-US').strip().lower() or 'en-us'
    langs = languages or []
    if not langs:
        # Region-only guess
        if region == 'USA' and pref.startswith('en'):
            return True
        if region == 'JPN' and pref.startswith('ja'):
            return True
        return None
    accepted = preferred_language_codes(pref)
    return bool(accepted.intersection(langs))


def needs_translation_sql_filter(preferred: str | None):
    """SQLAlchemy clause: ROM language known and does not match preferred locale.

    Unknown (no langs + ambiguous region) is excluded — same as preferred_locale_matches → None.
    """
    from sqlalchemy import and_, func, or_

    from oneirodex.models import Game

    codes = preferred_language_codes(preferred)
    pref = (preferred or 'en-US').strip().lower() or 'en-us'
    padded = func.concat(',', func.coalesce(Game.rom_languages, ''), ',')
    has_any_lang = and_(Game.rom_languages.isnot(None), Game.rom_languages != '')
    has_preferred = or_(*[padded.contains(f',{code},') for code in sorted(codes)])
    explicit_mismatch = and_(has_any_lang, ~has_preferred)

    no_langs = or_(Game.rom_languages.is_(None), Game.rom_languages == '')
    region_bits = []
    if pref.startswith('en') or 'en' in codes:
        region_bits.append(and_(no_langs, Game.rom_region == 'JPN'))
    if pref.startswith('ja') or 'ja' in codes:
        region_bits.append(and_(no_langs, Game.rom_region == 'USA'))

    if region_bits:
        return or_(explicit_mismatch, *region_bits)
    return explicit_mismatch


def rom_browse_flags(
    game,
    preferred_locale: str | None = 'en-US',
    *,
    has_translation_patch: bool = False,
) -> dict[str, Any]:
    """Card/browse fields for LANG / PATCH badges and chips."""
    rom_languages_raw = getattr(game, 'rom_languages', None) or ''
    rom_lang_list = [part.strip() for part in rom_languages_raw.split(',') if part.strip()]
    rom_region = getattr(game, 'rom_region', None)
    locale_matches = preferred_locale_matches(
        preferred_locale, rom_lang_list, region=rom_region
    )
    return {
        'rom_region': rom_region,
        'rom_languages': getattr(game, 'rom_languages', None),
        'has_english': getattr(game, 'has_english', None),
        'preferred_game_locale': preferred_locale or 'en-US',
        'preferred_locale_matches': locale_matches,
        'needs_translation': locale_matches is False,
        'has_translation_patch': bool(has_translation_patch),
    }


def apply_rom_language_fields(
    game,
    path_or_name: str | None = None,
    *,
    peel: dict[str, Any] | None = None,
) -> None:
    """Set rom_* columns on a Game from peel capture or path/name parse.

    Prefer console-peel captures when ``peel`` includes ``rom_region`` /
    ``rom_languages`` keys (including explicit None). Otherwise parse the dump
    label from ``path_or_name`` / ``game.full_disk_path`` / ``game.name``.
    """
    if isinstance(peel, dict) and ('rom_region' in peel or 'rom_languages' in peel):
        game.rom_region = peel.get('rom_region')
        game.rom_languages = peel.get('rom_languages')
        if 'has_english' in peel:
            game.has_english = peel.get('has_english')
        else:
            langs_raw = game.rom_languages or ''
            langs = [part.strip() for part in langs_raw.split(',') if part.strip()]
            game.has_english = ('en' in langs) if langs else None
        return

    source = path_or_name or getattr(game, 'full_disk_path', None) or getattr(game, 'name', '') or ''
    parsed = parse_rom_language_tags(source)
    game.rom_region = parsed['rom_region']
    game.rom_languages = parsed['rom_languages']
    game.has_english = parsed['has_english']


def classify_patch_file(filename: str) -> dict[str, Any] | None:
    """Return translation_patch metadata when filename is .ips/.bps/.ups."""
    base = _basename(filename)
    root, ext = os.path.splitext(base)
    lower = ext.lower()
    if lower not in _PATCH_EXTS:
        return None
    # Optional language hint in filename: en, english, eng
    target = None
    lowered = root.lower()
    for code in ('en', 'fr', 'de', 'es', 'it', 'ja', 'pt', 'ru', 'zh', 'ko'):
        if re.search(rf'(^|[^a-z]){code}([^a-z]|$)', lowered) or f'{code}glish' in lowered:
            target = code
            break
    if 'english' in lowered or 'eng' in lowered.split('_') or 'eng' in lowered.split('-'):
        target = 'en'
    return {
        'extra_kind': 'translation_patch',
        'patch_format': lower.lstrip('.'),
        'target_language': target or 'en',
    }
