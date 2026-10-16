"""W20-4 Scan / match policy — GlobalSettings-backed thresholds and peel toggles.

Defaults match today's hardcoded constants in match_scoring / duplicate_check.
Never exposes mega-lib / depth-3 family walk.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.utils.cache import cache
from oneirodex.models import GlobalSettings
from oneirodex.utils.duplicate_check import DEFAULT_TITLE_THRESHOLD
from oneirodex.utils.match_scoring import DEFAULT_AMBIGUOUS_GAP, DEFAULT_HIGH_THRESHOLD

PEEL_PROFILES = frozenset({'conservative', 'aggressive'})
DEFAULT_PEEL_PROFILE = 'conservative'

# Flat keys stored under GlobalSettings.settings['scan_match'] (snake_case API shape).
POLICY_STORAGE_KEY = 'scan_match'

SAFE_VARIANT_DEFAULTS = {
    'enable_year_drop_variant': True,
    'enable_pack_peel_variant': True,
    'enable_edition_peel_variant': True,
    'enable_sequel_numeral_variant': True,
}

CORE_DEFAULTS = {
    'dupe_title_threshold': float(DEFAULT_TITLE_THRESHOLD),
    'match_high_threshold': float(DEFAULT_HIGH_THRESHOLD),
    'match_ambiguous_gap': float(DEFAULT_AMBIGUOUS_GAP),
    'peel_profile': DEFAULT_PEEL_PROFILE,
    **SAFE_VARIANT_DEFAULTS,
}

# CamelCase aliases used by classic server settings JSON (DEFAULT_SETTINGS).
CAMEL_TO_SNAKE = {
    'dupeTitleThreshold': 'dupe_title_threshold',
    'matchHighThreshold': 'match_high_threshold',
    'matchAmbiguousGap': 'match_ambiguous_gap',
    'peelProfile': 'peel_profile',
    'enableYearDropVariant': 'enable_year_drop_variant',
    'enablePackPeelVariant': 'enable_pack_peel_variant',
    'enableEditionPeelVariant': 'enable_edition_peel_variant',
    'enableSequelNumeralVariant': 'enable_sequel_numeral_variant',
    'proposeOnlyScan': 'propose_only_scan',
}


def _settings_row() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def _ensure_settings_row() -> GlobalSettings:
    row = _settings_row()
    if row is None:
        row = GlobalSettings(settings={})
        db.session.add(row)
        db.session.flush()
    return row


def _clamp_unit(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def normalize_peel_profile(value: Any) -> str:
    raw = str(value or DEFAULT_PEEL_PROFILE).strip().lower()
    if raw in PEEL_PROFILES:
        return raw
    return DEFAULT_PEEL_PROFILE


def _boolish(value: Any, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on'):
        return True
    if text in ('0', 'false', 'no', 'off'):
        return False
    return bool(default)


def _stored_policy_blob(row: GlobalSettings | None) -> dict:
    """Merge nested scan_match blob + camelCase top-level aliases from settings JSON."""
    if row is None:
        return {}
    blob: dict = {}
    settings = row.settings if isinstance(row.settings, dict) else {}
    nested = settings.get(POLICY_STORAGE_KEY)
    if isinstance(nested, dict):
        blob.update(nested)
    for camel, snake in CAMEL_TO_SNAKE.items():
        if camel in settings and snake not in blob:
            blob[snake] = settings[camel]
        if snake in settings and snake not in blob:
            blob[snake] = settings[snake]
    return blob


def resolve_scan_match_policy(settings: Any = None) -> dict:
    """
    Return a complete policy dict (snake_case) with defaults filled in.

    Accepts None, a GlobalSettings row, a scan settings dict (snake or camel),
    or a policy fragment. Unset keys fall back to today's hardcoded constants.
    """
    fragment: dict = {}

    if settings is None:
        try:
            row = _settings_row()
            fragment = _stored_policy_blob(row)
            propose = bool(getattr(row, 'propose_only_scan', False)) if row else False
        except Exception:
            # No app/DB context (unit tests) — pure defaults.
            propose = False
            fragment = {}
    elif isinstance(settings, GlobalSettings):
        fragment = _stored_policy_blob(settings)
        propose = bool(getattr(settings, 'propose_only_scan', False))
    elif isinstance(settings, dict):
        # Threaded scan dict or API body.
        for camel, snake in CAMEL_TO_SNAKE.items():
            if camel in settings:
                fragment[snake] = settings[camel]
            if snake in settings:
                fragment[snake] = settings[snake]
        nested = settings.get(POLICY_STORAGE_KEY)
        if isinstance(nested, dict):
            for key, value in nested.items():
                fragment.setdefault(key, value)
        # Thin scan dicts may omit thresholds — fill unset keys from DB when available.
        threshold_keys = (
            'dupe_title_threshold',
            'match_high_threshold',
            'match_ambiguous_gap',
            'peel_profile',
            *SAFE_VARIANT_DEFAULTS.keys(),
        )
        if not all(key in fragment for key in threshold_keys):
            try:
                stored = _stored_policy_blob(_settings_row())
                for key, value in stored.items():
                    fragment.setdefault(key, value)
            except Exception:
                pass
        if 'propose_only_scan' in settings:
            propose = _boolish(settings.get('propose_only_scan'), False)
        elif 'proposeOnlyScan' in settings:
            propose = _boolish(settings.get('proposeOnlyScan'), False)
        else:
            try:
                row = _settings_row()
                propose = bool(getattr(row, 'propose_only_scan', False)) if row else False
            except Exception:
                propose = False
    else:
        propose = bool(getattr(settings, 'propose_only_scan', False))
        fragment = {}

    policy = {
        'propose_only_scan': bool(propose),
        'dupe_title_threshold': _clamp_unit(
            fragment.get('dupe_title_threshold'),
            CORE_DEFAULTS['dupe_title_threshold'],
        ),
        'match_high_threshold': _clamp_unit(
            fragment.get('match_high_threshold'),
            CORE_DEFAULTS['match_high_threshold'],
        ),
        'match_ambiguous_gap': _clamp_unit(
            fragment.get('match_ambiguous_gap'),
            CORE_DEFAULTS['match_ambiguous_gap'],
        ),
        'peel_profile': normalize_peel_profile(fragment.get('peel_profile')),
    }
    for key, default in SAFE_VARIANT_DEFAULTS.items():
        policy[key] = _boolish(fragment.get(key), default)
    return policy


def get_scan_match_config() -> dict:
    """Admin GET payload — always includes core + safe-variant keys."""
    return resolve_scan_match_policy()


def save_scan_match_config(data: dict) -> dict:
    """Persist a partial PUT body; returns the full resolved policy."""
    if not isinstance(data, dict) or not data:
        raise ValueError('No fields to update')

    # Refuse mega-lib / depth-3 keys even if a client sends them.
    forbidden = {
        'mega_lib', 'megaLib', 'allow_mega_lib',
        'family_walk_depth', 'familyWalkDepth',
        'depth_3_family_walk', 'depth3FamilyWalk', 'max_family_depth',
    }
    for key in forbidden:
        if key in data:
            raise ValueError(f'{key} is not a supported scan/match setting')

    row = _ensure_settings_row()
    current = resolve_scan_match_policy(row)

    if 'propose_only_scan' in data or 'proposeOnlyScan' in data:
        raw = data.get('propose_only_scan', data.get('proposeOnlyScan'))
        current['propose_only_scan'] = _boolish(raw, current['propose_only_scan'])
        row.propose_only_scan = current['propose_only_scan']

    if 'dupe_title_threshold' in data or 'dupeTitleThreshold' in data:
        current['dupe_title_threshold'] = _clamp_unit(
            data.get('dupe_title_threshold', data.get('dupeTitleThreshold')),
            current['dupe_title_threshold'],
        )
    if 'match_high_threshold' in data or 'matchHighThreshold' in data:
        current['match_high_threshold'] = _clamp_unit(
            data.get('match_high_threshold', data.get('matchHighThreshold')),
            current['match_high_threshold'],
        )
    if 'match_ambiguous_gap' in data or 'matchAmbiguousGap' in data:
        current['match_ambiguous_gap'] = _clamp_unit(
            data.get('match_ambiguous_gap', data.get('matchAmbiguousGap')),
            current['match_ambiguous_gap'],
        )
    if 'peel_profile' in data or 'peelProfile' in data:
        current['peel_profile'] = normalize_peel_profile(
            data.get('peel_profile', data.get('peelProfile')),
        )

    for snake, camel in (
        ('enable_year_drop_variant', 'enableYearDropVariant'),
        ('enable_pack_peel_variant', 'enablePackPeelVariant'),
        ('enable_edition_peel_variant', 'enableEditionPeelVariant'),
        ('enable_sequel_numeral_variant', 'enableSequelNumeralVariant'),
    ):
        if snake in data or camel in data:
            current[snake] = _boolish(
                data.get(snake, data.get(camel)),
                current[snake],
            )

    settings = dict(row.settings) if isinstance(row.settings, dict) else {}
    stored = {
        'dupe_title_threshold': current['dupe_title_threshold'],
        'match_high_threshold': current['match_high_threshold'],
        'match_ambiguous_gap': current['match_ambiguous_gap'],
        'peel_profile': current['peel_profile'],
        'enable_year_drop_variant': current['enable_year_drop_variant'],
        'enable_pack_peel_variant': current['enable_pack_peel_variant'],
        'enable_edition_peel_variant': current['enable_edition_peel_variant'],
        'enable_sequel_numeral_variant': current['enable_sequel_numeral_variant'],
    }
    settings[POLICY_STORAGE_KEY] = stored
    # Keep camelCase mirrors for classic server-settings merges.
    settings['dupeTitleThreshold'] = stored['dupe_title_threshold']
    settings['matchHighThreshold'] = stored['match_high_threshold']
    settings['matchAmbiguousGap'] = stored['match_ambiguous_gap']
    settings['peelProfile'] = stored['peel_profile']
    settings['enableYearDropVariant'] = stored['enable_year_drop_variant']
    settings['enablePackPeelVariant'] = stored['enable_pack_peel_variant']
    settings['enableEditionPeelVariant'] = stored['enable_edition_peel_variant']
    settings['enableSequelNumeralVariant'] = stored['enable_sequel_numeral_variant']
    settings['proposeOnlyScan'] = current['propose_only_scan']
    row.settings = settings

    db.session.commit()
    try:
        cache.delete('global_settings')
    except Exception:
        pass
    return resolve_scan_match_policy(row)
