import os
import fnmatch
import re
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game
from sqlalchemy import select
from oneirodex.utils.fandom_alias import expand_fandom_search_variants
from oneirodex.utils.game_name_parse import (
    inject_franchise_apostrophes,
    is_bare_franchise,
    normalize_smart_apostrophes,
    parse_game_label,
)
from oneirodex.utils.rom_name_peel import rom_title_case

LETTER_BUCKET_RE = re.compile(r'^_[a-z0-9#if]$', re.IGNORECASE)


def has_request_context():
    try:
        from flask import has_request_context as check
    except ImportError:
        return False
    return check()


def flash(message):
    from flask import flash as legacy_flash

    return legacy_flash(message)


def _flash_if_request_context(message):
    if has_request_context():
        flash(message)


def should_skip_scan_dir(name, skip_dir_patterns=None, skip_dir_regexes=None):
    """True when folder basename matches a skip-dir glob or regex (case-insensitive)."""
    if not name:
        return False
    if skip_dir_patterns is None:
        from oneirodex.utils.helpers.scan_filters import DEFAULT_SKIP_DIR_GLOBS
        skip_dir_patterns = DEFAULT_SKIP_DIR_GLOBS
    if skip_dir_regexes is None:
        from oneirodex.utils.helpers.scan_filters import DEFAULT_SKIP_DIR_REGEXES
        skip_dir_regexes = DEFAULT_SKIP_DIR_REGEXES
    folded = name.casefold()
    for pattern in skip_dir_patterns:
        if not pattern:
            continue
        if fnmatch.fnmatch(folded, str(pattern).casefold()):
            return True
    for pattern in skip_dir_regexes:
        if not pattern:
            continue
        try:
            if pattern.search(name):
                return True
        except AttributeError:
            if re.search(str(pattern), name, re.IGNORECASE):
                return True
    return False


# Sequel numeral swaps for IGDB search (trailing token only).
_ROMAN_TO_ARABIC = {
    'II': '2', 'III': '3', 'IV': '4', 'V': '5',
    'VI': '6', 'VII': '7', 'VIII': '8', 'IX': '9', 'X': '10',
}
_ARABIC_TO_ROMAN = {v: k for k, v in _ROMAN_TO_ARABIC.items()}
_EDITION_TAIL_TOKENS = frozenset({
    'goty', 'edition', 'remastered', 'remake', 'deluxe', 'definitive',
    'complete', 'collection', 'hd', 'ultimate', 'anniversary', 'enhanced',
})
# Contiguous subtitle phrases → insert ": " immediately before the match (longest first).
_KNOWN_SUBTITLES = (
    "legacy of the void",
    "wings of liberty",
    "heart of the swarm",
    "director's cut",
    "enhanced edition",
    "definitive edition",
    "complete edition",
    "game of the year",
    "royal edition",
    "dark alliance",
    "dark arisen",
    "remastered",
    "remake",
)
# Stage C10 — edition peel tails (longest first). Keep full string; add peeled head.
# Do not peel Remastered/Remake/Edition-alone identity tokens here.
_EDITION_PEEL_PHRASES = (
    "collector's edition",
    "collectors edition",
    "legendary edition",
    "collector's",
    "collectors",
    "collector",
    "legendary",
    "complete",
)
# Franchise heads that use a hyphen (not colon) subtitle separator, e.g.
# "Agatha Christie - Death on the Nile".
_HYPHEN_SUBTITLE_HEADS = (
    "agatha christie",
)
# Franchise heads that take a colon subtitle when at least one token follows
# (e.g. "Assassin's Creed Odyssey" -> "Assassin's Creed: Odyssey").
# Match after A8 apostrophe inject (name-resolution.md Stage C).
_FRANCHISE_COLON_HEADS = (
    "assassin's creed",
    "baldur's gate",
    "grand theft auto",
    "the elder scrolls",
    "far cry",
    "call of duty",
)
# Stage C pack/collection peel tails (longest first).
_PACK_TAIL_PHRASES = (
    "complete collection",
    "dlc pack",
    "collection",
    "pack",
)
_TRAILING_YEAR_RE = re.compile(r'^(?:19|20)\d{2}$')
# Stylized glued titles IGDB often stores without the space (`1000xRESIST`).
_STYLIZED_COMPACT_RE = re.compile(
    r'^(\d+x)\s+(.+)$',
    re.IGNORECASE,
)
# C14 — dotted acronym tokens (S.W.A.R.M. / G.O.T.Y.) → punctuation-light (SWARM).
# ≥2 letter+period pairs; optional final letter+period. Token-local only.
_DOTTED_ACRONYM_TOKEN_RE = re.compile(
    r'(?<![A-Za-z0-9])((?:[A-Za-z]\.){2,}[A-Za-z]\.?)(?![A-Za-z0-9])',
)


def _list_game_dirs(folder_path, scan_depth=1, skip_dir_patterns=None, skip_dir_regexes=None):
    """Return list of (item_name, full_path) game directories honoring scan_depth.

    scan_depth=2 unwraps letter buckets (_a…_z, _#) used by layouts like
    .../_pc/_b/Baldur's Gate Dark Alliance 1. Set library scan_depth to 2 for
    those roots; depth 1 would treat `_b` itself as a game folder.

    Does **not** walk Family→Platform→ROMs (no scan_depth=3). Console trees
    use per-leaf libraries — see docs/strategy/console-gaming-libraries.md.

    skip_dir_patterns — case-insensitive fnmatch globs; matched folders are
    excluded at every listing level (defaults from load_skip_dir_patterns /
    ``dir:`` Admin filters). Defense-in-depth if a lib is pointed too high.
    """
    depth = int(scan_depth or 1)
    patterns = skip_dir_patterns or ()
    results = []
    try:
        entries = sorted(os.listdir(folder_path), key=str.lower)
    except OSError as exc:
        print(f"Error listing '{folder_path}': {exc}")
        return results

    for item in entries:
        full_path = os.path.join(folder_path, item)
        if not os.path.isdir(full_path):
            continue
        if should_skip_scan_dir(item, patterns, skip_dir_regexes):
            continue
        if depth >= 2 and LETTER_BUCKET_RE.match(item):
            try:
                children = sorted(os.listdir(full_path), key=str.lower)
            except OSError:
                continue
            for child in children:
                child_path = os.path.join(full_path, child)
                if not os.path.isdir(child_path):
                    continue
                if should_skip_scan_dir(child, patterns, skip_dir_regexes):
                    continue
                results.append((child, child_path))
        else:
            results.append((item, full_path))
    return results


def get_game_names_from_folder(
    folder_path,
    insensitive_patterns,
    sensitive_patterns,
    scan_depth=1,
    skip_dir_patterns=None,
    skip_dir_regexes=None,
):
    if not os.path.exists(folder_path) or not os.access(folder_path, os.R_OK):
        print(f"Error: The folder '{folder_path}' does not exist or is not readable.")
        _flash_if_request_context(
            f"Error: The folder '{folder_path}' does not exist or is not readable."
        )
        return []
    game_names_with_paths = []
    for item, full_path in _list_game_dirs(
        folder_path, scan_depth=scan_depth, skip_dir_patterns=skip_dir_patterns,
        skip_dir_regexes=skip_dir_regexes,
    ):
        game_name = clean_game_name(item, insensitive_patterns, sensitive_patterns)
        game_names_with_paths.append({'name': game_name, 'full_path': full_path})
    return game_names_with_paths

def get_game_names_from_files(folder_path, extensions, insensitive_patterns, sensitive_patterns):
    if not os.path.exists(folder_path) or not os.access(folder_path, os.R_OK):
        print(f"Error: The path '{folder_path}' does not exist or is not readable.")
        return []
    file_contents = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    # print(f"Files found in folder: {file_contents}")
    game_names_with_paths = []
    for file_name in file_contents:
        print(f"Checking file: {file_name}")
        extension = file_name.split('.')[-1].lower()
        if extension in extensions:
            # print(f"Found supported file: {file_name}")
            # Extract the game name without the extension
            game_name_without_extension = '.'.join(file_name.split('.')[:-1])
            # Clean the game name
            cleaned_game_name = clean_game_name(game_name_without_extension, insensitive_patterns, sensitive_patterns)
            # print(f"Extracted and cleaned game name: {cleaned_game_name}")
            full_path = os.path.join(folder_path, file_name)

            game_names_with_paths.append({'name': cleaned_game_name, 'full_path': full_path, 'file_type': extension})
            # print(f"Added cleaned game name with path: {cleaned_game_name} at {full_path}")

    # BE-DET-5 — cue+bin siblings are one image set (keep .cue, drop companions).
    try:
        from oneirodex.utils.multi_disc import filter_cue_bin_companions

        before = len(game_names_with_paths)
        game_names_with_paths = filter_cue_bin_companions(game_names_with_paths)
        dropped = before - len(game_names_with_paths)
        if dropped:
            print(f"Filtered {dropped} cue companion file(s) from scan listing")
    except Exception as filter_err:  # noqa: BLE001 — scan must continue
        print(f"cue+bin companion filter skipped: {filter_err}")

    # print(f"Game names with paths extracted from files: {game_names_with_paths}")
    return game_names_with_paths


def get_game_name_by_uuid(uuid):
    print(f"Searching for game UUID: {uuid}")
    game = db.session.execute(select(Game).filter_by(uuid=uuid)).scalars().first()
    if game:
        print(f"Game with name {game.name} and UUID {game.uuid} found")
        return game.name
    else:
        print("Game not found")
        return None
    
    
def detect_goty_pattern(filename):
    """
    Detect if filename contains GOTY or G.O.T.Y. patterns.
    Returns tuple: (has_goty, standardized_name)
    """
    # Check for various GOTY patterns (case-insensitive)
    goty_patterns = [
        r'\bg\.o\.t\.y\.?(?=\s|$|\.|-)',    # g.o.t.y or g.o.t.y. (followed by space, end, dot, or hyphen)
        r'(?:^|[^a-zA-Z])goty(?=\s|$|-|\.|_)',  # goty (not preceded by letter, followed by space, end, hyphen, dot, or underscore)
    ]

    for i, pattern in enumerate(goty_patterns):
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            start, end = match.span()
            if i == 1:  # Special handling for the second pattern that includes preceding character
                # Check if match starts with a non-letter character
                if match.start() > 0 and not filename[match.start()].isalpha():
                    # Keep the preceding character
                    cleaned = filename[:start+1] + 'GOTY' + filename[end:]
                else:
                    cleaned = filename[:start] + 'GOTY' + filename[end:]
            else:
                # Standard replacement for first pattern
                cleaned = filename[:start] + 'GOTY' + filename[end:]
            return True, cleaned

    return False, filename


def _dedupe_variants(items):
    """Preserve order; case-insensitive unique non-empty strings."""
    seen = set()
    out = []
    for item in items:
        if not item or not str(item).strip():
            continue
        text = str(item).strip()
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _normalize_apostrophes(name):
    """Map smart quotes to ASCII apostrophe (Stage A8)."""
    return normalize_smart_apostrophes(name)


def _pack_peel_variant(name):
    """
    Stage C pack/collection peel: keep full title first; add peeled head.

    Tails: Complete Collection, Collection, DLC Pack, Pack — peel when ≥1
    head token remains (exact pack titles stay as earlier variants).
    """
    if not name:
        return None
    lower = name.casefold()
    for phrase in _PACK_TAIL_PHRASES:
        suffix = ' ' + phrase
        if not lower.endswith(suffix):
            continue
        head = name[: -len(suffix)].strip(' -_')
        if head and len(head.split()) >= 1:
            return head
    return None


def _edition_peel_variant(name):
    """
    Stage C10 — keep full title; add head without trailing Complete/Collector/
    Legendary (and * Edition forms) when ≥2 head tokens remain.
    """
    if not name:
        return None
    lower = name.casefold()
    for phrase in _EDITION_PEEL_PHRASES:
        suffix = ' ' + phrase
        if not lower.endswith(suffix):
            continue
        head = name[: -len(suffix)].strip(' -_')
        if head and len(head.split()) >= 2:
            return head
    return None


def _strip_trailing_bare_one(name):
    """
    Strip a trailing bare edition number '1' when ≥3 non-empty tokens precede it
    and the preceding token is non-numeric.

    Folder labels often append '1' for the first game in a series
    (e.g. Baldur's Gate Dark Alliance 1 → Baldur's Gate Dark Alliance).
    """
    words = name.split()
    if len(words) < 4 or words[-1] != '1':
        return None
    if any(ch.isdigit() for ch in words[-2]):
        return None
    return ' '.join(words[:-1])


def _known_subtitle_colon(name):
    """Insert ': ' before a known contiguous subtitle phrase when absent."""
    if ':' in name:
        return None
    lower = name.casefold()
    for phrase in _KNOWN_SUBTITLES:
        idx = lower.find(phrase)
        if idx <= 0:
            continue
        # Require a word boundary before the phrase
        if name[idx - 1] not in ' \t-_':
            continue
        head = name[:idx].rstrip(' -_')
        tail = name[idx:].lstrip(' -_')
        if not head or not tail:
            continue
        return f"{head}: {tail}"
    return None


def _colon_subtitle_variants(name):
    """
    Stage C5 heuristic colon (≥4 tokens only).

    Prefer a 2-word trailing subtitle (`tokens[:-2]: tokens[-2:]`), e.g.
    Baldur's Gate: Dark Alliance. Also emit a 1-word trailing subtitle form
    for the same ≥4-token titles. Three-word titles (e.g. A Fishermans Tale)
    must not invent a colon — use known-subtitle / franchise-head paths instead.
    """
    words = name.split()
    if len(words) < 4:
        return []
    if words[-1].isdigit() or words[-1].lower() in _EDITION_TAIL_TOKENS:
        return []
    if ':' in name:
        return []

    return [
        f"{' '.join(words[:-2])}: {' '.join(words[-2:])}",
        f"{' '.join(words[:-1])}: {words[-1]}",
    ]


def _sequel_numeral_variants(name):
    """Swap trailing Arabic ↔ Roman sequel tokens (2/II, 3/III, …)."""
    words = name.split()
    if len(words) < 2:
        return []
    last = words[-1]
    head = ' '.join(words[:-1])
    upper = last.upper()
    variants = []
    if upper in _ROMAN_TO_ARABIC:
        variants.append(f"{head} {_ROMAN_TO_ARABIC[upper]}")
    if last.isdigit() and last in _ARABIC_TO_ROMAN:
        variants.append(f"{head} {_ARABIC_TO_ROMAN[last]}")
    return variants


def _hyphen_subtitle_variants(name):
    """
    Hyphen ↔ space subtitle variant.

    If a ' - ' subtitle separator is present, add a despaced copy (matches
    existing Stage C7 heuristic). Otherwise, if the name starts with a known
    hyphen-subtitle franchise head (e.g. "Agatha Christie"), insert one.
    """
    if ' - ' in name:
        despaced = re.sub(r'\s+', ' ', name.replace(' - ', ' ')).strip()
        return [despaced] if despaced and despaced != name else []

    lower = name.casefold()
    for head in _HYPHEN_SUBTITLE_HEADS:
        prefix = head + ' '
        if lower.startswith(prefix):
            tail = name[len(head):].strip(' -')
            if tail:
                return [f"{name[:len(head)]} - {tail}"]
            break
    return []


def _franchise_head_colon_variant(name):
    """Insert ': ' after a known franchise head when ≥1 token follows and no colon exists."""
    if ':' in name:
        return None
    lower = name.casefold()
    for head in _FRANCHISE_COLON_HEADS:
        prefix = head + ' '
        if lower.startswith(prefix):
            tail = name[len(head):].strip()
            if tail:
                return f"{name[:len(head)]}: {tail}"
            break
    return None


def _drop_trailing_year_variant(name):
    """Drop a trailing standalone 4-digit year (1900s/2000s) as a search variant."""
    words = name.split()
    if len(words) < 2:
        return None
    if not _TRAILING_YEAR_RE.match(words[-1]):
        return None
    return ' '.join(words[:-1])


def _deapostrophe_variant(name):
    """One search copy with ASCII apostrophes removed."""
    if "'" not in name:
        return None
    cleaned = re.sub(r"\s+", " ", name.replace("'", "")).strip()
    return cleaned if cleaned and cleaned != name else None


def _article_reorder_variant(name: str) -> str | None:
    """C12 — reorder trailing article suffix (`, The` / `, A` / `, An`).

    Also handles article before a hyphen subtitle:
    ``Legend of Zelda, The - Ocarina of Time`` → ``The Legend of Zelda - Ocarina of Time``.
    """
    if not name:
        return None
    for suffix in (', The', ', A', ', An'):
        if name.endswith(suffix):
            article = suffix[2:].strip()
            head = name[: -len(suffix)].strip()
            if head:
                return rom_title_case(f'{article} {head}')
        # Mid-title article before `` - `` subtitle (console No-Intro style).
        marker = f'{suffix} - '
        idx = name.find(marker)
        if idx > 0:
            article = suffix[2:].strip()
            head = name[:idx].strip()
            rest = name[idx + len(marker) :].strip()
            if head and rest:
                return rom_title_case(f'{article} {head} - {rest}')
    return None


def _stylized_compact_variants(name: str) -> list[str]:
    """
    W21-BE-3 — glued search copies for stylized `Nx Word` labels.

    IGDB often stores `1000xRESIST` while folders keep `1000x Resist`. Scoring
    already treats them as equal after alnum normalize; search still needs the
    compact query or the API may return nothing.
    """
    if not name:
        return []
    match = _STYLIZED_COMPACT_RE.match(name.strip())
    if not match:
        return []
    prefix, rest = match.group(1), match.group(2).strip()
    if not rest:
        return []
    # Preserve folder casing on the digit+x prefix; drop spaces in the tail.
    compact = prefix + re.sub(r'\s+', '', rest)
    out = [compact]
    upper_tail = prefix + re.sub(r'\s+', '', rest).upper()
    if upper_tail.casefold() != compact.casefold():
        out.append(upper_tail)
    return out


def _punctuation_light_variants(name: str) -> list[str]:
    """
    C14 / W22-M2 — collapse dotted acronym tokens only.

    ``Armorines - Project S.W.A.R.M.`` → ``Armorines - Project SWARM``.
    Additive search variant; never replaces the cleaned display primary.
    Keeps hyphens, apostrophes, commas, and spaces elsewhere.
    """
    if not name or not str(name).strip():
        return []
    text = str(name).strip()
    if not _DOTTED_ACRONYM_TOKEN_RE.search(text):
        return []

    def _collapse(match: re.Match) -> str:
        return match.group(1).replace('.', '')

    light = _DOTTED_ACRONYM_TOKEN_RE.sub(_collapse, text)
    light = re.sub(r'\s+', ' ', light).strip()
    if not light or light.casefold() == text.casefold():
        return []
    return [light]


def generate_goty_variants(base_name, *, policy=None):
    """
    Generate ordered IGDB search variants for a folder/game label.

    Stage C (docs/strategy/name-resolution.md): cleaned as-is (post A8 inject) →
    article reorder (C12) → stylized compact `Nx Word` (C13 / W21-BE-3) →
    punctuation-light dotted acronyms (C14 / W22-M2) →
    franchise/known colon → drop bare 1 → sequel ↔ Roman → heuristic colon (≥4) →
    year drop → pack/collection peel → edition peel (C10) → de-apostrophe →
    hyphen/GOTY → BE-DET-9 fandom soft alias / regional / remaster variants
    (propose-first at identify). C11 bare franchise → single variant only
    (plus soft fandom search copies when registered).

    policy (optional dict from resolve_scan_match_policy): toggles
    enable_year_drop_variant / enable_pack_peel_variant /
    enable_edition_peel_variant / enable_sequel_numeral_variant (default True).
    """
    if not base_name or not str(base_name).strip():
        return []

    toggles = policy if isinstance(policy, dict) else {}
    enable_year = toggles.get('enable_year_drop_variant', True)
    enable_pack = toggles.get('enable_pack_peel_variant', True)
    enable_edition = toggles.get('enable_edition_peel_variant', True)
    enable_sequel = toggles.get('enable_sequel_numeral_variant', True)

    # A8 normalize + franchise inject before colon-head match.
    base_name = inject_franchise_apostrophes(
        _normalize_apostrophes(str(base_name).strip())
    )
    # C11 — bare franchise / ambiguous one-token: do not invent sequel/edition variants.
    # BE-DET-9: still allow soft fandom search copies (identify stays propose-first).
    if is_bare_franchise(base_name):
        bare = [base_name]
        bare.extend(expand_fandom_search_variants(base_name))
        return _dedupe_variants(bare)

    variants = [base_name]

    article_variant = _article_reorder_variant(base_name)
    if article_variant:
        variants.append(article_variant)

    # Stylized compact (`1000x Resist` → `1000xResist` / `1000xRESIST`) for IGDB search.
    variants.extend(_stylized_compact_variants(base_name))

    # C14 — dotted acronym collapse (`S.W.A.R.M.` → `SWARM`); additive only.
    variants.extend(_punctuation_light_variants(base_name))
    article_light = _punctuation_light_variants(article_variant) if article_variant else []
    for light in article_light:
        if light not in variants:
            variants.append(light)

    if 'GOTY' in base_name:
        variants.append(base_name.replace('GOTY', 'G.O.T.Y.'))
        no_goty_variant = re.sub(r'\s+', ' ', base_name.replace('GOTY', '')).strip()
        if no_goty_variant:
            variants.append(no_goty_variant)

    # Known subtitle / franchise colon (may still include trailing bare 1).
    known_on_base = _known_subtitle_colon(base_name)
    if known_on_base:
        variants.append(known_on_base)

    franchise_on_base = _franchise_head_colon_variant(base_name)
    if franchise_on_base:
        variants.append(franchise_on_base)

    stripped_one = _strip_trailing_bare_one(base_name)
    if stripped_one:
        variants.append(stripped_one)
        known_stripped = _known_subtitle_colon(stripped_one)
        if known_stripped:
            variants.append(known_stripped)
        franchise_stripped = _franchise_head_colon_variant(stripped_one)
        if franchise_stripped:
            variants.append(franchise_stripped)

    # Heuristic colon on title core when known/franchise list did not produce it.
    # Never invent colon for 3-token titles (A Fishermans Tale).
    core = stripped_one or base_name
    if not _known_subtitle_colon(core) and not _franchise_head_colon_variant(core):
        variants.extend(_colon_subtitle_variants(core))

    if enable_sequel:
        for seed in (base_name, stripped_one) if stripped_one else (base_name,):
            variants.extend(_sequel_numeral_variants(seed))

    # Trailing 4-digit year dropped as an additional search variant.
    if enable_year:
        year_dropped = _drop_trailing_year_variant(base_name)
        if year_dropped:
            variants.append(year_dropped)

    # Pack / collection peel — keep full string earlier; add peeled head.
    if enable_pack:
        pack_peeled = _pack_peel_variant(base_name)
        if pack_peeled:
            variants.append(pack_peeled)

    # C10 edition peel — keep full; add Complete/Collector/Legendary head.
    if enable_edition:
        edition_peeled = _edition_peel_variant(base_name)
        if edition_peeled:
            variants.append(edition_peeled)

    # Prefer de-apostrophe of the best colon form (without trailing bare 1).
    colon_hit = next(
        (v for v in variants if ': ' in v and not v.rstrip().endswith(' 1')),
        None,
    )
    deap = _deapostrophe_variant(colon_hit or core)
    if deap:
        variants.append(deap)

    # Hyphen ↔ space / Agatha-style subtitle (Stage C row 9).
    variants.extend(_hyphen_subtitle_variants(base_name))

    # BE-DET-9 — soft alias / remaster / regional EN↔JP search copies (propose-first).
    variants.extend(expand_fandom_search_variants(base_name))

    return _dedupe_variants(variants)


def clean_game_name(filename, insensitive_patterns, sensitive_patterns):
    # print(f"Original filename: {filename}")

    # Strip common scene/repack bracket tags and trailing Steam App IDs first
    parsed = parse_game_label(filename)
    filename = parsed['cleaned_name'] or filename

    # Check and remove 'setup' at the start, case-insensitive
    if filename.lower().startswith('setup'):
        filename = filename[len('setup'):].lstrip("_").lstrip("-").lstrip()
        # print(f"After removing 'setup': {filename}")

    # Detect and preserve GOTY patterns early, before dot processing
    has_goty, filename = detect_goty_pattern(filename)

    # First handle version numbers and known patterns that should be removed
    filename = re.sub(r'v\d+(\.\d+)*', '', filename)  # Remove version numbers like v1.0.3
    filename = re.sub(r'(?:^|_|\s)\d+(\.\d+){2,}(?=_|\s|$)', '', filename)  # Remove complex version numbers like 1.9.23494.3
    filename = re.sub(r'\b\d+(\.\d+)+\b', '', filename)  # Remove standalone version numbers like 1.0.3
    filename = re.sub(r'_\(\d+\)_', '_', filename)  # Replace build numbers in parentheses like _(51906)_ with single underscore
    filename = re.sub(r'_?\(\d+\)_?', '', filename)  # Remove any remaining build numbers in parentheses

    # Handle dots between single letters (like A.Tale -> A Tale), but preserve GOTY if present
    if not has_goty or 'GOTY' not in filename:
        filename = re.sub(r'(?<=\b[A-Z])\.(?=[A-Z]\b|\s|$)', ' ', filename)
    else:
        # More careful dot handling when GOTY is present
        filename = re.sub(r'(?<=\b[A-Z])\.(?=[A-Z]\b|\s|$)(?!.*GOTY)', ' ', filename)

    # Replace remaining dots and underscores with spaces, but preserve GOTY
    if has_goty and 'GOTY' in filename:
        # Temporarily replace GOTY to protect it from dot processing
        filename = filename.replace('GOTY', 'GOTYPLACEHOLDER')
        filename = re.sub(r'(?<!^)(?<![\d])\.|_', ' ', filename)
        filename = filename.replace('GOTYPLACEHOLDER', 'GOTY')
    else:
        filename = re.sub(r'(?<!^)(?<![\d])\.|_', ' ', filename)

    # Define a regex pattern for version numbers
    version_pattern = r'\bv?\d+(\.\d+){1,3}'

    # Remove version numbers
    filename = re.sub(version_pattern, '', filename)

    # Remove known release group patterns
    for pattern in insensitive_patterns:
        escaped_pattern = re.escape(pattern)
        # Use word boundary only if pattern starts/ends with word characters
        if pattern[0].isalnum() and pattern[-1].isalnum():
            filename = re.sub(f"\\b{escaped_pattern}\\b", '', filename, flags=re.IGNORECASE)
        else:
            filename = re.sub(escaped_pattern, '', filename, flags=re.IGNORECASE)

    for pattern, is_case_sensitive in sensitive_patterns:
        escaped_pattern = re.escape(pattern)
        if is_case_sensitive:
            filename = re.sub(f"\\b{escaped_pattern}\\b", '', filename)
        else:
            filename = re.sub(f"\\b{escaped_pattern}\\b", '', filename, flags=re.IGNORECASE)

    # Handle cases with numerals and versions
    filename = re.sub(r'\b([IVXLCDM]+|[0-9]+)(?:[^\w]|$)', r' \1 ', filename)

    # Cleanup for versions, DLCs, etc.
    filename = re.sub(r'Build\.\d+', '', filename)
    filename = re.sub(r'(\+|\-)\d+DLCs?', '', filename, flags=re.IGNORECASE)
    # Keep Remastered/Remake/Edition for IGDB disambiguation; strip only junk tokens
    filename = re.sub(r'Repack|Proper|Dodi', '', filename, flags=re.IGNORECASE)

    # Remove trailing numbers enclosed in brackets
    filename = re.sub(r'\(\d+\)$', '', filename).strip()

    # Smart cleanup of trailing numbers - keep only one meaningful number at the end
    # Split by spaces and work backwards from the end
    words = filename.split()
    if len(words) > 1:
        # Find trailing numeric/garbage words
        trailing_numbers = []
        clean_words = []

        for word in reversed(words):
            # Check if word is purely numeric or obvious garbage
            if (word.isdigit() and len(word) <= 2) or word.lower() in ['win', 'gog', 'steam']:
                trailing_numbers.append(word)
            else:
                # Keep this word and stop looking
                clean_words = words[:len(words) - len(trailing_numbers)]
                break

        # If we found trailing garbage words, clean them up
        if trailing_numbers:
            # Look for a valid game sequel number (typically 1-20)
            valid_sequel = None
            for num_word in reversed(trailing_numbers):
                if num_word.isdigit() and 1 <= int(num_word) <= 20:
                    valid_sequel = num_word
                    break

            # Rebuild filename with cleaned words plus optional valid sequel number
            if valid_sequel:
                filename = ' '.join(clean_words + [valid_sequel])
            else:
                filename = ' '.join(clean_words)

    # Normalize whitespace and re-title
    filename = re.sub(r'\s+', ' ', filename).strip()
    cleaned_name = ' '.join(filename.split()).title()

    # Preserve GOTY in uppercase after title case conversion
    if has_goty:
        cleaned_name = re.sub(r'\bGoty\b', 'GOTY', cleaned_name)

    # print(f"Final cleaned name: {cleaned_name}")

    return cleaned_name
