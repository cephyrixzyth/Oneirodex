"""Emulator profile helpers — preferred WebRetro cores per platform."""

from __future__ import annotations

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.platform import (
    ARCADE_COMPANION_CORES,
    Emulator,
    LibraryPlatform,
    platform_emulator_mapping,
)


def _request_cache(value=None, *, write=False, clear=False):
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return None
        key = '_emulator_profiles_cache'
        if clear:
            if hasattr(g, key):
                delattr(g, key)
            return None
        if write:
            setattr(g, key, value)
            return value
        return getattr(g, key, None)
    except ImportError:
        return None


def _allowed_cores(platform_key: str) -> set[str]:
    """Cores an operator may pick for a platform.

    Normally the platform mapping. ARCADE is the exception (INSP-43): it is a
    locked platform with an empty mapping on purpose, so its companion cores
    live in their own list.
    """
    if platform_key == 'ARCADE':
        return {e.value for e in ARCADE_COMPANION_CORES}
    return {e.value for e in platform_emulator_mapping.get(LibraryPlatform[platform_key], [])}


def _global_settings() -> GlobalSettings | None:
    return db.session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1),
    ).scalars().first()


def get_emulator_profiles() -> dict[str, str]:
    """Return {platform_name: core_id} overrides from GlobalSettings."""
    cached = _request_cache()
    if cached is not None:
        return cached

    settings = _global_settings()
    raw = getattr(settings, 'emulator_profiles', None) if settings else None
    if not isinstance(raw, dict):
        cleaned: dict[str, str] = {}
    else:
        cleaned = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            platform = key.strip().upper()
            core = value.strip()
            if not platform or not core:
                continue
            cleaned[platform] = core

    _request_cache(cleaned, write=True)
    return cleaned


def set_emulator_profiles(profiles: dict[str, str | None]) -> dict[str, str]:
    """Validate and persist preferred cores. Empty/null clears a platform."""
    settings = _global_settings()
    if not settings:
        settings = GlobalSettings()
        db.session.add(settings)

    valid_platforms = {p.name for p in LibraryPlatform}
    valid_cores = {e.value for e in Emulator}
    next_map = dict(get_emulator_profiles())

    for platform, core in (profiles or {}).items():
        platform_key = str(platform or '').strip().upper()
        if platform_key not in valid_platforms:
            raise ValueError(f'Unsupported platform: {platform}')
        if core is None or str(core).strip() == '':
            next_map.pop(platform_key, None)
            continue
        core_value = str(core).strip()
        allowed = _allowed_cores(platform_key)
        if core_value not in valid_cores or (allowed and core_value not in allowed):
            raise ValueError(f'Core {core_value} is not valid for {platform_key}')
        next_map[platform_key] = core_value

    settings.emulator_profiles = next_map
    db.session.commit()
    _request_cache(clear=True)
    return next_map


def resolve_emulators_for_platform(platform_name: str) -> dict:
    """Return default cores with optional preferred core first."""
    platform_enum = LibraryPlatform[platform_name]
    defaults = [e.value for e in platform_emulator_mapping.get(platform_enum, [])]
    if platform_name.upper() == 'ARCADE':
        # INSP-43 -- offered, never mapped; see ARCADE_COMPANION_CORES.
        defaults = [e.value for e in ARCADE_COMPANION_CORES]
    preferred = get_emulator_profiles().get(platform_name.upper())
    ordered = list(defaults)
    if preferred and preferred in ordered:
        ordered.remove(preferred)
        ordered.insert(0, preferred)
    elif preferred:
        ordered.insert(0, preferred)
    return {
        'platform': platform_name,
        'emulators': ordered,
        'preferred': preferred if preferred in (defaults + ([preferred] if preferred else [])) else preferred,
        'defaults': defaults,
    }
