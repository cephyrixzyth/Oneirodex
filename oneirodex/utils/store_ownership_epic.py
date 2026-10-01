"""Epic Games ownership register via the launcher's public client
(unofficial surface, as Legendary / Heroic use). Register IDs and names
only; never downloads.

Split out of ``store_ownership`` in the v11 cycle (H-D.4) as a pure move.
"""
from __future__ import annotations

import base64
import json
import os

from sqlalchemy import select

from oneirodex import db
from oneirodex.models import StoreAccount
from oneirodex.utils.store_ownership_common import (
    connect_store_account,
    disconnect_store_account,
    get_epic_api_token,
    is_ownership_sync_enabled,
    upsert_owned_title,
    _any_account_credential,
    _outbound,
    _parse_credential_json,
    strip_internal_keys,
)
from oneirodex.utils.store_sync_errors import StoreSyncError, StoreSyncPermissionError, rejected_reason
from oneirodex.utils.store_sync_jobs import checkpoint, mark_partial

#: Library pages read per sync. Hitting it with a cursor left means the list is
#: incomplete, which the job reports instead of presenting as the whole library.
_EPIC_MAX_PAGES = 20


# Epic Games Launcher public client (Legendary / Heroic). Same unofficial
# surface warning as GOG. Override with EPIC_CLIENT_ID / EPIC_CLIENT_SECRET.
_EPIC_LAUNCHER_CLIENT_ID = '34a02cf8f4414e29b15921876da36f9a'
_EPIC_LAUNCHER_CLIENT_SECRET = 'daafbccc737745186e330d496dd2ea9d'
_EPIC_TOKEN_URL = (
    'https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token'
)
_EPIC_LIBRARY_URL = (
    'https://library-service.live.use1a.on.epicgames.com/library/api/public/items'
)


def epic_live_ready() -> bool:
    return bool(get_epic_api_token()) or _any_account_credential('epic')


def _epic_client_pair() -> tuple[str, str]:
    client_id = (os.getenv('EPIC_CLIENT_ID') or '').strip() or _EPIC_LAUNCHER_CLIENT_ID
    client_secret = (
        (os.getenv('EPIC_CLIENT_SECRET') or '').strip() or _EPIC_LAUNCHER_CLIENT_SECRET
    )
    return client_id, client_secret


def _epic_device_auth_for(account: StoreAccount) -> dict:
    # The household device auth is used only when the member saved nothing.
    # An incomplete member paste (e.g. a Legendary user.json) is reported as
    # incomplete rather than silently syncing the household account's library.
    data = _parse_credential_json(account.credential)
    if data:
        return data
    env_raw = get_epic_api_token()
    env_data = _parse_credential_json(env_raw) if env_raw else {}
    if env_data:
        env_data = {**env_data, 'origin': 'household'}
    return env_data


def credential_source(account: StoreAccount) -> str:
    """member | household | none, by the same selection the sync makes."""
    device = _epic_device_auth_for(account)
    if not (device.get('account_id') and device.get('device_id') and device.get('secret')):
        return 'none'
    return 'household' if device.get('origin') == 'household' else 'member'


def _epic_access_token(account: StoreAccount, device: dict) -> str:
    account_id = (device.get('account_id') or '').strip()
    device_id = (device.get('device_id') or '').strip()
    secret = (device.get('secret') or '').strip()
    if not (account_id and device_id and secret):
        raise StoreSyncError(
            'Epic live sync needs device auth JSON '
            '(account_id, device_id, secret) from Legendary/Heroic, or '
            'EPIC_DEVICE_AUTH. CSV import still works without it.',
            'credential_missing',
        )
    client_id, client_secret = _epic_client_pair()
    basic = base64.b64encode(f'{client_id}:{client_secret}'.encode('ascii')).decode('ascii')
    resp = _outbound(
        'POST',
        _EPIC_TOKEN_URL,
        headers={
            'Authorization': f'Basic {basic}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        data={
            'grant_type': 'device_auth',
            'account_id': account_id,
            'device_id': device_id,
            'secret': secret,
        },
    )
    # A revoked or deleted device auth is answered with 400 invalid_grant as
    # well as 401; either way only a new device auth fixes it.
    if resp.status_code in (400, 401):
        raise StoreSyncError(
            'Epic rejected the saved device auth (unofficial launcher client). '
            'Paste a new device-auth JSON; CSV import still works.',
            rejected_reason(device.get('origin')),
        )
    resp.raise_for_status()
    payload = resp.json() if resp.content else {}
    access = (payload.get('access_token') or '').strip()
    if not access:
        raise StoreSyncError('Epic device auth returned no access token', 'invalid_response')
    display = (payload.get('displayName') or payload.get('account_id') or '').strip()
    # Never label a member's link with the household account's identity.
    if display and not account.external_account_id and device.get('origin') != 'household':
        account.external_account_id = display[:64]
        db.session.commit()
    return access


def _epic_library_items(access_token: str, origin: str | None = None) -> list[tuple[str, str | None]]:
    items: list[tuple[str, str | None]] = []
    cursor = None
    for _ in range(_EPIC_MAX_PAGES):
        checkpoint()
        params = {'includeMetadata': 'true'}
        if cursor:
            params['cursor'] = cursor
        resp = _outbound(
            'GET',
            _EPIC_LIBRARY_URL,
            headers={'Authorization': f'bearer {access_token}'},
            params=params,
        )
        if resp.status_code == 401:
            raise StoreSyncError(
                'Epic library request was rejected. Paste a new device-auth JSON.',
                rejected_reason(origin),
            )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        records = (
            payload.get('records')
            or payload.get('elements')
            or payload.get('items')
            or []
        )
        if isinstance(records, dict):
            records = list(records.values())
        for row in records:
            if not isinstance(row, dict):
                continue
            catalog_id = (
                row.get('catalogItemId')
                or row.get('catalogItemID')
                or row.get('id')
                or row.get('appName')
            )
            if not catalog_id:
                continue
            meta = row.get('metadata') if isinstance(row.get('metadata'), dict) else {}
            name = row.get('title') or meta.get('title') or row.get('appName')
            items.append((str(catalog_id), str(name) if name else None))
        meta = payload.get('responseMetadata') or payload.get('paging') or {}
        cursor = meta.get('nextCursor') or meta.get('cursor') or None
        checkpoint(pages=1, items=len(records))
        if not cursor:
            break
    else:
        mark_partial('page_limit')
    return items


def connect_epic_account(
    user_id: int,
    epic_account_id: str | None = None,
    note: str | None = None,
    device_auth: str | dict | None = None,
) -> StoreAccount:
    external_id = (epic_account_id or note or '').strip() or None
    credential = None
    if isinstance(device_auth, dict) and device_auth:
        credential = json.dumps(strip_internal_keys(device_auth))
    elif isinstance(device_auth, str) and device_auth.strip():
        raw = device_auth.strip()
        parsed = _parse_credential_json(raw)
        credential = json.dumps(strip_internal_keys(parsed)) if parsed else raw
    return connect_store_account(user_id, 'epic', external_id, credential=credential)


def disconnect_epic_account(user_id: int) -> None:
    disconnect_store_account(user_id, 'epic')


def sync_epic_owned_games(user_id: int) -> dict:
    """Fetch owned Epic catalog items via unofficial launcher device auth.

    Register-only: records IDs and names; does not download anything.
    """
    if not is_ownership_sync_enabled():
        raise StoreSyncPermissionError('Store ownership sync is disabled by administrator', 'sync_disabled')

    account = db.session.execute(
        select(StoreAccount).filter_by(user_id=user_id, store='epic')
    ).scalars().first()
    if not account:
        raise StoreSyncError('Epic account not connected', 'not_connected')

    device = _epic_device_auth_for(account)
    access = _epic_access_token(account, device)
    items = _epic_library_items(access, device.get('origin'))
    matched = 0
    for catalog_id, name in items:
        row = upsert_owned_title(user_id, 'epic', catalog_id, name)
        if row.matched_game_uuid:
            matched += 1
    db.session.commit()
    return {'synced': len(items), 'matched': matched, 'store': 'epic'}
