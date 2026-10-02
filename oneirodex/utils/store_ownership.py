"""
Register-only store ownership sync.

Records which titles a user owns according to external store APIs or CSV import.
NEVER downloads games, DRM payloads, or store clients — ownership data is used
solely to annotate library browse/discover cards (owned / store_owned badges).

GOG/Epic matching: Game has no dedicated gog_id/epic_id columns today. When a
CSV row includes a title name, we match on normalized name (casefold + strip)
only when exactly one library game matches; ambiguous or nameless rows stay
unmatched until an admin links them manually.

The v11 cycle (H-D.4) split this by store as pure moves: shared plumbing in
``store_ownership_common``, one module each for GOG / Epic / Amazon. Steam,
the CSV imports and the summary stay here, and every name callers import still
resolves here.
"""

from __future__ import annotations

import csv
import io

from sqlalchemy import func, select

from oneirodex import db
from oneirodex.models import StoreAccount, UserOwnedTitle
# H-D.4 split: these moved to sibling modules as pure moves. Public names are
# re-exported here because callers and tests import them from this module.
from oneirodex.utils.store_ownership_amazon import (  # noqa: F401
    amazon_live_ready,
    connect_amazon_account,
    disconnect_amazon_account,
    sync_amazon_owned_games,
    _flatten_amazon_credential,
)
from oneirodex.utils.store_ownership_psn import (  # noqa: F401
    connect_psn_account,
    disconnect_psn_account,
    get_psn_api_token,
    psn_live_ready,
    sync_psn_owned_games,
)
from oneirodex.utils.store_ownership_xbox import (  # noqa: F401
    connect_xbox_account,
    disconnect_xbox_account,
    get_xbox_api_token,
    sync_xbox_owned_games,
    xbox_live_ready,
)
from oneirodex.utils.store_ownership_common import (  # noqa: F401
    EXTERNAL_APP_ID_MAX,
    connect_store_account,
    disconnect_store_account,
    get_amazon_api_token,
    get_epic_api_token,
    get_gog_api_token,
    get_steam_web_api_key,
    is_ownership_sync_enabled,
    match_title_to_library_game,
    store_sync_mode,
    STORE_SYNC_MODE,
    unofficial_store_opt_in,
    UNOFFICIAL_OPT_IN_STORES,
    upsert_owned_title,
    VALID_STORES,
    _any_account_credential,
    _CSV_ID_HEADERS,
    _match_by_unique_normalized_name,
    _match_meta_quest_by_url,
    _NAME_MATCH_STORES,
    _normalize_title_name,
    _outbound,
    _parse_credential_json,
)
from oneirodex.utils.store_ownership_epic import (  # noqa: F401
    connect_epic_account,
    disconnect_epic_account,
    epic_live_ready,
    sync_epic_owned_games,
)
from oneirodex.utils.store_ownership_gog import (  # noqa: F401
    connect_gog_account,
    disconnect_gog_account,
    gog_live_ready,
    sync_gog_owned_games,
)
from oneirodex.utils.store_sync_errors import StoreSyncError, StoreSyncPermissionError
from oneirodex.utils.store_sync_jobs import mark_warning


def get_matched_owned_game_uuids(user_id: int) -> set[str]:
    rows = db.session.execute(
        select(UserOwnedTitle.matched_game_uuid).where(
            UserOwnedTitle.user_id == user_id,
            UserOwnedTitle.matched_game_uuid.isnot(None),
        )
    ).all()
    return {row[0] for row in rows}


def ownership_flags(game_uuid: str, owned_uuids: set[str]) -> dict:
    owned = game_uuid in owned_uuids
    return {
        'owned': owned,
        'store_owned': owned,
    }


def connect_steam_account(user_id: int, steam_id: str) -> StoreAccount:
    steam_id = steam_id.strip()
    if not steam_id.isdigit():
        raise ValueError('Steam ID must be numeric')
    return connect_store_account(user_id, 'steam', steam_id)


def disconnect_steam_account(user_id: int) -> None:
    disconnect_store_account(user_id, 'steam')


def sync_steam_owned_games(user_id: int) -> dict:
    """
    Fetch owned games via Steam Web API GetOwnedGames and upsert UserOwnedTitle rows.
    Register-only: records app IDs and names; does not download anything.
    """
    if not is_ownership_sync_enabled():
        raise StoreSyncPermissionError('Store ownership sync is disabled by administrator', 'sync_disabled')

    api_key = get_steam_web_api_key()
    if not api_key:
        raise StoreSyncError(
            'Steam Web API key not configured (set STEAM_WEB_API_KEY env or admin setting)',
            'server_key_missing',
        )

    account = db.session.execute(
        select(StoreAccount).filter_by(user_id=user_id, store='steam')
    ).scalars().first()
    if not account or not account.external_account_id:
        raise StoreSyncError('Steam account not connected', 'not_connected')

    url = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/'
    params = {
        'key': api_key,
        'steamid': account.external_account_id,
        'include_appinfo': 1,
        'include_played_free_games': 1,
        'format': 'json',
    }
    resp = _outbound('GET', url, params=params)
    # The request URL carries the server key, and requests' HTTPError text
    # includes that URL, so no raw exception from here may reach a response.
    if resp.status_code in (401, 403):
        raise StoreSyncError('Steam refused the server key for this request', 'access_denied')
    resp.raise_for_status()
    data = resp.json()
    response = data.get('response') if isinstance(data, dict) else None
    response = response if isinstance(response, dict) else {}
    games = response.get('games') or []
    if 'games' not in response and 'game_count' not in response:
        # Steam answers a private (or friends-only) game list with an empty
        # object. That is not "owns nothing", so say so instead of implying it.
        mark_warning('library_not_visible')

    matched = 0
    for game in games:
        app_id = game.get('appid')
        if app_id is None:
            continue
        row = upsert_owned_title(user_id, 'steam', str(app_id), game.get('name'))
        if row.matched_game_uuid:
            matched += 1
    db.session.commit()
    return {'synced': len(games), 'matched': matched, 'store': 'steam'}


def _parse_store_csv_row(row: list[str], store: str) -> tuple[str, str | None] | None:
    if not row:
        return None
    external_id = row[0].strip()
    if not external_id or external_id.lower() in _CSV_ID_HEADERS:
        return None
    if store == 'steam' and not external_id.isdigit():
        return None
    name = None
    if len(row) > 1:
        name_cell = row[1].strip()
        if name_cell and name_cell.lower() != 'name':
            name = name_cell
    return external_id, name


def import_store_csv(user_id: int, store: str, csv_text: str) -> dict:
    """
    Import owned titles from CSV (register-only manual sync).
    Accepts product IDs in the first column, optional name in the second.
    """
    if store not in VALID_STORES:
        raise ValueError(f'Unsupported store: {store}')
    if not is_ownership_sync_enabled():
        raise PermissionError('Store ownership sync is disabled by administrator')

    reader = csv.reader(io.StringIO(csv_text))
    count = 0
    matched = 0
    skipped = 0
    for row in reader:
        parsed = _parse_store_csv_row(row, store)
        if not parsed:
            continue
        external_id, name = parsed
        if len(external_id) > EXTERNAL_APP_ID_MAX:
            skipped += 1
            continue
        title_row = upsert_owned_title(user_id, store, external_id, name)
        count += 1
        if title_row.matched_game_uuid:
            matched += 1
    db.session.commit()
    return {'imported': count, 'matched': matched, 'skipped': skipped, 'store': store}


def import_steam_csv(user_id: int, csv_text: str) -> dict:
    return import_store_csv(user_id, 'steam', csv_text)


def import_gog_csv(user_id: int, csv_text: str) -> dict:
    return import_store_csv(user_id, 'gog', csv_text)


def import_epic_csv(user_id: int, csv_text: str) -> dict:
    return import_store_csv(user_id, 'epic', csv_text)


def import_amazon_csv(user_id: int, csv_text: str) -> dict:
    return import_store_csv(user_id, 'amazon', csv_text)


def import_xbox_csv(user_id: int, csv_text: str) -> dict:
    """Register-only Xbox ownership import (title ids / PFNs + names)."""
    return import_store_csv(user_id, 'xbox', csv_text)


def import_psn_csv(user_id: int, csv_text: str) -> dict:
    """Register-only PlayStation ownership import (title ids + names)."""
    return import_store_csv(user_id, 'psn', csv_text)


def import_meta_quest_csv(user_id: int, csv_text: str) -> dict:
    """Register-only Meta/Quest ownership import (never downloads DRM titles)."""
    return import_store_csv(user_id, 'meta_quest', csv_text)


def get_ownership_summary(user_id: int) -> dict:
    accounts = db.session.execute(
        select(StoreAccount).filter_by(user_id=user_id)
    ).scalars().all()
    account_by_store = {account.store: account for account in accounts}

    total_owned = db.session.execute(
        select(func.count(UserOwnedTitle.id)).filter_by(user_id=user_id)
    ).scalar() or 0
    total_matched = db.session.execute(
        select(func.count(UserOwnedTitle.id)).where(
            UserOwnedTitle.user_id == user_id,
            UserOwnedTitle.matched_game_uuid.isnot(None),
        )
    ).scalar() or 0

    stores = {}
    for store in sorted(VALID_STORES):
        owned_count = db.session.execute(
            select(func.count(UserOwnedTitle.id)).filter_by(user_id=user_id, store=store)
        ).scalar() or 0
        matched_count = db.session.execute(
            select(func.count(UserOwnedTitle.id)).where(
                UserOwnedTitle.user_id == user_id,
                UserOwnedTitle.store == store,
                UserOwnedTitle.matched_game_uuid.isnot(None),
            )
        ).scalar() or 0
        account = account_by_store.get(store)
        # Newest row wins: a register is only as current as its most recent
        # entry, and that is what someone means by "when did this last update".
        last_seen = db.session.execute(
            select(func.max(UserOwnedTitle.last_synced_at)).filter_by(
                user_id=user_id, store=store,
            )
        ).scalar()

        mode = store_sync_mode(store)
        unofficial = store in UNOFFICIAL_OPT_IN_STORES
        stores[store] = {
            # INSP-42: an unofficial store says so, and whether the operator
            # opted its live sync in; off means CSV snapshot and the UI says it.
            'unofficial': unofficial,
            'opt_in': (store in unofficial_store_opt_in()) if unofficial else None,
            'connected': account is not None,
            'external_account_id': account.external_account_id if account else None,
            'has_credential': bool(account.credential) if account else False,
            'owned_count': owned_count,
            'matched_count': matched_count,
            # The UI needs to be able to say "snapshot from 3 weeks ago" rather
            # than presenting a stale list as though it were current.
            'sync_mode': mode,
            'live_sync': mode == 'live',
            'last_synced_at': last_seen.isoformat() if last_seen else None,
        }

    return {
        'enabled': is_ownership_sync_enabled(),
        'has_steam_api_key': get_steam_web_api_key() is not None,
        'has_gog_api_key': get_gog_api_token() is not None,
        'has_epic_api_key': get_epic_api_token() is not None,
        'has_amazon_api_key': get_amazon_api_token() is not None,
        'has_xbox_api_key': get_xbox_api_token() is not None,
        'has_psn_api_key': get_psn_api_token() is not None,
        'unofficial_opt_in': sorted(unofficial_store_opt_in()),
        'stores': stores,
        'total_owned': total_owned,
        'total_matched': total_matched,
    }
