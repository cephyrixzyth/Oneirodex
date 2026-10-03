"""Sync every linked store for a member in one call.

Each store still runs as its own recorded job (:func:`run_store_sync`), so a
failure in one store is reported against that store and never stops the rest.
Stores the member has not linked, and live stores the operator has not enabled,
are listed as ``skipped`` with a reason instead of being silently dropped.
"""
from __future__ import annotations

from sqlalchemy import select

from oneirodex import db
from oneirodex.models import StoreAccount
from oneirodex.utils.store_ownership_common import store_sync_mode
from oneirodex.utils.store_sync_errors import SyncOutcomeError
from oneirodex.utils.store_sync_jobs import LIVE_SYNC_ADAPTERS, run_store_sync

__all__ = ['sync_all_stores']


def sync_all_stores(user_id: int, *, trigger: str = 'member', actor_id: int | None = None) -> list[dict]:
    linked = set(
        db.session.execute(select(StoreAccount.store).where(StoreAccount.user_id == user_id)).scalars()
    )
    results: list[dict] = []
    for store in LIVE_SYNC_ADAPTERS:
        if store not in linked:
            results.append({'store': store, 'status': 'skipped', 'reason': 'not_connected'})
            continue
        if store_sync_mode(store) != 'live':
            results.append({'store': store, 'status': 'skipped', 'reason': 'opt_in_required'})
            continue
        try:
            outcome = run_store_sync(user_id, store, trigger=trigger, actor_id=actor_id)
        except SyncOutcomeError as exc:
            results.append({'store': store, 'status': 'failed', 'reason': exc.reason})
            continue
        job = outcome['job']
        entry = {'store': store, 'status': job.status, 'reason': outcome['reason']}
        result = outcome['result'] or {}
        for key in ('synced', 'matched'):
            if key in result:
                entry[key] = result[key]
        results.append(entry)
    return results
