"""P0-02: delayed provider responses across real PostgreSQL requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Event

import pytest
from sqlalchemy import func, select, update

from tests.fixtures.faults import DelayedProvider


@pytest.mark.parametrize('change', ['disconnect', 'reconnect'])
def test_delayed_store_response_cannot_overwrite_a_newer_link(
    app, no_savepoint_db, tmp_path, monkeypatch, reusable_secret_keyring, change,
):
    from oneirodex import db
    from oneirodex.models import StoreAccount, StoreSyncJob, UserOwnedTitle
    from oneirodex.utils import store_ownership_common as stores, store_sync_jobs as jobs
    from oneirodex.utils.store_credentials import read_store_credential
    from tests.fixtures.household_safety import seed_household

    household = seed_household(app, no_savepoint_db, tmp_path, monkeypatch)
    uid = household.users['member'].id
    initial = json.dumps({'refresh_token': 'synthetic-original'})
    newer = json.dumps({'refresh_token': 'synthetic-newer'})
    stale = json.dumps({'refresh_token': 'synthetic-stale'})
    stores.connect_store_account(uid, 'gog', 'fixture-account', credential=initial)
    provider = DelayedProvider(stale)
    fenced = Event()

    def provider_and_publish(user_id):
        account = db.session.execute(
            select(StoreAccount).filter_by(user_id=user_id, store='gog'),
        ).scalar_one()
        assert read_store_credential(account) == initial
        refreshed = provider()
        try:
            stores.connect_store_account(user_id, 'gog', 'fixture-account', credential=refreshed)
        except jobs.SyncSlotLost:
            fenced.set()
            raise
        stores.upsert_owned_title(user_id, 'gog', 'late-title', 'Synthetic late title')
        db.session.commit()
        return {'synced': 1, 'matched': 0}

    def synchronize():
        with app.app_context():
            result = jobs.run_store_sync(
                uid, 'gog', trigger='member', actor_id=uid, sync_fn=provider_and_publish,
            )
            return result['job'].status, result['reason'], result['result']

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(synchronize)
        try:
            assert provider.entered.wait(timeout=10), 'Provider boundary was not reached'
            # A live sync still owns the slot: normal reconnect must refuse.
            with pytest.raises(jobs.SyncOutcomeError) as busy:
                jobs.exclusive_link_change(
                    uid, 'gog', 'connect',
                    lambda: stores.connect_store_account(uid, 'gog', credential=newer),
                )
            assert busy.value.reason == 'sync_in_progress'
            no_savepoint_db.expire_all()
            current = no_savepoint_db.execute(
                select(StoreAccount).filter_by(user_id=uid, store='gog'),
            ).scalar_one()
            assert read_store_credential(current) == initial
            running = no_savepoint_db.execute(
                select(StoreSyncJob).filter_by(user_id=uid, store='gog', status='running'),
            ).scalar_one()
            # Advance the persisted heartbeat, not wall time or the locking code.
            no_savepoint_db.execute(
                update(StoreSyncJob).where(StoreSyncJob.id == running.id).values(
                    heartbeat_at=jobs.utcnow() - timedelta(minutes=11),
                ),
            )
            no_savepoint_db.commit()
            if change == 'disconnect':
                jobs.exclusive_link_change(
                    uid, 'gog', 'disconnect',
                    lambda: stores.disconnect_store_account(uid, 'gog'), clear_history=True,
                )
            else:
                jobs.exclusive_link_change(
                    uid, 'gog', 'connect',
                    lambda: stores.connect_store_account(uid, 'gog', 'fixture-account', credential=newer),
                )
        finally:
            provider.release.set()
        assert pending.result(timeout=10) == ('failed', 'interrupted', None)
        assert fenced.is_set(), 'Actual stale commit fence must reject the provider publication'

    no_savepoint_db.expire_all()
    account = no_savepoint_db.execute(
        select(StoreAccount).filter_by(user_id=uid, store='gog'),
    ).scalar_one_or_none()
    if change == 'disconnect':
        assert account is None
    else:
        assert account.credential is None
        assert read_store_credential(account) == newer
    assert no_savepoint_db.execute(
        select(func.count()).select_from(UserOwnedTitle).where(UserOwnedTitle.user_id == uid),
    ).scalar_one() == 0
    assert household.legacy_path.read_bytes() == b'legacy-fixture'
    assert household.unrelated_path.read_bytes() == b'unrelated-fixture'
