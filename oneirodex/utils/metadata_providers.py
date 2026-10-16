"""Operator toggles for Steam / GOG / Epic as scan-match + enrich sources.

Keyless storefronts are always *usable*; these flags only decide whether Stage D
identify and the metadata cascade ask them. Defaults are all on — same behaviour
as before the toggles existed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from oneirodex import cache
from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import GlobalSettings
from oneirodex.utils.event_logging import log_system_event

STORAGE_KEY = 'metadata_providers'
# Storefront sources feed Stage D *and* enrichment; hash_identify (INSP-31) is
# an identify-only source with the same on/off switch and no Stage D role.
STORE_PROVIDER_IDS = ('steam', 'gog', 'epic')
PROVIDER_IDS = STORE_PROVIDER_IDS + ('hash_identify',)
DEFAULTS = {provider: True for provider in PROVIDER_IDS}


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


def resolve_metadata_providers(settings: Any = None) -> dict[str, bool]:
    """Return ``{steam,gog,epic: bool}`` with defaults filled."""
    fragment: dict = {}
    try:
        if settings is None:
            row = _settings_row()
            blob = row.settings if row and isinstance(row.settings, dict) else {}
        elif isinstance(settings, GlobalSettings):
            blob = settings.settings if isinstance(settings.settings, dict) else {}
        elif isinstance(settings, dict):
            blob = settings
        else:
            blob = {}
        nested = blob.get(STORAGE_KEY) if isinstance(blob, dict) else None
        if isinstance(nested, dict):
            fragment.update(nested)
        for key in PROVIDER_IDS:
            if key in blob and key not in fragment:
                fragment[key] = blob[key]
    except Exception as exc:
        # Falling back to DEFAULTS means every provider turns *on*, so a DB
        # hiccup or a corrupt settings blob would quietly re-enable sources the
        # operator switched off. Keep the permissive fallback — it matches
        # pre-toggle behaviour and must not break a scan — but say so, instead
        # of swallowing the reason.
        log_system_event(
            f'Metadata provider flags unreadable, defaulting to all enabled: {exc}',
            event_type='settings',
            event_level='warning',
        )
        fragment = {}

    out: dict[str, bool] = {}
    for key in PROVIDER_IDS:
        raw = fragment.get(key, DEFAULTS[key])
        if isinstance(raw, dict):
            raw = raw.get('identify', raw.get('enabled', DEFAULTS[key]))
        out[key] = _boolish(raw, DEFAULTS[key])
    return out


def stage_d_source_ids() -> tuple[str, ...]:
    """Enabled Stage D store sources in cascade order."""
    flags = resolve_metadata_providers()
    return tuple(key for key in STORE_PROVIDER_IDS if flags.get(key))


def disabled_enrich_sources() -> frozenset[str]:
    """Source ids the enrichment cascade should skip."""
    flags = resolve_metadata_providers()
    return frozenset(key for key in STORE_PROVIDER_IDS if not flags.get(key))


def get_metadata_providers_config() -> dict:
    """Admin GET payload — flags plus honesty notes."""
    flags = resolve_metadata_providers()
    return {
        'providers': flags,
        'notes': {
            'steam': 'Stage D App ID / exact title + PC enrichment. Never a download queue.',
            'gog': 'Stage D exact title + PC enrichment. DRM-free catalogue only.',
            'epic': 'Stage D exact title + PC enrichment. Ownership/register links only.',
            'hash_identify': "Console identify after an IGDB and local-DAT miss: the file's own hashes against a keyless community lookup. Identity only, never enrichment; never a download.",
        },
    }


def save_metadata_providers(data: dict) -> dict:
    """Persist a partial PUT body; returns the full config payload."""
    if not isinstance(data, dict) or not data:
        raise ValueError('No fields to update')

    # Accept either flat {steam: true} or nested {providers: {steam: true}}.
    incoming = data.get('providers') if isinstance(data.get('providers'), dict) else data
    if not isinstance(incoming, dict) or not incoming:
        raise ValueError('No provider fields to update')

    # A body of only unknown keys used to match nothing, change nothing, and
    # still answer 200 with the full config — so a typo ("steamm") read as a
    # successful save. Name what was not recognised instead.
    unknown = [key for key in incoming if key not in PROVIDER_IDS]
    if len(unknown) == len(incoming):
        raise ValueError(
            f"No known provider in {', '.join(sorted(unknown))} — expected one of "
            f"{', '.join(PROVIDER_IDS)}"
        )

    row = _ensure_settings_row()
    current = resolve_metadata_providers(row)
    changed = False
    for key in PROVIDER_IDS:
        if key not in incoming:
            continue
        next_val = _boolish(incoming.get(key), current[key])
        if next_val != current[key]:
            current[key] = next_val
            changed = True

    if changed or STORAGE_KEY not in (row.settings or {}):
        settings = dict(row.settings) if isinstance(row.settings, dict) else {}
        settings[STORAGE_KEY] = dict(current)
        row.settings = settings
        flag_modified(row, 'settings')
        db.session.commit()
        try:
            cache.delete('global_settings')
        except Exception:
            pass

    return get_metadata_providers_config()
