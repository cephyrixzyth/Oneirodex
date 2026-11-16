"""One store-connection status contract for first-run, Settings and admin repair (LIB-04).

The provider registry says what an adapter *can* do; this says where one member
stands with each provider, derived from stored facts only: operator policy, the
member's linked account, which credential a live sync would use, recorded
titles and the latest sync job. It never calls a provider and never returns a
credential, so a status of ``connected`` means "linked, and the last sync did
not fail", not "the provider would accept the token right now".

States (one per provider, several can differ at once — there is deliberately no
global success flag):

``unavailable``      no adapter exists for this service
``disabled``         the administrator turned store ownership sync off
``import_only``      snapshot import only (CSV / export file); no live listing
``not_configured``   live adapter exists but an operator prerequisite is missing
``not_connected``    ready to link
``needs_credential`` linked, but no sign-in a live sync could use
``connected``        linked; last sync succeeded, or none has run yet
``syncing``          a sync is running now
``partial``          last sync finished with an incomplete list
``reauth_required``  last sync was refused: sign-in expired or revoked
``failed``           last sync failed for another reason (see ``last_sync.outcome``)
``cancelled``        last sync was cancelled before anything was saved
"""
from __future__ import annotations

import os

from sqlalchemy import case, func, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import StoreAccount, User, UserOwnedTitle
from oneirodex.utils.store_capabilities import provider_capabilities
from datetime import timezone
from importlib import import_module

from oneirodex.utils.store_ownership_common import (
    get_epic_api_token,
    get_gog_api_token,
    get_steam_web_api_key,
    is_ownership_sync_enabled,
    unofficial_store_opt_in,
)
from oneirodex.utils.store_sync_errors import AUTH_REASONS, CONFIG_REASONS, RECONNECT_CLEARS
from oneirodex.utils.store_sync_jobs import (
    CANCELLABLE_STORES,
    LIVE_SYNC_ADAPTERS,
    iso_utc,
    is_stale,
    job_dict,
    latest_jobs,
    utcnow,
)

__all__ = ['STATES', 'member_connections', 'admin_connections', 'household_status']

STATES = (
    'unavailable', 'disabled', 'import_only', 'not_configured', 'not_connected',
    'needs_credential', 'connected', 'syncing', 'partial', 'reauth_required',
    'failed', 'cancelled',
)
#: Stores with a DELETE /api/ownership/<store> route (clears the link and titles).
_DISCONNECTABLE = frozenset(LIVE_SYNC_ADAPTERS)
_TOKEN_STORES = frozenset({'gog', 'epic', 'amazon', 'xbox', 'psn'})


def _household_token(store: str) -> bool:
    """Presence only; the value is never read into a response."""
    if store == 'gog':
        return bool(get_gog_api_token())
    if store == 'epic':
        return bool(get_epic_api_token())
    if store == 'amazon':
        from oneirodex.utils.store_ownership_amazon import household_available
        return household_available()
    if store == 'xbox':
        from oneirodex.utils.store_ownership_xbox import get_xbox_api_token
        return bool(get_xbox_api_token())
    if store == 'psn':
        from oneirodex.utils.store_ownership_psn import get_psn_api_token
        return bool(get_psn_api_token())
    return False


def _household_refresh_persists(store: str) -> bool:
    """Whether the configured household path can write refreshed tokens.

    This is presence-only status logic. GOG/Amazon only persist when a refresh
    token is configured; Xbox's adapter refreshes and persists on each sync.
    Epic and PSN do not write refreshed household credentials.
    """
    if store == 'gog':
        return bool(
            (os.getenv('GOG_REFRESH_TOKEN') or '').strip()
            or (os.getenv('GOG_API_TOKEN') or '').strip()
        )
    if store == 'amazon':
        from oneirodex.utils.store_ownership_amazon import (
            _flatten_amazon_credential,
            _household_env,
            _parse_credential_json,
        )

        raw, _access, _serial = _household_env()
        if not raw:
            return False
        if raw.lstrip().startswith('{'):
            normalized = _flatten_amazon_credential(_parse_credential_json(raw))
            return bool(normalized.get('refresh_token'))
        # The adapter treats a configured scalar household token as refresh.
        return True
    if store == 'xbox':
        from oneirodex.utils.store_ownership_xbox import get_xbox_api_token
        return bool(get_xbox_api_token())
    return False


def _credential_keyring_available() -> bool:
    from oneirodex.utils.store_credentials import (
        StoreCredentialError,
        load_store_credential_keyring,
    )

    try:
        load_store_credential_keyring()
    except StoreCredentialError:
        return False
    return True


def _credential_keyring_required(store: str, source: str, env: dict) -> bool:
    """Whether connecting/syncing this current path can require encryption."""
    if store not in _TOKEN_STORES or env['credential_keyring']:
        return False
    if source in {'migration_required', 'unavailable', 'member'}:
        return True
    if source == 'household':
        return bool(env['household_refresh_persists'].get(store, False))
    # A missing token can still be added through the connect/reconnect form;
    # identifier-only links remain allowed by the route when no secret is sent.
    return source == 'none'


def _client_package(store: str) -> bool:
    if store == 'xbox':
        from oneirodex.utils.store_ownership_xbox import client_available
        return client_available()
    if store == 'psn':
        from oneirodex.utils.store_ownership_psn import client_available
        return client_available()
    return True


def _setup_missing(store: str, provider: dict, env: dict) -> str | None:
    """Operator prerequisite for live sync that is absent, if any."""
    if store == 'steam' and not env['steam_key']:
        return 'server_key'
    if provider.get('requires_unofficial_opt_in') and not provider.get('unofficial_opted_in'):
        return 'opt_in'
    if store in ('xbox', 'psn') and not env['packages'].get(store, True):
        return 'client_package'
    return None


#: Adapters that, before LIB-04, stored the household token they had used on
#: the member's account without marking it (GOG, Amazon, Xbox).
_UNTAGGED_HOUSEHOLD_COPIES = frozenset({'gog', 'amazon', 'xbox'})


def _credential_source(store: str, account: StoreAccount | None, env: dict) -> str:
    """Which sign-in a sync would use, decided by the adapter's own resolver
    (the same function the sync calls), so status can never disagree with
    what actually runs. Reads presence only; no value leaves this function."""
    if store not in _TOKEN_STORES:
        return 'not_required'
    if account is None:
        return 'household' if env['household'].get(store) else 'none'
    module = import_module(f'oneirodex.utils.store_ownership_{store}')
    try:
        source = module.credential_source(account)
    except Exception as exc:
        from oneirodex.utils.store_credentials import (
            StoreCredentialError,
            StoreCredentialMigrationRequired,
        )

        if isinstance(exc, StoreCredentialMigrationRequired):
            return 'migration_required'
        if isinstance(exc, StoreCredentialError):
            return 'unavailable'
        raise
    if (source == 'member' and store in _UNTAGGED_HOUSEHOLD_COPIES and account.updated_at is None
            and env['household'].get(store)):
        # Saved before LIB-04 tagged household copies (updated_at is still NULL
        # from the migration). Before then these adapters wrote the household
        # token onto a member's account after a sync, untagged, so on a server
        # with a household sign-in this may be one. Say so, not 'yours'.
        return 'unknown'
    return source


def _naive(value):
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _environment() -> dict:
    return {
        'enabled': is_ownership_sync_enabled(),
        'opted_in': unofficial_store_opt_in(),
        'steam_key': bool(get_steam_web_api_key()),
        'household': {store: _household_token(store) for store in _TOKEN_STORES},
        'household_refresh_persists': {
            store: _household_refresh_persists(store) for store in _TOKEN_STORES
        },
        'credential_keyring': _credential_keyring_available(),
        'packages': {store: _client_package(store) for store in ('xbox', 'psn')},
    }


def _record_counts(user_ids) -> dict:
    rows = db.session.execute(select(
        UserOwnedTitle.user_id, UserOwnedTitle.store,
        func.count(UserOwnedTitle.id),
        func.count(UserOwnedTitle.matched_game_uuid),
        func.sum(case((UserOwnedTitle.matched_game_uuid.is_(None) & UserOwnedTitle.match_reviewed.is_(False), 1), else_=0)),
        func.max(UserOwnedTitle.last_synced_at),
    ).where(UserOwnedTitle.user_id.in_(list(user_ids))).group_by(UserOwnedTitle.user_id, UserOwnedTitle.store)).all()
    return {(r[0], r[1]): {
        'owned': int(r[2] or 0), 'matched': int(r[3] or 0),
        'needs_review': int(r[4] or 0), 'last_recorded_at': iso_utc(r[5]),
    } for r in rows}


def _derive(provider, account, records, job, env, now):
    store = provider['id']
    caps = provider['capabilities']
    has_import = caps['csv_import'] != 'unavailable' or caps['file_import'] != 'unavailable'
    live = caps['library_listing'] == 'live'
    # Xbox / PlayStation have a live adapter even while the operator has not
    # opted in; that is a missing prerequisite, not an import-only service.
    could_be_live = live or bool(provider.get('requires_unofficial_opt_in'))
    source = _credential_source(store, account, env)
    if source == 'migration_required':
        missing = 'credential_migration'
    elif source == 'unavailable':
        missing = 'credential_keyring'
    elif _credential_keyring_required(store, source, env):
        missing = 'credential_keyring'
    else:
        missing = _setup_missing(store, provider, env) if could_be_live else None
    owned = records['owned'] if records else 0
    if job is not None and account is not None and account.created_at is not None and (
        _naive(job.started_at) < _naive(account.created_at)
    ):
        # History from an earlier link (disconnected since) says nothing about this one.
        job = None
    last = job_dict(job, now)
    previous = None
    clearable = store in _DISCONNECTABLE and (account is not None or owned > 0)

    if caps['library_listing'] == 'unavailable' and not has_import:
        state, actions = 'unavailable', []
    elif account is not None and last and last['status'] == 'running':
        # A job that is actually running is reported as such, with its cancel,
        # even if sync was turned off or a prerequisite removed while it ran.
        state = 'syncing'
        actions = ['cancel'] if job.cancellable and not job.cancel_requested else []
    elif not env['enabled']:
        state, actions = 'disabled', []
    elif source in {'migration_required', 'unavailable'}:
        state = 'not_configured'
        actions = ['import_csv'] + (['disconnect'] if clearable else [])
    elif not could_be_live:
        state = 'import_only'
        actions = ['import_csv'] if caps['csv_import'] != 'unavailable' else []
        if caps['file_import'] != 'unavailable':
            actions.append('import_file')
        if clearable:
            actions.append('disconnect')
    elif missing:
        state, actions = 'not_configured', ['import_csv'] + (['disconnect'] if clearable else [])
        if store == 'steam' and missing == 'server_key':
            # A Steam ID needs no key: free-game claims record the title and
            # open Steam with it. Only the live library read needs the key.
            actions.insert(0, 'reconnect' if account is not None else 'connect')
        elif missing == 'credential_keyring':
            # The link can still be identifier-only. A token submission is
            # guarded by the same key-ring check in the connect route.
            actions.insert(0, 'reconnect' if account is not None else 'connect')
    elif account is None:
        state, actions = 'not_connected', ['connect', 'import_csv'] + (['disconnect'] if clearable else [])
    elif source == 'none':
        state, actions = 'needs_credential', ['reconnect', 'import_csv', 'disconnect']
    else:
        reason = last['outcome']['reason'] if last and last['outcome'] else None
        # A sign-in failure followed by a real reconnect (a new sign-in saved),
        # or a configuration failure the operator has since fixed, no longer
        # describes the account: keep it as history, report the current link.
        reconnected = (
            reason in RECONNECT_CLEARS and job.finished_at is not None and account.updated_at is not None
            and _naive(account.updated_at) > _naive(job.finished_at)
        )
        config_fixed = reason in CONFIG_REASONS and last['status'] == 'failed'
        if last is None or reconnected or config_fixed or last['status'] == 'succeeded':
            state = 'connected'
            if (reconnected or config_fixed) and last['status'] != 'succeeded':
                previous, last = last, None
        elif last['status'] == 'partial':
            state = 'partial'
        elif last['status'] == 'cancelled':
            state = 'cancelled'
        elif last['outcome'] and last['outcome']['reason'] in AUTH_REASONS:
            state = 'reauth_required'
        else:
            state = 'failed'
        actions = (['reconnect'] if state == 'reauth_required' else ['sync', 'reconnect']) + ['import_csv', 'disconnect']

    return {
        'provider': store,
        'name': provider['name'],
        'authority': provider['authority'],
        'state': state,
        'live': bool(live and env['enabled']),
        'cancellable': store in CANCELLABLE_STORES,
        'setup': {'ready': missing is None, 'missing': missing},
        'credential': {
            'source': source,
            'household_available': bool(env['household'].get(store, False)),
            'keyring_available': bool(env.get('credential_keyring', False)),
        },
        'account': {
            'connected': account is not None,
            'linked_at': iso_utc(account.created_at) if account else None,
            'updated_at': iso_utc(account.updated_at) if account else None,
        },
        'records': records or {'owned': 0, 'matched': 0, 'needs_review': 0, 'last_recorded_at': None},
        'last_sync': last,
        'previous_failure': previous,
        'actions': actions,
    }


def member_connections(user) -> dict:
    """Status of every registered provider for one member."""
    env = _environment()
    providers = provider_capabilities(enabled=env['enabled'], unofficial_stores=env['opted_in'])
    accounts = {a.store: a for a in db.session.execute(
        select(StoreAccount).where(StoreAccount.user_id == user.id)
    ).scalars()}
    counts = _record_counts([user.id])
    jobs = latest_jobs([user.id])
    now = utcnow()
    connections = []
    for provider in providers:
        store = provider['id']
        entry = _derive(provider, accounts.get(store), counts.get((user.id, store)), jobs.get((user.id, store)), env, now)
        entry['account']['external_account_id'] = accounts[store].external_account_id if store in accounts else None
        connections.append(entry)
    return {'schema_version': 1, 'sync_enabled': env['enabled'], 'connections': connections}


def household_status() -> dict:
    """Operator configuration as presence flags only (admin)."""
    env = _environment()
    return {
        'sync_enabled': env['enabled'],
        'steam_server_key': env['steam_key'],
        'unofficial_opt_in': sorted(env['opted_in']),
        'household_tokens': {store: env['household'][store] for store in sorted(_TOKEN_STORES)},
        'optional_packages': env['packages'],
    }


def admin_connections(*, after_id: int = 0, limit: int = 50) -> dict:
    """Redacted per-member diagnostics for linked or recorded stores.

    Returns states, reason codes, counts and credential *source* only: no
    credential, external account ID, title names or upstream text.
    """
    env = _environment()
    providers = {p['id']: p for p in provider_capabilities(enabled=env['enabled'], unofficial_stores=env['opted_in'])}
    users = db.session.execute(
        select(User.id, User.name).where(User.id > after_id).where(
            User.id.in_(select(StoreAccount.user_id)) | User.id.in_(select(UserOwnedTitle.user_id))
        ).order_by(User.id).limit(limit + 1)
    ).all()
    page = users[:limit]
    ids = [u.id for u in page]
    accounts = {(a.user_id, a.store): a for a in db.session.execute(
        select(StoreAccount).where(StoreAccount.user_id.in_(ids))
    ).scalars()} if ids else {}
    counts = _record_counts(ids) if ids else {}
    jobs = latest_jobs(ids) if ids else {}
    now = utcnow()
    members = []
    for uid, name in page:
        stores = sorted({s for (u, s) in accounts if u == uid} | {s for (u, s) in counts if u == uid} | {s for (u, s) in jobs if u == uid})
        rows = []
        for store in stores:
            provider = providers.get(store)
            if provider is None:
                continue
            entry = _derive(provider, accounts.get((uid, store)), counts.get((uid, store)), jobs.get((uid, store)), env, now)
            entry.pop('actions')
            job = jobs.get((uid, store))
            # Retry uses the member's own saved sign-in, so it cannot help when
            # that sign-in is missing or was refused; only the member can fix those.
            entry['admin_actions'] = (
                ['cancel'] if entry['state'] == 'syncing' and job is not None and job.cancellable and not job.cancel_requested
                else ['sync'] if entry['live'] and entry['account']['connected'] and entry['state'] in ('connected', 'partial', 'failed', 'cancelled')
                else []
            )
            rows.append(entry)
        members.append({'user_id': uid, 'name': name, 'stores': rows})
    return {
        'schema_version': 1,
        'household': household_status(),
        'members': members,
        'next_after_id': page[-1].id if len(users) > limit else None,
        'stale_running_jobs': sum(1 for job in jobs.values() if is_stale(job, now)),
    }
