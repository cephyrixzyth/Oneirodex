"""Decide when a same-IGDB hit is a true duplicate vs a different folder.

Duplicates are scoped to the **same system (library platform) and region**.
Cross-system copies of the same title are intentional (NES + SNES + Switch) and
must not be marked Duplicate — ``Game.igdb_id`` is unique per row, so those
editions import without the colliding IGDB id (title-group browse pairs them).
"""

from __future__ import annotations

import os
import re
from typing import Any

from oneirodex.utils.game_name_parse import parse_game_label
from oneirodex.utils.match_scoring import score_candidate

# Folder titles must be this similar to call same-IGDB a "Duplicate".
# Below this → treat as Unmatched (different packaging / remaster / bad match).
DEFAULT_TITLE_THRESHOLD = 0.85
# How closely an existing game's own folder must agree with its library name
# before that name may stand in for the folder in a duplicate check.
LIBRARY_NAME_TRUST_MIN = 0.7


def normalize_disk_path(path: str | None) -> str:
    if not path:
        return ''
    cleaned = path.replace('\\', '/').rstrip('/')
    try:
        cleaned = os.path.normcase(os.path.abspath(cleaned))
    except (OSError, ValueError):
        cleaned = os.path.normcase(cleaned)
    # Collapse duplicate slashes
    return re.sub(r'/+', '/', cleaned)


def folder_basename(path: str | None) -> str:
    if not path:
        return ''
    return os.path.basename(path.replace('\\', '/').rstrip('/'))


def normalize_rom_region(region: str | None) -> str | None:
    """Fold ROM region tags to a canonical code (USA / JPN / EUR / …)."""
    if region is None:
        return None
    text = str(region).strip()
    if not text:
        return None
    try:
        from oneirodex.utils.rom_language import normalize_region_token

        folded = normalize_region_token(text)
        if folded:
            return folded
    except Exception:
        pass
    return text.upper()


def library_platform_key(library_or_platform) -> str | None:
    """Stable system key from a Library, LibraryPlatform enum, or name string."""
    if library_or_platform is None:
        return None
    platform = getattr(library_or_platform, 'platform', library_or_platform)
    name = getattr(platform, 'name', None)
    if name:
        return str(name)
    text = str(platform).strip()
    return text or None


def game_library_platform_key(game) -> str | None:
    """Platform of the library that owns ``game`` (None when unloaded/missing)."""
    if game is None:
        return None
    library = getattr(game, 'library', None)
    if library is not None:
        return library_platform_key(library)
    return None


def same_duplicate_scope(
    existing_game,
    *,
    new_platform=None,
    new_library_uuid: str | None = None,
    new_rom_region: str | None = None,
) -> bool:
    """
    True when ``existing_game`` may count as a Duplicate of the scan target.

    Rules:
    - Different systems (library platforms) → never a duplicate.
    - Same system, both sides have a known ROM region and they differ → never.
    - Same system, region unknown on either side → still in scope (title check).
    - When platform cannot be resolved, fall back to same ``library_uuid``.
    """
    if existing_game is None:
        return False

    existing_platform = game_library_platform_key(existing_game)
    new_platform_key = library_platform_key(new_platform) if new_platform is not None else None

    if existing_platform and new_platform_key:
        if existing_platform != new_platform_key:
            return False
    elif new_library_uuid:
        existing_lib = getattr(existing_game, 'library_uuid', None)
        if existing_lib and str(existing_lib) != str(new_library_uuid):
            # Cross-library and we cannot prove same platform → out of scope.
            if not existing_platform or not new_platform_key:
                return False
    elif existing_platform or new_platform_key:
        # One side known, the other missing — do not invent a same-system match.
        return False

    existing_region = normalize_rom_region(getattr(existing_game, 'rom_region', None))
    new_region = normalize_rom_region(new_rom_region)
    if existing_region and new_region and existing_region != new_region:
        return False
    return True


_EDITION_MARKERS = {
    'disc': re.compile(r'\b(?:disc|disk|cd)\s*[-._ ]?([0-9]+)\b', re.I),
    'revision': re.compile(r'\b(?:rev(?:ision)?)[ ._-]*([a-z0-9]+)\b', re.I),
    'presentation': re.compile(r'\b(remaster(?:ed)?|remake|prototype|demo|beta|translation)\b', re.I),
}


def _is_vr_edition(label: str) -> bool:
    from oneirodex.utils.vr_catalog import has_vr_token

    parsed = parse_game_label(label)
    if parsed.get('had_vr_suffix'):
        return bool(parsed.get('vr_title'))
    return has_vr_token(label)


def edition_conflict(left: str, right: str) -> str | None:
    """A provider ID may cover several discs, releases, or localized editions.

    A VR edition ("Green Hell VR") is a separate product from the flat game
    ("Green Hell"), never a second copy of it.
    """
    if _is_vr_edition(left or '') != _is_vr_edition(right or ''):
        return 'vr'
    for category, pattern in _EDITION_MARKERS.items():
        def values(text):
            return {v.casefold().removesuffix('ed') if v.casefold() == 'remastered' else v.casefold()
                    for v in pattern.findall(text.replace('_', ' '))}
        a, b = values(left), values(right)
        if a != b and (category == 'presentation' or (a and b)):
            return category
    return None


def explain_duplicate_match(
    existing_game,
    new_full_disk_path: str,
    new_raw_name: str | None = None,
    *,
    title_threshold: float = DEFAULT_TITLE_THRESHOLD,
    new_platform=None,
    new_library_uuid: str | None = None,
    new_rom_region: str | None = None,
) -> dict[str, Any]:
    """
    Return a structured match explanation for UI glance + fix logging.

    Keys: is_duplicate, match_reason (short code), match_score, matched_game_uuid,
    threshold, transforms (ordered Stage A peels for the new folder label)
    """
    existing_uuid = getattr(existing_game, 'uuid', None)
    existing_path = getattr(existing_game, 'full_disk_path', None) or ''
    existing_norm = normalize_disk_path(existing_path)
    new_norm = normalize_disk_path(new_full_disk_path)

    if not same_duplicate_scope(
        existing_game,
        new_platform=new_platform,
        new_library_uuid=new_library_uuid,
        new_rom_region=new_rom_region,
    ):
        existing_platform = game_library_platform_key(existing_game)
        new_platform_key = library_platform_key(new_platform) if new_platform is not None else None
        existing_region = normalize_rom_region(getattr(existing_game, 'rom_region', None))
        new_region = normalize_rom_region(new_rom_region)
        if (
            existing_platform
            and new_platform_key
            and existing_platform != new_platform_key
        ):
            reason = 'cross_system'
        elif (
            existing_region
            and new_region
            and existing_region != new_region
        ):
            reason = 'region_mismatch'
        else:
            reason = 'cross_system'
        return {
            'is_duplicate': False,
            'match_reason': reason,
            'match_score': 0.0,
            'matched_game_uuid': None,
            'threshold': title_threshold,
            'transforms': [],
        }

    if existing_norm and new_norm and existing_norm == new_norm:
        label = new_raw_name or folder_basename(new_full_disk_path)
        return {
            'is_duplicate': True,
            'match_reason': 'same_path',
            'match_score': 1.0,
            'matched_game_uuid': existing_uuid,
            'threshold': title_threshold,
            'transforms': list(parse_game_label(label).get('transforms') or []),
        }

    # The folder on disk is the evidence. ``new_raw_name`` is the scan-cleaned
    # name, which release-group filters can cut down ("Monkey Island 2 Lechucks
    # Revenge Remastered" lost "Remastered"); prefer the folder's own name.
    new_label = folder_basename(new_full_disk_path) or new_raw_name or ''
    existing_label = folder_basename(existing_path) or (getattr(existing_game, 'name', None) or '')

    conflict = edition_conflict(new_label, existing_label)
    if conflict:
        return {'is_duplicate': False, 'match_reason': 'different_' + conflict,
                'match_score': 0.0, 'matched_game_uuid': None,
                'threshold': title_threshold, 'transforms': [],
                'compared_labels': [new_label, existing_label]}

    new_parsed = parse_game_label(new_label)
    new_cleaned = new_parsed.get('cleaned_name') or new_label
    existing_cleaned = parse_game_label(existing_label).get('cleaned_name') or existing_label
    library_name = getattr(existing_game, 'name', None) or ''
    transforms = list(new_parsed.get('transforms') or [])

    score_vs_folder = score_candidate(new_cleaned, existing_cleaned)
    score_vs_library = score_candidate(new_cleaned, library_name) if library_name else 0.0
    # The library name only counts when the existing game's own folder agrees
    # with it. A wrong earlier match ("Star Trek Deep Space Nine" filed as "Star
    # Trek - Armada") otherwise turns every Star Trek folder into its duplicate.
    # The bar is loose: region or build tags ("Celeste (USA)") still trust it.
    if library_name and existing_cleaned and score_candidate(existing_cleaned, library_name) < LIBRARY_NAME_TRUST_MIN:
        score_vs_library = 0.0
    best = max(score_vs_folder, score_vs_library)
    reason = 'title_vs_folder' if score_vs_folder >= score_vs_library else 'title_vs_library_name'
    is_dup = best >= title_threshold
    return {
        'is_duplicate': is_dup,
        'match_reason': reason if is_dup else 'title_below_threshold',
        'match_score': round(float(best), 4),
        'matched_game_uuid': existing_uuid if is_dup else None,
        'threshold': title_threshold,
        'score_vs_folder': round(float(score_vs_folder), 4),
        'score_vs_library': round(float(score_vs_library), 4),
        'transforms': transforms,
    }


def should_mark_as_duplicate(
    existing_game,
    new_full_disk_path: str,
    new_raw_name: str | None = None,
    *,
    title_threshold: float = DEFAULT_TITLE_THRESHOLD,
    new_platform=None,
    new_library_uuid: str | None = None,
    new_rom_region: str | None = None,
) -> bool:
    """
    True only when the new folder is effectively the same title/path as an
    existing library game that already owns this IGDB ID — on the **same
    system and region**.

    False when the IGDB ID collides but the folder looks like a different
    package (e.g. "Alan Wake Complete Collection" vs "Alan Wake"), or when the
    existing hit is a different system/region — those should stay importable
    (cross-system editions) or Unmatched for human review, not "Duplicate".
    """
    return bool(
        explain_duplicate_match(
            existing_game,
            new_full_disk_path,
            new_raw_name,
            title_threshold=title_threshold,
            new_platform=new_platform,
            new_library_uuid=new_library_uuid,
            new_rom_region=new_rom_region,
        )['is_duplicate']
    )
