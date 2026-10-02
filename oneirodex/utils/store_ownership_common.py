"""Shared plumbing for the register-only store ownership sync: the store
list and sync modes, credential lookups, the guarded outbound HTTP call,
title matching against the library and the owned-title upsert.

Split out of ``store_ownership`` in the v11 cycle (H-D.4) as a pure move.
NEVER downloads games, DRM payloads or store clients (see ``store_ownership``).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from oneirodex import db
from oneirodex.models import Game, GameURL, StoreAccount, UserOwnedTitle
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.http_safe import safe_request
from oneirodex.utils.security import validate_user_outbound_http_url
from oneirodex.utils.store_capabilities import REGISTER_ACCOUNT_STORES


# meta_quest = register-only ownership (CSV); never downloads DRM titles.
# amazon = live register via unofficial Nile/Heroic (IDs + names); never downloads.
# xbox / psn = register-only, opt-in, unofficial (INSP-42): CSV always; live only
#   when ENABLE_UNOFFICIAL_STORE_SYNC names the store. Never downloads.
VALID_STORES = REGISTER_ACCOUNT_STORES
UNOFFICIAL_OPT_IN_STORES = frozenset({'xbox', 'psn'})
#: Width of UserOwnedTitle.external_app_id. Xbox package family names and
#: Amazon product IDs run well past the original 32.
EXTERNAL_APP_ID_MAX = 128
_CSV_ID_HEADERS = frozenset({
    'appid',
    'app_id',
    'id',
    'steam_app_id',
    'product_id',
    'gog_id',
    'epic_id',
    'catalog_item_id',
    'meta_id',
    'quest_id',
    'asin',
    'amazon_id',
    'amzn_id',
    'title_id',
    'xbox_title_id',
    'pfn',
    'np_communication_id',
    'psn_id',
    'name',
})


_NAME_MATCH_STORES = frozenset({'gog', 'epic', 'amazon', 'meta_quest', 'xbox', 'psn'})


def unofficial_store_opt_in() -> frozenset[str]:
    """Stores the operator has opted into live *unofficial* sync for (G5).

    ``ENABLE_UNOFFICIAL_STORE_SYNC`` is a comma list (``xbox,psn``); ``all``
    means both. Unset -- the default -- means CSV snapshot only, and the
    product says so. Read live, so a test or a restart can change it.
    """
    raw = (os.getenv('ENABLE_UNOFFICIAL_STORE_SYNC') or '').strip().lower()
    if not raw or raw in ('0', 'false', 'no', 'off'):
        return frozenset()
    if raw in ('1', 'true', 'yes', 'on', 'all'):
        return UNOFFICIAL_OPT_IN_STORES
    return frozenset(s.strip() for s in raw.split(',') if s.strip()) & UNOFFICIAL_OPT_IN_STORES


def is_ownership_sync_enabled() -> bool:
    settings = global_settings_row()
    if settings is not None and settings.enable_store_ownership_sync is False:
        return False
    return True


def get_steam_web_api_key() -> str | None:
    """Server-level Steam Web API key from env or global settings."""
    key = (os.getenv('STEAM_WEB_API_KEY') or '').strip()
    if key:
        return key
    settings = global_settings_row()
    if settings and settings.steam_web_api_key:
        return settings.steam_web_api_key.strip()
    return None


#: How each store's register can be kept current.
#:
#: 'live'     — we can re-read ownership from the store on a schedule.
#: 'snapshot' — the register only changes when someone imports a file. What was
#:              imported is correct as of that import and drifts from then on.
#:
#: Stated here because the product was quietly implying otherwise: linking a GOG
#: or Epic account looked identical to linking Steam, produced a one-time list,
#: and then never refreshed — with nothing anywhere saying so. A register that
#: silently goes stale is worse than one you know is a snapshot, because you
#: trust it.
#:
#: Moving a store to 'live' means implementing its sync *and* enrolling it in
#: ownership_poller._live_sync_handlers(); this map is what the UI reads, so a
#: store promoted here without a working sync would start lying again.
STORE_SYNC_MODE: dict[str, str] = {
    'steam': 'live',
    'gog': 'live',
    'epic': 'live',
    'amazon': 'live',
    'playnite': 'snapshot',
    # xbox / psn: 'snapshot' here is the *default*; store_sync_mode() promotes
    # them to 'live' only while ENABLE_UNOFFICIAL_STORE_SYNC names them.
    'xbox': 'snapshot',
    'psn': 'snapshot',
}


def store_sync_mode(store: str) -> str:
    """Snapshot unless we know otherwise — the safe direction to be wrong in."""
    key = (store or '').lower()
    if key in UNOFFICIAL_OPT_IN_STORES:
        return 'live' if key in unofficial_store_opt_in() else 'snapshot'
    return STORE_SYNC_MODE.get(key, 'snapshot')


def get_gog_api_token() -> str | None:
    """Household GOG token from env — fallback when a member has no saved credential.

    Live GOG sync uses the unofficial Galaxy client (same public client Heroic
    and Playnite use). Prefer a per-account refresh token on StoreAccount.
    """
    return (
        (os.getenv('GOG_ACCESS_TOKEN') or '').strip()
        or (os.getenv('GOG_REFRESH_TOKEN') or '').strip()
        or (os.getenv('GOG_API_TOKEN') or '').strip()
        or None
    )


def get_epic_api_token() -> str | None:
    """Household Epic device-auth JSON from env — fallback when a member has none."""
    return (
        (os.getenv('EPIC_DEVICE_AUTH') or '').strip()
        or (os.getenv('EPIC_API_TOKEN') or '').strip()
        or None
    )


def get_amazon_api_token() -> str | None:
    """Household Amazon/Nile token from env — fallback when a member has none."""
    return (
        (os.getenv('AMAZON_REFRESH_TOKEN') or '').strip()
        or (os.getenv('AMAZON_NILE_JSON') or '').strip()
        or (os.getenv('AMAZON_API_TOKEN') or '').strip()
        or None
    )


def _outbound(method: str, url: str, **kwargs):
    kwargs.setdefault('timeout', 30)
    return safe_request(
        method,
        url,
        validator=validate_user_outbound_http_url,
        **kwargs,
    )


def _any_account_credential(store: str) -> bool:
    row = db.session.execute(
        select(StoreAccount.id).where(
            StoreAccount.store == store,
            StoreAccount.credential.isnot(None),
            StoreAccount.credential != '',
        ).limit(1)
    ).first()
    return row is not None


#: Keys Oneirodex writes into a stored credential; never accepted from a member.
INTERNAL_CREDENTIAL_KEYS = frozenset({'origin', 'household_fp'})


def household_fp(value: str | None) -> str | None:
    """Short fingerprint of a household env token. A member row holding a
    refreshed copy of the household sign-in records which env value it came
    from, so replacing the env token (the operator's repair) supersedes it."""
    if not value:
        return None
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]


def strip_internal_keys(data):
    """Member-submitted credential JSON minus the tags only the server may set."""
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k not in INTERNAL_CREDENTIAL_KEYS}
    return data


def stale_household_copy(data: dict, env_value: str | None) -> bool:
    """A stored household-origin credential no longer matches the operator's
    current household token (replaced or removed), so it must not be used."""
    return data.get('origin') == 'household' and (
        not env_value or data.get('household_fp') != household_fp(env_value)
    )


def _parse_credential_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {'token': raw}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        return {'token': parsed}
    return {}


def _normalize_title_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.casefold().strip()
    return normalized or None


def _match_by_unique_normalized_name(name: str | None) -> str | None:
    """
    Best-effort match when no store-specific Game ID column exists.
    Returns a UUID only when exactly one library game shares the normalized name.
    """
    normalized = _normalize_title_name(name)
    if not normalized:
        return None
    # lower(trim()) approximates casefold for typical ASCII game titles on SQLite.
    matches = db.session.execute(
        select(Game.uuid).where(func.lower(func.trim(Game.name)) == normalized)
    ).scalars().all()
    if len(matches) == 1:
        return matches[0]
    return None


def _match_meta_quest_by_url(external_app_id: str) -> str | None:
    """Exact match on GameURL(url_type='meta_quest') when a single game links the id."""
    external_id = (external_app_id or '').strip()
    if not external_id:
        return None
    matches = db.session.execute(
        select(GameURL.game_uuid).where(
            GameURL.url_type == 'meta_quest',
            GameURL.url == external_id,
        )
    ).scalars().all()
    if len(matches) == 1:
        return matches[0]
    return None


def match_title_to_library_game(
    store: str,
    external_app_id: str,
    name: str | None = None,
) -> str | None:
    """
    Match an owned store title to a library Game UUID.
    Steam: exact match on Game.steam_app_id when present.
    Meta Quest: GameURL url_type=meta_quest exact id, else unique normalized name.
    GOG/Epic/Amazon: unique normalized name when name is provided; never multi-match.
    """
    if store == 'steam':
        try:
            app_id = int(external_app_id)
        except (TypeError, ValueError):
            return None
        matches = db.session.execute(
            select(Game.uuid).filter(Game.steam_app_id == app_id).limit(2)
        ).scalars().all()
        return matches[0] if len(matches) == 1 else None
    if store == 'meta_quest':
        by_url = _match_meta_quest_by_url(external_app_id)
        if by_url:
            return by_url
        return _match_by_unique_normalized_name(name)
    if store in _NAME_MATCH_STORES:
        return _match_by_unique_normalized_name(name)
    return None


def upsert_owned_title(
    user_id: int,
    store: str,
    external_app_id: str,
    name: str | None = None,
) -> UserOwnedTitle:
    """Insert or update a UserOwnedTitle row and attempt library matching."""
    if len(str(external_app_id)) > EXTERNAL_APP_ID_MAX:
        from oneirodex.utils.store_sync_errors import StoreSyncError
        raise StoreSyncError('A store returned an ID longer than Oneirodex records', 'invalid_response')
    name = str(name).strip()[:255] or None if name else None
    now = datetime.now(timezone.utc)
    # Only exact provider identifiers may auto-link. A name is a review hint,
    # never evidence that two editions/platforms are the same entitlement.
    matched_uuid = match_title_to_library_game(store, external_app_id)
    existing = db.session.execute(
        select(UserOwnedTitle).filter_by(
            user_id=user_id,
            store=store,
            external_app_id=str(external_app_id),
        )
        .with_for_update().execution_options(populate_existing=True)
    ).scalars().first()
    if existing:
        if name:
            existing.name = name
        # Sync refreshes source data, not a previous identity decision. A missing
        # or changed candidate must not erase/reassign an established mapping.
        # Explicit remapping and provenance require the pending review workflow.
        if existing.matched_game_uuid is None and not existing.match_reviewed:
            existing.matched_game_uuid = matched_uuid
        existing.last_synced_at = now
        return existing
    row = UserOwnedTitle(
        user_id=user_id,
        store=store,
        external_app_id=str(external_app_id),
        name=name,
        matched_game_uuid=matched_uuid,
        last_synced_at=now,
    )
    db.session.add(row)
    return row


def connect_store_account(
    user_id: int,
    store: str,
    external_account_id: str | None = None,
    credential: str | None = None,
) -> StoreAccount:
    """Link a register-only store account (optional external ID / note / secret)."""
    if store not in VALID_STORES:
        raise ValueError(f'Unsupported store: {store}')
    # The column holds 64 characters. An over-long note used to fail the INSERT,
    # and the logged DataError carried the statement parameters, credential included.
    external_account_id = (external_account_id or '').strip()[:64] or None
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def existing():
        return db.session.execute(
            select(StoreAccount).filter_by(user_id=user_id, store=store)
        ).scalars().first()

    def update(account):
        # updated_at marks a real reconnect: a new sign-in, or (Steam, where the
        # ID is what a sync uses) a different account. Re-saving a label does
        # not, so it cannot make a refused sign-in look repaired.
        if credential or (store == 'steam' and account.external_account_id != external_account_id):
            account.updated_at = now
        account.external_account_id = external_account_id
        if credential:
            account.credential = credential

    account = existing()
    if account:
        update(account)
    else:
        account = StoreAccount(
            user_id=user_id,
            store=store,
            external_account_id=external_account_id,
            credential=credential,
            # Naive UTC like every LIB-04 time. The model's aware default is
            # shifted to the session time zone by PostgreSQL on a non-UTC
            # server, and status compares this with job start times.
            created_at=now,
            updated_at=now,
        )
        db.session.add(account)
    try:
        db.session.commit()
    except IntegrityError:
        # Two connects raced (double submit). Update the row that won instead
        # of surfacing an error whose logged text would carry the credential.
        db.session.rollback()
        account = existing()
        if account is None:
            raise
        update(account)
        db.session.commit()
    return account


def disconnect_store_account(user_id: int, store: str) -> None:
    """Remove store link and clear synced titles for that store."""
    account = db.session.execute(
        select(StoreAccount).filter_by(user_id=user_id, store=store)
    ).scalars().first()
    if account:
        db.session.delete(account)
    for row in db.session.execute(
        select(UserOwnedTitle).filter_by(user_id=user_id, store=store)
    ).scalars().all():
        db.session.delete(row)
    db.session.commit()
