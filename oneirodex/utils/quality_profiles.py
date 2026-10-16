"""Quality / release profiles (preferred groups/patterns, size band, blocklist).

Stored on ``GlobalSettings.quality_profiles`` (JSON). Supports:

* **v2 multi-profile** — ``{ version, active_id, profiles: [...] }``
* **v1 flat** — legacy single-object shape (migrated on read)

Active profile drives *arr search scoring and scan name-clean extras
(blocked groups + excluded terms merge into ReleaseGroup-style strip patterns).
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings

PROFILE_FIELD_DEFAULTS: dict[str, Any] = {
    'preferred_groups': [],
    'blocked_groups': [],
    'preferred_patterns': [],
    'excluded_terms': [],
    'min_size_mb': None,
    'max_size_mb': None,
    'prefer_repack': True,
}

# Legacy flat keys (v1) — still accepted on PUT of the active profile.
LEGACY_FLAT_KEYS = frozenset(PROFILE_FIELD_DEFAULTS.keys())

DEFAULT_PROFILE_NAME = 'Default'


def _new_id() -> str:
    return str(uuid4())


# Migrating the legacy flat format must land on the *same* id every time.
#
# It used to mint a random uuid per conversion, and `_load_store()` does not
# persist the migration unless asked — so `save_quality_profile()` (load, read
# active_id, then call update_quality_profile, which loads again) migrated
# twice, got two different ids, and raised "profile not found" for the id it
# had just been handed. Anyone upgrading from the flat format hit that on their
# first edit.
LEGACY_PROFILE_ID = str(uuid5(NAMESPACE_URL, 'oneirodex:quality-profile:legacy'))


def _normalize_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _coerce_size(val: Any) -> float | None:
    if val is None or val == '':
        return None
    return float(val)


def _profile_fields_from(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    out = dict(PROFILE_FIELD_DEFAULTS)
    for key in PROFILE_FIELD_DEFAULTS:
        if key not in src:
            continue
        if key in ('preferred_groups', 'blocked_groups', 'preferred_patterns', 'excluded_terms'):
            out[key] = _normalize_str_list(src.get(key))
        elif key in ('min_size_mb', 'max_size_mb'):
            try:
                out[key] = _coerce_size(src.get(key))
            except (TypeError, ValueError):
                out[key] = None
        elif key == 'prefer_repack':
            out[key] = bool(src.get(key))
    return out


def _make_profile(
    *,
    profile_id: str | None = None,
    name: str | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = _profile_fields_from(fields)
    return {
        'id': profile_id or _new_id(),
        'name': (name or DEFAULT_PROFILE_NAME).strip() or DEFAULT_PROFILE_NAME,
        **body,
    }


def _settings_row() -> GlobalSettings:
    row = db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()
    if not row:
        row = GlobalSettings()
        db.session.add(row)
        db.session.flush()
    return row


def _is_v2(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get('profiles'), list)


def _is_v1_flat(raw: Any) -> bool:
    if not isinstance(raw, dict) or _is_v2(raw):
        return False
    return bool(LEGACY_FLAT_KEYS.intersection(raw.keys())) or not raw


def _migrate_raw(raw: Any) -> dict[str, Any]:
    """Normalize stored JSON to v2 ``{version, active_id, profiles}``."""
    if _is_v2(raw):
        profiles = []
        for item in raw.get('profiles') or []:
            if not isinstance(item, dict):
                continue
            pid = str(item.get('id') or '').strip() or _new_id()
            profiles.append(_make_profile(
                profile_id=pid,
                name=item.get('name'),
                fields=item,
            ))
        if not profiles:
            profiles = [_make_profile()]
        active_id = str(raw.get('active_id') or '').strip()
        if not any(p['id'] == active_id for p in profiles):
            active_id = profiles[0]['id']
        return {'version': 2, 'active_id': active_id, 'profiles': profiles}

    if _is_v1_flat(raw):
        profile = _make_profile(
            profile_id=LEGACY_PROFILE_ID,
            fields=raw if isinstance(raw, dict) else None,
        )
        return {'version': 2, 'active_id': profile['id'], 'profiles': [profile]}

    profile = _make_profile()
    return {'version': 2, 'active_id': profile['id'], 'profiles': [profile]}


def _save_store(store: dict[str, Any]) -> dict[str, Any]:
    row = _settings_row()
    normalized = _migrate_raw(store)
    row.quality_profiles = normalized
    flag_modified(row, 'quality_profiles')
    db.session.commit()
    return normalized


def _load_store(*, persist_migration: bool = False) -> dict[str, Any]:
    row = _settings_row()
    raw = getattr(row, 'quality_profiles', None)
    store = _migrate_raw(raw)
    # Optional persist when upgrading legacy flat JSON (admin list/create paths).
    if persist_migration and not _is_v2(raw):
        row.quality_profiles = store
        flag_modified(row, 'quality_profiles')
        db.session.commit()
    return store


def _public_store(store: dict[str, Any]) -> dict[str, Any]:
    """List payload plus flattened active fields for legacy admin UI."""
    active = get_quality_profile(store=store)
    return {
        'version': 2,
        'active_id': store['active_id'],
        'profiles': list(store['profiles']),
        **{k: active[k] for k in PROFILE_FIELD_DEFAULTS},
        'id': active.get('id'),
        'name': active.get('name'),
    }


def list_quality_profiles() -> dict[str, Any]:
    store = _load_store(persist_migration=True)
    return _public_store(store)


def get_quality_profile(
    profile_id: str | None = None,
    *,
    store: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one profile (active when ``profile_id`` is None)."""
    data = store if store is not None else _load_store()
    target = (profile_id or data.get('active_id') or '').strip()
    for profile in data.get('profiles') or []:
        if profile.get('id') == target:
            return dict(profile)
    profiles = data.get('profiles') or []
    if profiles:
        return dict(profiles[0])
    return _make_profile()


def create_quality_profile(payload: dict[str, Any]) -> dict[str, Any]:
    store = _load_store()
    name = (payload.get('name') or 'Profile').strip() or 'Profile'
    profile = _make_profile(name=name, fields=payload)
    store['profiles'].append(profile)
    if payload.get('activate') or len(store['profiles']) == 1:
        store['active_id'] = profile['id']
    _save_store(store)
    return profile


def update_quality_profile(profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store = _load_store()
    pid = (profile_id or '').strip()
    for idx, profile in enumerate(store['profiles']):
        if profile.get('id') != pid:
            continue
        fields = _profile_fields_from({**profile, **payload})
        name = payload.get('name', profile.get('name'))
        updated = _make_profile(profile_id=pid, name=name, fields=fields)
        store['profiles'][idx] = updated
        if payload.get('activate') is True:
            store['active_id'] = pid
        _save_store(store)
        return updated
    raise KeyError(f'profile not found: {pid}')


def delete_quality_profile(profile_id: str) -> dict[str, Any]:
    store = _load_store()
    pid = (profile_id or '').strip()
    remaining = [p for p in store['profiles'] if p.get('id') != pid]
    if len(remaining) == len(store['profiles']):
        raise KeyError(f'profile not found: {pid}')
    if not remaining:
        remaining = [_make_profile()]
    store['profiles'] = remaining
    if store.get('active_id') == pid:
        store['active_id'] = remaining[0]['id']
    saved = _save_store(store)
    return _public_store(saved)


def set_active_quality_profile(profile_id: str) -> dict[str, Any]:
    store = _load_store()
    pid = (profile_id or '').strip()
    if not any(p.get('id') == pid for p in store['profiles']):
        raise KeyError(f'profile not found: {pid}')
    store['active_id'] = pid
    saved = _save_store(store)
    return _public_store(saved)


def save_quality_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Legacy PUT helper: update the active profile fields (and optional name)."""
    store = _load_store()
    active_id = store['active_id']
    return update_quality_profile(active_id, payload)


def active_exclude_terms_for_scan() -> list[str]:
    """Blocked groups + excluded terms from the active profile (scan name-clean)."""
    profile = get_quality_profile()
    terms: list[str] = []
    seen: set[str] = set()
    for key in ('blocked_groups', 'excluded_terms'):
        for item in profile.get(key) or []:
            text = str(item).strip()
            if not text:
                continue
            low = text.lower()
            if low in seen:
                continue
            seen.add(low)
            terms.append(text)
    return terms


def score_release_title(
    title: str,
    *,
    size_bytes: int | None = None,
    profile: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Heuristic score for an indexer / release title against a quality profile."""
    cfg = profile if profile is not None else get_quality_profile(profile_id)
    text = (title or '').lower()
    score = 0
    reasons: list[str] = []

    for group in cfg.get('preferred_groups') or []:
        if group.lower() in text:
            score += 10
            reasons.append(f'preferred:{group}')
    for pattern in cfg.get('preferred_patterns') or []:
        if pattern.lower() in text:
            score += 5
            reasons.append(f'pattern:{pattern}')
    for group in cfg.get('blocked_groups') or []:
        if group.lower() in text:
            score -= 100
            reasons.append(f'blocked:{group}')
    for term in cfg.get('excluded_terms') or []:
        if term.lower() in text:
            score -= 100
            reasons.append(f'excluded:{term}')
    if cfg.get('prefer_repack') and ('repack' in text or 'proper' in text):
        score += 3
        reasons.append('repack_or_proper')

    size_mb = (size_bytes / (1024 * 1024)) if size_bytes else None
    min_mb = cfg.get('min_size_mb')
    max_mb = cfg.get('max_size_mb')
    if size_mb is not None:
        if min_mb is not None and size_mb < float(min_mb):
            score -= 20
            reasons.append('below_min_size')
        if max_mb is not None and size_mb > float(max_mb):
            score -= 20
            reasons.append('above_max_size')

    return {
        'title': title,
        'score': score,
        'reasons': reasons,
        'allowed': score > -50,
        'profile_id': cfg.get('id'),
        'profile_name': cfg.get('name'),
    }
