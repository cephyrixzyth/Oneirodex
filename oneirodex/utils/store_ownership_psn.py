"""PlayStation Network ownership register via the unofficial ``psnawp``
client (INSP-42, v11 H4a). **Register-only, opt-in, unofficial.**

A member's own ``npsso`` token (copied from a signed-in browser session, the
way every community tool does it) lets the client list the account's title
history -- ids and names -- which we write to the ownership register so a
card can say *Owned on PlayStation*. Nothing here downloads, installs or
touches a console.

* **Opt-in.** Live sync runs only when ``ENABLE_UNOFFICIAL_STORE_SYNC`` names
  ``psn``; otherwise the store is a CSV snapshot. Default off (gate G5).
* **Optional extra.** ``psnawp`` is imported lazily; missing -> plugin
  *available*, sync says which package to install. CSV needs nothing.
* **The token is the member's.** Stored on their ``StoreAccount``, never
  logged; a rejected token fails closed with one sentence.
"""
from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import select

from oneirodex import db
from oneirodex.models import StoreAccount
from oneirodex.utils.store_ownership_common import (
    _any_account_credential,
    _parse_credential_json,
    connect_store_account,
    disconnect_store_account,
    is_ownership_sync_enabled,
    unofficial_store_opt_in,
    upsert_owned_title,
)
from oneirodex.utils.store_sync_errors import StoreSyncError, StoreSyncPermissionError, rejected_reason

STORE = 'psn'
PACKAGE = 'psnawp'
INSTALL_HINT = f'PlayStation live sync needs the optional {PACKAGE} package (pip install {PACKAGE}). CSV import works without it.'


def client_available() -> bool:
    try:
        import psnawp_api  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def get_psn_api_token() -> str | None:
    """Household npsso from env -- fallback when a member saved none."""
    return (os.getenv('PSN_NPSSO') or '').strip() or None


def psn_live_ready() -> bool:
    if STORE not in unofficial_store_opt_in() or not client_available():
        return False
    return bool(get_psn_api_token()) or _any_account_credential(STORE)


def connect_psn_account(
    user_id: int,
    online_id: str | None = None,
    note: str | None = None,
    npsso: str | None = None,
) -> StoreAccount:
    external_id = (online_id or note or '').strip() or None
    payload = {'npsso': npsso.strip()} if (npsso or '').strip() else {}
    cred_json = json.dumps(payload) if payload else None
    return connect_store_account(user_id, STORE, external_id, credential=cred_json)


def disconnect_psn_account(user_id: int) -> None:
    disconnect_store_account(user_id, STORE)


def _npsso_source(account: StoreAccount) -> tuple[str, str | None]:
    """(npsso, origin): the member's own token, else the household PSN_NPSSO."""
    data = _parse_credential_json(account.credential)
    token = str(data.get('npsso') or data.get('token') or '').strip()
    if token:
        return token, None
    household = get_psn_api_token() or ''
    return household, ('household' if household else None)


def _npsso_for(account: StoreAccount) -> str:
    return _npsso_source(account)[0]


def credential_source(account: StoreAccount) -> str:
    """member | household | none, by the same selection the sync makes."""
    token, origin = _npsso_source(account)
    if not token:
        return 'none'
    return 'household' if origin == 'household' else 'member'


def _psn_titles(npsso: str) -> tuple[list[tuple[str, str | None]], str | None]:
    """Title ids + names from the account's title stats, via the unofficial
    client; also the online id when the client reports it. Tests patch this."""
    from psnawp_api import PSNAWP

    client = PSNAWP(npsso)
    me = client.me()
    online_id = getattr(me, 'online_id', None)
    rows: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for stat in me.title_stats(limit=1000):
        tid = str(getattr(stat, 'title_id', '') or '').strip()
        if tid and tid not in seen:
            seen.add(tid)
            rows.append((tid, getattr(stat, 'name', None)))
    return rows, (str(online_id) if online_id else None)


def sync_psn_owned_games(user_id: int) -> dict[str, Any]:
    """Register IDs and names from the PSN title history. Never downloads."""
    if not is_ownership_sync_enabled():
        raise StoreSyncPermissionError('Store ownership sync is disabled by administrator', 'sync_disabled')
    if STORE not in unofficial_store_opt_in():
        raise StoreSyncPermissionError(
            'PlayStation live sync is opt-in: set ENABLE_UNOFFICIAL_STORE_SYNC=psn on the server. CSV import works without it.',
            'opt_in_required',
        )
    if not client_available():
        raise StoreSyncError(INSTALL_HINT, 'client_package_missing')
    account = db.session.execute(
        select(StoreAccount).filter_by(user_id=user_id, store=STORE)
    ).scalars().first()
    if not account:
        raise StoreSyncError('PlayStation account not connected', 'not_connected')
    npsso, origin = _npsso_source(account)
    if not npsso:
        raise StoreSyncError('PlayStation live sync needs an npsso token. CSV import works without it.', 'credential_missing')
    try:
        rows, online_id = _psn_titles(npsso)
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if '401' in text or 'Unauthorized' in text or 'npsso' in text.lower():
            raise StoreSyncError('PlayStation rejected the saved npsso (unofficial psnawp client). Paste a fresh token; CSV import still works.', rejected_reason(origin)) from exc
        raise StoreSyncError(f'PlayStation sync failed: {type(exc).__name__}', 'upstream_unavailable') from exc
    # Never label a member's link with the household account's online ID.
    if online_id and not account.external_account_id and origin != 'household':
        account.external_account_id = online_id[:64]
    matched = 0
    for title_id, name in rows:
        row = upsert_owned_title(user_id, STORE, title_id, name)
        if row.matched_game_uuid:
            matched += 1
    db.session.commit()
    return {'synced': len(rows), 'matched': matched, 'store': STORE}
