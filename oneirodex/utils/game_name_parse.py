"""
Parse raw game folder/file labels into cleaned search names and Steam App ID hints.

Implements Stage A0–A14 from docs/strategy/name-resolution.md so identify can
rely on parse_game_label alone (not clean_game_name) for strip quality.
"""
import os
import re

# A1 — generic scene/repack bracket tags: [Repack], [HV Repack], [… Repack], [… HV Repack].
# Alias tokens stay in this regex only (not public docs).
_BRACKET_TAG_RE = re.compile(
    r'\[\s*(?:[^\]]*?[^\s\]]\s+)?(?:HV\s+)?Repack\s*\]',
    re.IGNORECASE,
)
# A2 — version junk like [1 0 4 1] or [1.0.4.1] in brackets.
_VERSION_BRACKET_RE = re.compile(
    r'\[\s*\d+(?:[\s._]+\d+)+\s*\]',
    re.IGNORECASE,
)
# A3 — trailing "(Build …)" / "(build …)" — not a Steam App ID.
_BUILD_PAREN_RE = re.compile(r'\s*\(\s*build\b[^)]*\)\s*$', re.IGNORECASE)
# A4 — VR / mod tails (order: VR MOD… → vendor-mod → spaced VR → glued VR).
_VR_MOD_TAIL_RE = re.compile(r'\s*-?\s*\bVR\s+MOD\b.*$', re.IGNORECASE)
_MOTHERVR_TAIL_RE = re.compile(r'\s*-?\s*\bMotherVR\b.*$', re.IGNORECASE)
_TRAILING_VR_RE = re.compile(r'\s+VR\s*$', re.IGNORECASE)
# Glued product names like 3DSenVR (no whitespace before VR).
_GLUED_TRAILING_VR_RE = re.compile(r'(?<=[A-Za-z0-9])VR\s*$', re.IGNORECASE)
# A5 — trailing (digits) Steam App ID (4–7 digits).
_STEAM_ID_RE = re.compile(r'\(\s*(\d{4,7})\s*\)\s*$')
# A6 — trailing spaced/dotted version tails (v0 4, v1.188, v1.1.0a); not mid-title "v".
_SPACED_VERSION_TAIL_RE = re.compile(
    r'\s+\bv\d+(?:[.\s_]\d+)+[a-zA-Z]?(?:\s+P2P?)?\s*$',
    re.IGNORECASE,
)
# A6 — trailing dotted x.y.z (no ``v``) e.g. Satellite Reign 1.13.06.
# Three+ numeric segments so sequels like "Quake 2" / years stay put.
# Do not peel the right-hand side of an A12 update range (`update 1.24.01 - 1.25.01`).
_DOTTED_VERSION_TAIL_RE = re.compile(
    r'\s+(?<!- )\d+\.\d+\.\d+(?:\.\d+)*\s*$',
)
# A6 — trailing Early Access / EA tokens only.
_EARLY_ACCESS_TAIL_RE = re.compile(
    r'\s+\b(?:Early\s+Access|EA)\s*$',
    re.IGNORECASE,
)
# A9 — (Incl Update…) / (Incl. Update N) parentheticals + platform parens.
_INCL_UPDATE_PAREN_RE = re.compile(
    r'\s*\(\s*Incl\.?\s+Update(?:\s+\d+)?\s*\)\s*$',
    re.IGNORECASE,
)
_PLATFORM_PAREN_RE = re.compile(
    r'\s*\(\s*oculus\s*\)\s*$',
    re.IGNORECASE,
)
# A10 — unbracketed trailing scene/repack suffixes (code-only aliases; not public docs).
# Household / generic shapes only — public docs say "scene/repack tags", never this list.
_UNBRACKETED_SCENE_ALIASES = frozenset({
    'scenegrp',
    'scene',
    'repack',
    'proper',
    'internal',
    'rune',
    'group',
    # Hyphen-glued household suffixes (e.g. BeachHead-<alias>) — aliases in code only.
    'skidrow',
    'codex',
    'cpy',
    'plaza',
    'reloaded',
    'hoodlum',
    'razor1911',
    'empress',
    'flt',
    'dodi',
    'goldberg',
})
_UNBRACKETED_SCENE_TAIL_RE = re.compile(
    r'(?:\s+-\s*|\s+|-)('
    + '|'.join(re.escape(a) for a in sorted(_UNBRACKETED_SCENE_ALIASES, key=len, reverse=True))
    + r')\s*$',
    re.IGNORECASE,
)
# A11 — date-stamps YYYYMMDD / YYYYMMDDnn and compact single-block V########.
_DATE_STAMP_TAIL_RE = re.compile(
    r'\s+(?:(?:19|20)\d{6,10}|[Vv]\d{6,12})\s*$',
)
# A12 — Update / Build prose tails + version ranges.
_UPDATE_RANGE_TAIL_RE = re.compile(
    r'\s+\bupdate\s+\d+(?:[.\s_]\d+)*(?:\s*-\s*\d+(?:[.\s_]\d+)*)?\s*$',
    re.IGNORECASE,
)
_UPDATE_VERSION_TAIL_RE = re.compile(
    r'\s+\bUpdate\s+v?\d+(?:[.\s_]\d+)*[a-zA-Z]?\s*$',
    re.IGNORECASE,
)
# After A6 peels `v…`, a bare trailing Update may remain (Update v1.2 → Update).
_BARE_UPDATE_TAIL_RE = re.compile(
    r'\s+\bUpdate\s*$',
    re.IGNORECASE,
)
_BARE_BUILD_TAIL_RE = re.compile(
    r'\s+\bBuild\s+\d+[a-zA-Z]?\s*$',
    re.IGNORECASE,
)
# W22-M5 — folder basename that is itself an update package (never a game title).
_BARE_UPDATE_PACKAGE_NAMES = frozenset({'update', 'updates'})
# Trailing `` - UPDATE`` / `` UPDATE`` when ≥2 head tokens remain after peel.
_TRAILING_UPDATE_SEP_RE = re.compile(
    r'(?:\s+-\s*|\s+)\bUPDATES?\s*$',
    re.IGNORECASE,
)
# A13 — strip pure add-on / HV junk from cleaned display (edition peels → Stage C10).
_ADDON_JUNK_TAIL_RE = re.compile(
    r'\s+(?:4K\s+Videos?\s+Add-?ons?(?:\s+Repack)?|\bHV)\s*$',
    re.IGNORECASE,
)
# A8 — smart quotes + household backtick typos → ASCII apostrophe.
_SMART_APOSTROPHE_RE = re.compile(r"[’‘ʼ´`]")
# A8 — franchise heads missing apostrophe on disk (inject before Stage C colon match).
_FRANCHISE_APOSTROPHE_INJECT = (
    (re.compile(r'^Assassins(\s+Creed\b)', re.IGNORECASE), "Assassin's"),
    (re.compile(r'^Baldurs(\s+Gate\b)', re.IGNORECASE), "Baldur's"),
    (re.compile(r'^A Fishermans(\s+Tale\b)', re.IGNORECASE), "A Fisherman's"),
)
# C11 — bare franchise / one-token ambiguous labels → propose only (no auto-import).
_BARE_FRANCHISE_LABELS = frozenset({
    'final fantasy',
    'battletoads',
    'keeper',
})
_BARE_FRANCHISE_HEADS = frozenset({
    "assassin's creed",
    "baldur's gate",
    'grand theft auto',
    'the elder scrolls',
    'far cry',
    'call of duty',
    'final fantasy',
})
# Tiny stylized aliases after A7.
_ALIAS_MAP = {
    'adr1ft': 'Adrift',
}


def _basename_only(raw: str) -> str:
    """A0 — trim and drop path segments (works for /, \\, and UNC-style labels)."""
    text = (raw or '').strip()
    if not text:
        return ''
    # Normalize separators so basename works even when host OS differs from label shape.
    unified = text.replace('\\', '/')
    return os.path.basename(unified.rstrip('/')) or unified


def strip_repack_tags(raw: str) -> str:
    """A1 — remove generic scene/repack bracket tags from a label."""
    if not raw:
        return ''
    return _BRACKET_TAG_RE.sub('', raw).strip()


def strip_version_brackets(raw: str) -> str:
    """A2 — remove bracketed multi-part version junk (e.g. [1 0 4 1])."""
    if not raw:
        return ''
    return _VERSION_BRACKET_RE.sub('', raw).strip()


def strip_build_tail(raw: str) -> str:
    """A3 — remove a trailing '(Build ...)' / '(build ...)' parenthetical."""
    if not raw:
        return ''
    return _BUILD_PAREN_RE.sub('', raw).strip()


def strip_vr_noise_tail(raw: str) -> str:
    """
    A4 / A14 — remove trailing VR/mod noise: 'VR MOD …', vendor-mod tails
    ('MotherVR …'), spaced trailing 'VR', then glued trailing 'VR'
    (e.g. 3DSenVR → 3DSen). Does not strip mid-token VR (7VR Wonders).
    """
    if not raw:
        return ''
    working = _VR_MOD_TAIL_RE.sub('', raw)
    working = _MOTHERVR_TAIL_RE.sub('', working)
    working = _TRAILING_VR_RE.sub('', working)
    working = _GLUED_TRAILING_VR_RE.sub('', working)
    return working.strip()


def detect_vr_suffix(raw: str) -> bool:
    """True when the label has a peelable trailing VR / VR MOD / glued VR suffix."""
    if not raw:
        return False
    text = raw.strip()
    return bool(
        _VR_MOD_TAIL_RE.search(text)
        or _MOTHERVR_TAIL_RE.search(text)
        or _TRAILING_VR_RE.search(text)
        or _GLUED_TRAILING_VR_RE.search(text)
    )


def strip_version_access_tails(raw: str) -> str:
    """A6 — strip trailing spaced/dotted v… versions, x.y.z tails, and Early Access / EA."""
    if not raw:
        return ''
    working = raw
    # Repeat lightly: "Title v0 4 Early Access" → strip version then EA.
    for _ in range(3):
        next_pass = _SPACED_VERSION_TAIL_RE.sub('', working).strip()
        next_pass = _DOTTED_VERSION_TAIL_RE.sub('', next_pass).strip()
        next_pass = _EARLY_ACCESS_TAIL_RE.sub('', next_pass).strip()
        if next_pass == working:
            break
        working = next_pass
    return working


def strip_incl_update_tails(raw: str) -> str:
    """A9 — strip (Incl Update…) parentheticals and (oculus)-style platform parens."""
    if not raw:
        return ''
    working = _INCL_UPDATE_PAREN_RE.sub('', raw).strip()
    working = _PLATFORM_PAREN_RE.sub('', working).strip()
    return working


def strip_unbracketed_scene_suffix(raw: str, *, peel_profile: str = 'conservative') -> str:
    """
    A10 — strip trailing unbracketed scene/repack suffixes (hyphen or space).

    Hyphen forms (BeachHead-ALIAS / Title - ALIAS) allow a single head token.
    Space-only forms require ≥2 head tokens (avoids over-peel on generic aliases)
    unless peel_profile is 'aggressive' (min 1 token).
    Alias list is code-only.
    """
    if not raw:
        return ''
    match = _UNBRACKETED_SCENE_TAIL_RE.search(raw)
    if not match:
        return raw.strip()
    head = raw[: match.start()].strip(' -_')
    if not head:
        return raw.strip()
    sep = raw[match.start() : match.start(1)]
    profile = (peel_profile or 'conservative').strip().lower()
    if profile == 'aggressive':
        min_tokens = 1
    else:
        min_tokens = 1 if '-' in sep else 2
    if len(head.split()) < min_tokens:
        return raw.strip()
    return head


def strip_edition_display_tails(raw: str) -> str:
    """
    Aggressive peel only — strip Complete/Collector/Legendary from cleaned display
    when ≥2 head tokens remain (conservative leaves these for Stage C10 variants).
    """
    if not raw:
        return ''
    lower = raw.casefold()
    for phrase in (
        "collector's edition",
        "collectors edition",
        "legendary edition",
        "collector's",
        "collectors",
        "collector",
        "legendary",
        "complete",
    ):
        suffix = ' ' + phrase
        if not lower.endswith(suffix):
            continue
        head = raw[: -len(suffix)].strip(' -_')
        if head and len(head.split()) >= 2:
            return head
    return raw.strip()


def strip_date_stamp_tails(raw: str) -> str:
    """A11 — strip trailing YYYYMMDD(nn) or compact V######## blocks."""
    if not raw:
        return ''
    return _DATE_STAMP_TAIL_RE.sub('', raw).strip()


def strip_update_build_prose_tails(raw: str) -> str:
    """A12 — strip Update vX / update ranges / bare trailing Build N / bare Update."""
    if not raw:
        return ''
    working = raw
    for _ in range(3):
        next_pass = _UPDATE_RANGE_TAIL_RE.sub('', working).strip()
        next_pass = _UPDATE_VERSION_TAIL_RE.sub('', next_pass).strip()
        next_pass = _BARE_BUILD_TAIL_RE.sub('', next_pass).strip()
        next_pass = _BARE_UPDATE_TAIL_RE.sub('', next_pass).strip()
        if next_pass == working:
            break
        working = next_pass
    return working


def strip_addon_junk_tails(raw: str) -> str:
    """A13 — strip pure add-on / bare HV junk (edition peels stay for Stage C10)."""
    if not raw:
        return ''
    return _ADDON_JUNK_TAIL_RE.sub('', raw).strip()


def normalize_smart_apostrophes(raw: str) -> str:
    """A8 — map smart quotes to ASCII apostrophe."""
    if not raw:
        return ''
    return _SMART_APOSTROPHE_RE.sub("'", raw)


def inject_franchise_apostrophes(raw: str) -> str:
    """
    A8 — inject missing apostrophes on known franchise heads
    (Assassins Creed → Assassin's Creed) so Stage C colon heads can match.
    """
    if not raw:
        return ''
    working = raw
    for pattern, head in _FRANCHISE_APOSTROPHE_INJECT:
        match = pattern.match(working)
        if match:
            working = head + working[match.start(1) :]
            break
    return working


def is_bare_franchise(name: str) -> bool:
    """
    C11 — True when the cleaned label is a known bare franchise / ambiguous
    one-token head with no subtitle (propose / manual only; no auto-import).
    """
    if not name or not str(name).strip():
        return False
    folded = normalize_smart_apostrophes(str(name).strip()).casefold()
    folded = inject_franchise_apostrophes(folded).casefold()
    if folded in _BARE_FRANCHISE_LABELS:
        return True
    if folded in _BARE_FRANCHISE_HEADS:
        return True
    # Exact franchise colon-head with zero subtitle tokens.
    tokens = folded.split()
    if len(tokens) <= 2 and folded in _BARE_FRANCHISE_HEADS:
        return True
    return False


def _title_case_tokens(working: str) -> str:
    """A7 casing: title-case all-lowercase dumps; keep ALLCAPS+digit tokens."""
    parts = []
    for word in working.split(' '):
        if not word:
            continue
        if word.isupper() or any(ch.isdigit() for ch in word):
            parts.append(word)
        elif word.lower() == word:
            parts.append(word[:1].upper() + word[1:])
        else:
            parts.append(word)
    return ' '.join(parts)


def is_bare_update_package(name: str | None) -> bool:
    """True when the folder basename is literally UPDATE / Updates / updates."""
    if not name or not isinstance(name, str):
        return False
    folded = _basename_only(name).casefold().strip()
    return folded in _BARE_UPDATE_PACKAGE_NAMES


# A folder that is itself a patch/update package for a game that lives elsewhere:
# "Beast of Reincarnation update 1.0.7.0 - 1.0.8.0", "Grim Dawn Update_from_v1.3.0.0
# _to_v1.3.0.3-ElAmigos", "Alan Wake 2 update 1.2.8 - 1.2.10", "... Unofficial
# Patch". Not a full release that merely *includes* updates ("(Incl. Update 2)"),
# which is a game and imports normally.
_INCLUDES_UPDATE_RE = re.compile(r'\b(?:incl(?:ude[sd]?|uding)?\.?|with)\s+updates?\b', re.IGNORECASE)
_PATCH_PACKAGE_RE = re.compile(
    r'\bupdate\b\s*(?:from\s+)?v?\d'
    r'|\bunofficial\s+patch\b'
    r'|\bhotfix\b'
    r'|\bpatch\s+v?\d',
    re.IGNORECASE,
)


def looks_like_patch_package(raw: str | None) -> bool:
    """True when the folder name is a standalone update/patch package.

    Such a folder must never become a Game record: it is an update *for* a game,
    and importing it creates the game from the update folder -- under the wrong
    title when the update is for a sequel ("Alan Wake 2 update ..." was imported
    as Alan Wake), and it leaves the real game folder flagged as a duplicate of
    its own update.
    """
    if not raw or not isinstance(raw, str):
        return False
    label = _basename_only(raw).replace('_', ' ')
    # "(Incl. Update 5)" describes a full release that bundles updates.
    label = _INCLUDES_UPDATE_RE.sub('', label)
    return bool(_PATCH_PACKAGE_RE.search(label))


def detect_update_packaging(
    raw: str | None,
    *,
    cleaned_name: str | None = None,
    transforms: list | None = None,
) -> dict:
    """
    W22-M5 — classify update/patch packaging on a folder label.

    Returns:
        is_bare_update_package — never auto-import; never map to Soft title.
        update_folder_hint — Incl Update / Update prose / trailing UPDATE peeled.
        match_reason — ``update_package_folder`` or ``update_packaging_hint`` or None.
    """
    empty = {
        'is_bare_update_package': False,
        'update_folder_hint': False,
        'match_reason': None,
    }
    if not raw or not isinstance(raw, str):
        return empty

    basename = _basename_only(raw)
    if is_bare_update_package(basename):
        return {
            'is_bare_update_package': True,
            'update_folder_hint': True,
            'match_reason': 'update_package_folder',
        }

    cleaned = (cleaned_name if cleaned_name is not None else '').strip()
    # Peel emptied the title down to Update / empty → treat as bare package.
    if not cleaned or cleaned.casefold() in _BARE_UPDATE_PACKAGE_NAMES:
        if _TRAILING_UPDATE_SEP_RE.search(basename) or 'update' in basename.casefold():
            return {
                'is_bare_update_package': True,
                'update_folder_hint': True,
                'match_reason': 'update_package_folder',
            }

    hint = False
    for step in transforms or ():
        if not isinstance(step, dict):
            continue
        stage = (step.get('stage') or '').strip()
        reason = (step.get('reason') or '').strip()
        if stage == 'A9' and reason == 'incl_update_paren':
            hint = True
            break
        if stage == 'A12' and reason == 'update_build_prose':
            hint = True
            break

    if not hint and _TRAILING_UPDATE_SEP_RE.search(basename):
        # Title - UPDATE / trailing UPDATE with a real head (≥2 tokens preferred).
        head = _TRAILING_UPDATE_SEP_RE.sub('', basename).strip(' -_')
        if head and len(head.split()) >= 1:
            hint = True

    if hint:
        return {
            'is_bare_update_package': False,
            'update_folder_hint': True,
            'match_reason': 'update_packaging_hint',
        }
    return empty


def _empty_parse_result(raw: str = '') -> dict:
    return {
        'raw': raw or '',
        'cleaned_name': '',
        'steam_app_id': None,
        'bare_franchise': False,
        'had_vr_suffix': False,
        'transforms': [],
        'peel_profile': 'conservative',
        'update_folder_hint': False,
        'is_bare_update_package': False,
        'update_match_reason': None,
    }


def _record_transform(
    transforms: list,
    stage: str,
    before: str,
    after: str,
    reason: str | None = None,
) -> str:
    """Append a peel step when the string changed; return the new working value."""
    if after == before:
        return after
    step = {'stage': stage, 'before': before, 'after': after}
    if reason:
        step['reason'] = reason
    transforms.append(step)
    return after


def parse_game_label(raw: str, *, peel_profile: str | None = None) -> dict:
    """
    Parse a folder or file stem into a cleaned display/search name and optional Steam App ID.

    Stage order (docs/strategy/name-resolution.md):
      A0 basename/trim → A1 scene/repack → A2 version brackets → A3 (build …)
      → A4 VR/mod → A5 (digits) steam_app_id → A6 spaced v… / Early Access
      → A14 VR re-pass → A9 Incl Update → A10 unbracketed scene → A11 date-stamps
      → A12 Update/Build prose → A13 add-on/HV junk → A7 normalize → A8 apostrophe.

    peel_profile:
      conservative (default) — shipped A0–A14 behavior.
      aggressive — A10 allows single-token space peels; also strips Complete/Collector/
      Legendary from cleaned_name when ≥2 head tokens remain.

    Returns:
        dict with keys: raw, cleaned_name, steam_app_id, bare_franchise, had_vr_suffix,
        transforms (ordered list of {stage, before, after, reason?} for steps that changed
        the label — for unmatched/dupe/proposal explainers; short match_reason codes stay separate),
        update_folder_hint / is_bare_update_package / update_match_reason (W22-M5)
    """
    if not raw or not isinstance(raw, str):
        return _empty_parse_result(raw if isinstance(raw, str) else '')

    profile = (peel_profile or 'conservative').strip().lower()
    if profile not in ('conservative', 'aggressive'):
        profile = 'conservative'

    steam_app_id = None
    had_vr_suffix = False
    transforms: list = []

    # A0
    before = raw
    working = _basename_only(raw)
    working = _record_transform(
        transforms, 'A0', before, working, reason='basename_trim',
    )
    # A1
    working = _record_transform(
        transforms, 'A1', working, strip_repack_tags(working),
        reason='scene_repack_brackets',
    )
    # A2
    working = _record_transform(
        transforms, 'A2', working, strip_version_brackets(working),
        reason='version_brackets',
    )
    # A3
    working = _record_transform(
        transforms, 'A3', working, strip_build_tail(working),
        reason='build_paren',
    )
    # A4
    if detect_vr_suffix(working):
        had_vr_suffix = True
    working = _record_transform(
        transforms, 'A4', working, strip_vr_noise_tail(working),
        reason='vr_mod_tail',
    )
    # A5
    match = _STEAM_ID_RE.search(working)
    if match:
        steam_app_id = int(match.group(1))
        working = _record_transform(
            transforms, 'A5', working, working[: match.start()].strip(),
            reason='steam_app_id',
        )
    # A6
    working = _record_transform(
        transforms, 'A6', working, strip_version_access_tails(working),
        reason='version_or_early_access',
    )
    # A14 — VR re-pass after version strip (Title VR v… → Title VR → Title)
    if detect_vr_suffix(working):
        had_vr_suffix = True
    working = _record_transform(
        transforms, 'A14', working, strip_vr_noise_tail(working),
        reason='vr_repass',
    )
    # A9
    working = _record_transform(
        transforms, 'A9', working, strip_incl_update_tails(working),
        reason='incl_update_paren',
    )
    # A10
    working = _record_transform(
        transforms, 'A10', working,
        strip_unbracketed_scene_suffix(working, peel_profile=profile),
        reason='unbracketed_scene_suffix',
    )
    # A11
    working = _record_transform(
        transforms, 'A11', working, strip_date_stamp_tails(working),
        reason='date_stamp',
    )
    # A12
    working = _record_transform(
        transforms, 'A12', working, strip_update_build_prose_tails(working),
        reason='update_build_prose',
    )
    # A13 — add-on / HV junk only (Complete/Collector/Legendary kept for C10)
    working = _record_transform(
        transforms, 'A13', working, strip_addon_junk_tails(working),
        reason='addon_hv_junk',
    )
    # Aggressive: also peel edition tails into cleaned display (still no mega-lib).
    if profile == 'aggressive':
        working = _record_transform(
            transforms, 'A13b', working, strip_edition_display_tails(working),
            reason='aggressive_edition_display_peel',
        )
    # A7 — whitespace / underscore normalize (casing after alias check)
    before = working
    working = working.replace('_', ' ')
    working = re.sub(r'\s+', ' ', working).strip(' -_')
    working = _record_transform(
        transforms, 'A7', before, working, reason='whitespace_normalize',
    )
    # A8 — smart quotes before casing so apostrophes survive title-case path
    working = _record_transform(
        transforms, 'A8', working, normalize_smart_apostrophes(working),
        reason='smart_apostrophe',
    )

    before_case = working
    aliased = _ALIAS_MAP.get(working.casefold())
    if aliased:
        cleaned = aliased
        cleaned = _record_transform(
            transforms, 'A7', before_case, cleaned, reason='stylized_alias',
        )
    else:
        cleaned = _title_case_tokens(working)
        if cleaned != before_case:
            cleaned = _record_transform(
                transforms, 'A7', before_case, cleaned, reason='title_case',
            )
        # A8 franchise inject after casing so heads match title-case disk labels
        cleaned = _record_transform(
            transforms, 'A8', cleaned, inject_franchise_apostrophes(cleaned),
            reason='franchise_apostrophe_inject',
        )

    update_meta = detect_update_packaging(
        raw, cleaned_name=cleaned, transforms=transforms,
    )

    return {
        'raw': raw,
        'cleaned_name': cleaned,
        'steam_app_id': steam_app_id,
        'bare_franchise': is_bare_franchise(cleaned),
        'had_vr_suffix': had_vr_suffix,
        'transforms': transforms,
        'peel_profile': profile,
        'update_folder_hint': bool(update_meta.get('update_folder_hint')),
        'is_bare_update_package': bool(update_meta.get('is_bare_update_package')),
        'update_match_reason': update_meta.get('match_reason'),
    }
