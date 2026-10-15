"""Shared ROM name peel patterns (No-Intro / GoodTools) and console file-leaf parser."""

from __future__ import annotations

import os
import re
from typing import Any

from oneirodex.platform import LibraryPlatform
from oneirodex.utils.game_name_parse import (
    _record_transform,
    inject_franchise_apostrophes,
    normalize_smart_apostrophes,
    strip_repack_tags,
    strip_unbracketed_scene_suffix,
)
from oneirodex.utils.rom_archive import ARCHIVE_EXTENSIONS, PLATFORM_DUMP_SUFFIXES
from oneirodex.utils.rom_language_patterns import LANG_LIST_PAREN_RE, REGION_CAPTURE_RE

# --- Shared peel regex (single source — imported by set_completion + rom_language) ---

_PEEL_EXT_ALTS = '|'.join(
    sorted(
        {suffix.lstrip('.') for suffix in (PLATFORM_DUMP_SUFFIXES | ARCHIVE_EXTENSIONS)},
        key=lambda token: (-len(token), token),
    )
)
ROM_EXT_RE = re.compile(rf'\.(?:{_PEEL_EXT_ALTS})$', re.IGNORECASE)
DUMP_BRACKETS_RE = re.compile(r'\s*\[[^\]]*\]')
REGION_PAREN_RE = re.compile(
    r'\s*\((?:USA|Europe|Japan|World|UE|JU|EU|JP|U|J|E|Asia|Brazil|Korea|'
    r'Australia|France|Germany|Spain|Italy|Netherlands|Sweden|China|'
    r'Hong Kong|Taiwan|Russia|En,Fr,De|En,Ja)[^)]*\)',
    re.IGNORECASE,
)
REV_PAREN_RE = re.compile(
    r'\s*\((?:Rev\s*[A-Z0-9]+|v?\d+(?:\.\d+)*|Proto|Beta|Sample|Demo|'
    r'Unl|Aftermarket|Pirate|Virtual Console|Switch Online|Wii U Virtual Console|'
    r'GB Compatibility|SGB Enhanced|NTSC|PAL|NTSC-J)[^)]*\)',
    re.IGNORECASE,
)
# BE-DET-5 — Redump / scene disc tokens: (Disc 1), (Disk 2), (CD1), (CD 2).
DISC_PAREN_RE = re.compile(
    r'\s*\(\s*(?:Disc|Disk|CD)\s*(\d+)\s*\)',
    re.IGNORECASE,
)
REMAINING_SIMPLE_PAREN_RE = re.compile(r'\s*\([^)]{1,40}\)')
MULTI_SPACE_RE = re.compile(r'\s+')

# GoodTools / status flags that force propose-only (checked on raw basename).
_PROPOSE_BRACKET_FLAGS_RE = re.compile(r'\[(?:h|T|tr)\]', re.IGNORECASE)
_PROPOSE_STATUS_PAREN_RE = re.compile(
    r'\(\s*(?:Proto|Beta|Demo|Sample|Unl|Aftermarket|Pirate|Tr|Hacker)\b',
    re.IGNORECASE,
)
_MULTICART_RE = re.compile(
    r'(?:\b\d+\s*-?\s*in\s*-?\s*\d+\b|\bMaxi\s+\d+\b|'
    r'Action\s+Replay|Game\s+Genie|\[BIOS\])',
    re.IGNORECASE,
)
_METADATA_REGION_SHORTHAND_RE = re.compile(
    r'^(?:Jp-US|EU-US|US-EU|Jp-Eu)$',
    re.IGNORECASE,
)
_METADATA_PUBLISHER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .&'\-]{0,30}$")

# Identify wire — helper itself works for any console platform.
# PC / Mac / Other keep parse_game_label (FitGirl, Steam IDs, VR tails).
# Every other LibraryPlatform peels No-Intro / Redump / GoodTools names so a
# HuCard dump named ``Bomberman (Japan).pce`` searches IGDB as Bomberman, not
# the filename. Folders-mode still requires dump-shaped labels (BE-DET-2).
_PC_LABEL_PLATFORMS = frozenset({
    LibraryPlatform.OTHER,
    LibraryPlatform.PCWIN,
    LibraryPlatform.PCDOS,
    LibraryPlatform.MAC,
})
CONSOLE_ROM_PEEL_PILOT_PLATFORMS = frozenset(
    p for p in LibraryPlatform if p not in _PC_LABEL_PLATFORMS
)

# BE-DET-8 — MAME/FBNeo-style set folders (AES cart sets share this shape).
# NEOGEO_CD is intentionally excluded (disc Redump forms, not set dirs).
ARCADE_SET_FOLDER_PLATFORMS = frozenset({
    LibraryPlatform.ARCADE,
    LibraryPlatform.NEOGEO,
})

# Immediate child count under scan root / parent at which ARCADE identify
# forces propose-first (Stage E / Unmatched) — no aggressive fuzzy auto-import.
ARCADE_PROPOSE_FIRST_CHILD_THRESHOLD = 50

# Compact set basename after optional archive-ext strip (mslug, sf2ce, kof94…).
_ARCADE_SET_BASENAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,31}$')

# Transform reasons that indicate dump-set naming (not B15 ext / B20 title / leftover parens).
_CONSOLE_DUMP_LOOK_REASONS = frozenset({
    'dump_brackets',
    'region_lang_parens',
    'rev_hardware_parens',
    'metadata_parens',
    'disc_parens',
})

# BE-DET-7 — Switch title-dir scene tags (A1 / A10) in addition to dump brackets.
_SWITCH_SCENE_LOOK_REASONS = frozenset({
    'scene_repack_brackets',
    'unbracketed_scene_suffix',
})

_ARTICLE_SUFFIXES = (', The', ', A', ', An')
_ROM_SMALL_WORDS = frozenset({
    'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to', 'vs',
})


def rom_title_case(working: str) -> str:
    """Title-case ROM display names; keep small words lowercase (IGDB-style).

    Preserve capitalized articles after No-Intro comma suffixes (``Zelda, The``)
    and at the start of a hyphen subtitle (`` - The Minish Cap``).
    """
    if not working:
        return ''
    words = working.split(' ')
    out: list[str] = []
    last_idx = len(words) - 1
    for idx, word in enumerate(words):
        if not word:
            continue
        if word in ('-', '–', '—'):
            out.append(word)
            continue
        punct = ''
        core = word
        if word.endswith(','):
            core = word[:-1]
            punct = ','
        lower = core.lower()
        prev = words[idx - 1] if idx > 0 else ''
        after_hyphen = prev in ('-', '–', '—')
        # No-Intro ``Zelda, The`` — comma lives on the prior token.
        after_comma_token = bool(prev.endswith(','))
        is_article = lower in {'the', 'a', 'an'}
        force_cap_article = is_article and (
            after_comma_token
            or after_hyphen
            or idx == last_idx
        )

        if core.isupper() or re.fullmatch(r'[IVXLC]+', core, re.IGNORECASE):
            cased = core
        elif any(ch.isdigit() for ch in core) and core.upper() == core:
            cased = core
        elif idx == 0 or force_cap_article:
            if is_article:
                cased = core[:1].upper() + core[1:].lower()
            elif core.lower() == core:
                cased = core[:1].upper() + core[1:]
            else:
                cased = core
        elif idx > 0 and lower in _ROM_SMALL_WORDS:
            cased = lower
        elif core.lower() == core:
            cased = core[:1].upper() + core[1:]
        else:
            cased = core
        out.append(cased + punct)
    return ' '.join(out)


def _basename(raw: str) -> str:
    text = (raw or '').strip()
    if not text:
        return ''
    return os.path.basename(text.replace('\\', '/'))


def peel_rom_extensions(text: str) -> str:
    """B15 — strip known ROM/archive extensions."""
    return ROM_EXT_RE.sub('', text or '').strip()


def peel_dump_brackets(text: str) -> str:
    """B16 — strip all GoodTools / dump bracket tags."""
    if not text:
        return ''
    working = text
    while True:
        next_pass = DUMP_BRACKETS_RE.sub('', working).strip()
        if next_pass == working:
            break
        working = next_pass
    return working


def peel_region_and_lang_parens(text: str) -> str:
    """B17 — strip No-Intro region and language-list parentheticals."""
    if not text:
        return ''
    working = text
    while True:
        next_pass = REGION_PAREN_RE.sub('', working).strip()
        next_pass = LANG_LIST_PAREN_RE.sub('', next_pass).strip()
        if next_pass == working:
            break
        working = next_pass
    return working


def peel_rev_and_hardware_parens(text: str) -> str:
    """B18 — strip revision / hardware / status parentheticals."""
    if not text:
        return ''
    working = text
    while True:
        next_pass = REV_PAREN_RE.sub('', working).strip()
        if next_pass == working:
            break
        working = next_pass
    return working


def capture_disc_index(text: str) -> int | None:
    """Return the first ``(Disc|Disk|CD N)`` index from a dump label, or None."""
    if not text:
        return None
    match = DISC_PAREN_RE.search(text)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def peel_disc_parens(text: str) -> str:
    """Strip disc/disk/CD parentheticals (BE-DET-5 — after capture)."""
    if not text:
        return ''
    working = text
    while True:
        next_pass = DISC_PAREN_RE.sub('', working).strip()
        if next_pass == working:
            break
        working = next_pass
    return working


def _is_metadata_paren_inner(inner: str) -> bool:
    s = (inner or '').strip()
    if not s:
        return False
    if re.fullmatch(r'\d{4}', s):
        return True
    if _METADATA_REGION_SHORTHAND_RE.fullmatch(s):
        return True
    if not _METADATA_PUBLISHER_RE.fullmatch(s):
        return False
    head = s.split(',')[0].strip().lower()
    region_heads = {
        'usa', 'europe', 'japan', 'world', 'u', 'e', 'j', 'ue', 'ju', 'eu', 'jp',
        'asia', 'brazil', 'korea', 'australia', 'france', 'germany', 'spain',
        'italy', 'netherlands', 'sweden', 'china', 'hong kong', 'taiwan', 'russia',
    }
    if head in region_heads or head.startswith('rev'):
        return False
    return True


def peel_metadata_parens(text: str) -> str:
    """B19 — strip trailing GoodTools metadata glued parens (year, publisher, Jp-US)."""
    if not text:
        return ''
    working = text.strip()
    while True:
        if not working.endswith(')'):
            break
        open_idx = working.rfind('(')
        if open_idx < 0:
            break
        inner = working[open_idx + 1 : -1]
        if not _is_metadata_paren_inner(inner):
            break
        head = working[:open_idx].strip()
        if not head:
            break
        working = head
    return working


def peel_remaining_simple_parens(text: str) -> str:
    """Strip leftover short parentheticals (DAT normalize + console B19 fallback)."""
    if not text:
        return ''
    working = text
    while True:
        next_pass = REMAINING_SIMPLE_PAREN_RE.sub('', working).strip()
        if next_pass == working:
            break
        working = next_pass
    return working


def normalize_rom_peel_core(name: str | None) -> str:
    """Run B15–B19 without title-case (lowercase-safe for DAT keys)."""
    text = (name or '').strip()
    if not text:
        return ''
    text = peel_rom_extensions(text)
    text = peel_dump_brackets(text)
    text = peel_region_and_lang_parens(text)
    text = peel_rev_and_hardware_parens(text)
    text = peel_metadata_parens(text)
    text = peel_disc_parens(text)
    text = peel_remaining_simple_parens(text)
    text = MULTI_SPACE_RE.sub(' ', text.replace('_', ' ')).strip()
    return text


def normalize_set_title_from_peel(name: str | None) -> str:
    """Lowercase DAT / ownership key — wraps shared peel core."""
    return normalize_rom_peel_core(name).lower()


def _detect_propose_only(raw: str) -> bool:
    return bool(_PROPOSE_BRACKET_FLAGS_RE.search(raw) or _PROPOSE_STATUS_PAREN_RE.search(raw))


def _detect_multicart(raw: str) -> bool:
    return bool(_MULTICART_RE.search(raw))


def _detect_article_suffix(cleaned: str) -> str | None:
    for suffix in _ARTICLE_SUFFIXES:
        if cleaned.endswith(suffix):
            return suffix[2:].strip()
    return None


def looks_like_console_rom_dump_label(raw: str, *, platform: LibraryPlatform | None = None) -> bool:
    """True when basename shows No-Intro / GoodTools dump tags (B16–B19 metadata).

    Reuses ``parse_console_rom_label`` transform trail — does not fork peel regex.
    Extension-only (B15) or title-case (B20) alone do not count.

    BE-DET-7: when ``platform`` is SWITCH, also treat A1/A10 scene tags as dump-shaped
    so title dirs gate console peel (A1∪B16).
    """
    parsed = parse_console_rom_label(raw, platform=platform)
    reasons = _CONSOLE_DUMP_LOOK_REASONS
    if platform == LibraryPlatform.SWITCH:
        reasons = _CONSOLE_DUMP_LOOK_REASONS | _SWITCH_SCENE_LOOK_REASONS
    return any(
        (step.get('reason') in reasons)
        for step in (parsed.get('transforms') or [])
    )


def looks_like_arcade_set_basename(raw: str) -> bool:
    """True for MAME/FBNeo-style compact set folder or zip-per-set basename.

    Examples: ``mslug``, ``mslug.zip``, ``sf2ce``, ``kof94``. Dump-tagged
    titles (``Metal Slug (World)``) are not set basenames — use dump peel.
    """
    base = _basename(raw)
    if not base:
        return False
    stem = peel_rom_extensions(base) if ROM_EXT_RE.search(base) else base
    stem = (stem or '').strip()
    if not stem or ' ' in stem or '(' in stem or '[' in stem:
        return False
    return bool(_ARCADE_SET_BASENAME_RE.fullmatch(stem))


def _count_immediate_children(path: str) -> int | None:
    """Return immediate child count, or None when path missing / unreadable."""
    if not path or not os.path.isdir(path):
        return None
    try:
        return sum(1 for _ in os.scandir(path))
    except OSError:
        return None


def arcade_library_is_large(library, full_disk_path: str | None = None) -> bool:
    """True when an ARCADE leaf looks like a large set tree (propose-first).

    Prefers ``last_scan_folder`` child count, then the leaf parent directory,
    then existing Game row count for the library UUID.
    """
    if getattr(library, 'platform', None) != LibraryPlatform.ARCADE:
        return False
    threshold = ARCADE_PROPOSE_FIRST_CHILD_THRESHOLD
    roots: list[str] = []
    scan_root = getattr(library, 'last_scan_folder', None) or ''
    if scan_root:
        roots.append(scan_root)
    leaf = (full_disk_path or '').rstrip('\\/')
    if leaf:
        parent = os.path.dirname(leaf)
        if parent and parent not in roots:
            roots.append(parent)
    for root in roots:
        count = _count_immediate_children(root)
        if count is not None and count >= threshold:
            return True
    lib_uuid = getattr(library, 'uuid', None)
    if not lib_uuid:
        return False
    try:
        from sqlalchemy import func, select

        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Game

        n = db.session.execute(
            select(func.count()).select_from(Game).where(Game.library_uuid == lib_uuid)
        ).scalar()
        return int(n or 0) >= threshold
    except Exception:
        return False


def should_arcade_propose_first(
    library,
    full_disk_path: str | None = None,
    parsed_label: dict[str, Any] | None = None,
) -> bool:
    """BE-DET-8 — propose-first (no auto-import) for ARCADE set / large trees.

    Compact set basenames are inherently fuzzy vs catalog titles. Large ARCADE
    libs force Stage E / Unmatched propose even for dump-titled leaves.
    """
    if getattr(library, 'platform', None) != LibraryPlatform.ARCADE:
        return False
    if parsed_label and parsed_label.get('is_arcade_set'):
        return True
    return arcade_library_is_large(library, full_disk_path)


def neogeo_aes_cd_conflict(
    left: LibraryPlatform | str | None,
    right: LibraryPlatform | str | None,
) -> bool:
    """True when one side is Neo Geo AES and the other is Neo Geo CD.

    Hard guard — never identify/remap AES ↔ CD (BE-DET-8).
    """
    def _key(value: LibraryPlatform | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, LibraryPlatform):
            return value.name
        text = str(value).strip()
        if not text:
            return None
        upper = text.upper().replace(' ', '_')
        if upper in ('NEOGEO', 'NEOGEO_AES', 'NEO_GEO_AES'):
            return 'NEOGEO'
        if upper in ('NEOGEO_CD', 'NEO_GEO_CD', 'NEOCD'):
            return 'NEOGEO_CD'
        try:
            return LibraryPlatform[upper].name
        except KeyError:
            pass
        # Display strings
        folded = text.casefold()
        if 'neo geo cd' in folded or folded in ('neogeocd', 'neocd'):
            return 'NEOGEO_CD'
        if 'neo geo aes' in folded or folded in ('neogeo', 'neogeoaes'):
            return 'NEOGEO'
        if 'neo geo' in folded and 'cd' not in folded:
            return 'NEOGEO'
        return upper

    a, b = _key(left), _key(right)
    if not a or not b:
        return False
    pair = {a, b}
    return pair == {'NEOGEO', 'NEOGEO_CD'}


def _primary_rom_basenames_in_folder(folder_path: str) -> list[str]:
    """Immediate file children with a known ROM/archive extension (sorted)."""
    if not folder_path or not os.path.isdir(folder_path):
        return []
    try:
        names = os.listdir(folder_path)
    except OSError:
        return []
    out: list[str] = []
    for name in names:
        full = os.path.join(folder_path, name)
        try:
            if not os.path.isfile(full):
                continue
        except OSError:
            continue
        if ROM_EXT_RE.search(name):
            out.append(name)
    out.sort(key=str.lower)
    return out


def _folders_mode_has_dump_label(
    full_disk_path: str,
    *,
    platform: LibraryPlatform | None = None,
) -> bool:
    """Folders leaf uses console peel when dir basename or primary dump looks dump-tagged."""
    path = (full_disk_path or '').rstrip('\\/')
    if looks_like_console_rom_dump_label(_basename(path), platform=platform):
        return True
    for child in _primary_rom_basenames_in_folder(path):
        if looks_like_console_rom_dump_label(child, platform=platform):
            return True
    return False


def _folders_mode_has_arcade_set(
    full_disk_path: str,
    *,
    platform: LibraryPlatform | None = None,
) -> bool:
    """BE-DET-8 — folders leaf gates when ARCADE/NEOGEO AES set basename (or zip child)."""
    if platform not in ARCADE_SET_FOLDER_PLATFORMS:
        return False
    path = (full_disk_path or '').rstrip('\\/')
    if looks_like_arcade_set_basename(_basename(path)):
        return True
    for child in _primary_rom_basenames_in_folder(path):
        if looks_like_arcade_set_basename(child):
            return True
    return False


def should_use_console_rom_peel(
    library,
    full_disk_path: str,
    settings: dict | None = None,
) -> bool:
    """True when identify should use console ROM peel instead of PC parse_game_label."""
    platform = getattr(library, 'platform', None)
    if platform not in CONSOLE_ROM_PEEL_PILOT_PLATFORMS:
        return False
    scan_mode = (settings or {}).get('scan_mode')
    if scan_mode == 'files':
        return True
    if scan_mode == 'folders':
        path = full_disk_path or ''
        if _folders_mode_has_dump_label(path, platform=platform):
            return True
        # BE-DET-8: ARCADE / Neo Geo AES set folders (not NEOGEO_CD).
        return _folders_mode_has_arcade_set(path, platform=platform)
    return os.path.isfile(full_disk_path or '')


def parse_console_rom_label(
    raw: str,
    *,
    platform: LibraryPlatform | None = None,
) -> dict[str, Any]:
    """
    Parse a console ROM file basename into a cleaned IGDB search title.

    Stages B15–B20 (docs/strategy/name-resolution.md console slice).
    BE-DET-7: when ``platform`` is SWITCH, also apply A1 scene/repack brackets and
    A10 unbracketed scene suffixes (title-dir scene peel = A1∪B16).
    BE-DET-8: when ``platform`` is ARCADE or NEOGEO (AES), compact MAME/FBNeo set
    basenames get set-folder normalize (``is_arcade_set``); never treats NEOGEO_CD
    as AES set folders.
    Returns transforms[] trail (W20-2 parity) plus propose-only / multicart flags,
    captured ``rom_region`` / ``rom_languages`` (BE-DET-4), and ``disc_index``
    (BE-DET-5 — captured before disc parens are stripped).
    """
    raw_label = _basename(raw)
    transforms: list[dict[str, str]] = []
    propose_only = _detect_propose_only(raw_label)
    is_multicart = _detect_multicart(raw_label)
    switch_scene = platform == LibraryPlatform.SWITCH
    arcade_set_platform = platform in ARCADE_SET_FOLDER_PLATFORMS
    is_arcade_set = bool(
        arcade_set_platform and looks_like_arcade_set_basename(raw_label)
    )

    # Capture region/lang from the raw dump label before B17 strips them.
    # Lazy import avoids circular import with rom_language → rom_name_peel.
    from oneirodex.utils.rom_language import parse_rom_language_tags

    lang_tags = parse_rom_language_tags(raw_label) if raw_label else {
        'rom_region': None,
        'rom_languages': None,
        'has_english': None,
        'languages': [],
    }
    disc_index = capture_disc_index(raw_label) if raw_label else None

    empty = {
        'raw': '',
        'cleaned_name': '',
        'transforms': [],
        'propose_only': propose_only,
        'is_multicart': is_multicart,
        'is_arcade_set': False,
        'article_suffix': None,
        'bare_franchise': False,
        'steam_app_id': None,
        'had_vr_suffix': False,
        'rom_region': None,
        'rom_languages': None,
        'has_english': None,
        'languages': [],
        'disc_index': None,
    }
    if not raw_label:
        return empty

    working = raw_label

    after = peel_rom_extensions(working)
    working = _record_transform(transforms, 'B15', working, after, 'strip_extension')

    # BE-DET-7 — SWITCH title-dir: A1 scene/repack brackets before dump B16.
    if switch_scene:
        after = strip_repack_tags(working)
        working = _record_transform(
            transforms, 'A1', working, after, 'scene_repack_brackets',
        )

    after = peel_dump_brackets(working)
    working = _record_transform(transforms, 'B16', working, after, 'dump_brackets')

    after = peel_region_and_lang_parens(working)
    working = _record_transform(transforms, 'B17', working, after, 'region_lang_parens')

    after = peel_rev_and_hardware_parens(working)
    working = _record_transform(transforms, 'B18', working, after, 'rev_hardware_parens')

    after = peel_metadata_parens(working)
    working = _record_transform(transforms, 'B19', working, after, 'metadata_parens')

    # Capture may have run on raw; re-read after prior peels in case only
    # remaining token is the disc paren (already captured from raw).
    if disc_index is None:
        disc_index = capture_disc_index(working)
    after = peel_disc_parens(working)
    working = _record_transform(transforms, 'B19', working, after, 'disc_parens')

    after = peel_remaining_simple_parens(working)
    working = _record_transform(transforms, 'B19', working, after, 'remaining_parens')

    # BE-DET-7 — SWITCH title-dir: A10 unbracketed scene/repack suffixes.
    if switch_scene:
        after = strip_unbracketed_scene_suffix(working)
        working = _record_transform(
            transforms, 'A10', working, after, 'unbracketed_scene_suffix',
        )

    before_b20 = working
    # BE-DET-8 — compact set tokens: underscore→space; keep short set name case
    # for DAT/search honesty (avoid ``mslug`` → ``Mslug`` title-case noise).
    if is_arcade_set:
        spaced = MULTI_SPACE_RE.sub(' ', working.replace('_', ' ')).strip()
        if '_' in (before_b20 or ''):
            working = rom_title_case(spaced)
        else:
            working = spaced
        working = normalize_smart_apostrophes(working)
        working = inject_franchise_apostrophes(working)
        # Always record set-normalize trail (even when string unchanged) so
        # identify / Unmatched can see the arcade-set path.
        if working == before_b20:
            transforms.append({
                'stage': 'B20',
                'before': before_b20,
                'after': working,
                'reason': 'arcade_set_normalize',
            })
        else:
            working = _record_transform(
                transforms, 'B20', before_b20, working, 'arcade_set_normalize',
            )
    else:
        working = MULTI_SPACE_RE.sub(' ', working.replace('_', ' ')).strip()
        working = normalize_smart_apostrophes(working)
        working = inject_franchise_apostrophes(working)
        working = rom_title_case(working)
        working = _record_transform(transforms, 'B20', before_b20, working, 'normalize_title')

    article_suffix = _detect_article_suffix(working)
    # Compact set basenames are fuzzy vs retail catalog titles → propose-only.
    if is_arcade_set:
        propose_only = True

    return {
        'raw': raw_label,
        'cleaned_name': working,
        'transforms': transforms,
        'propose_only': propose_only or is_multicart,
        'is_multicart': is_multicart,
        'is_arcade_set': is_arcade_set,
        'article_suffix': article_suffix,
        'bare_franchise': False,
        'steam_app_id': None,
        'had_vr_suffix': False,
        'rom_region': lang_tags.get('rom_region'),
        'rom_languages': lang_tags.get('rom_languages'),
        'has_english': lang_tags.get('has_english'),
        'languages': list(lang_tags.get('languages') or []),
        'disc_index': disc_index,
    }
