"""Background re-sync for linked store accounts (GT-B27).

Why this exists
---------------
`sync_steam_owned_games` has always worked, but nothing ever ran it again.
Linking a Steam account synced once, at the moment you linked it, and the
register was stale from the next purchase onward — which makes a *linked*
account behave no better than the CSV import it was supposed to improve on.

That is the reported gap: "gaming services we link to need to sync to the
service like Steam does, not just an upload that won't stay up to date." Steam
already had the live call; what it did not have was a clock.

Scope
-----
Register-only, exactly as the sync itself is: this records which titles an
account owns. It downloads nothing and changes nothing on disk.

Only stores with a real live API are polled. GOG, Epic, and Amazon use unofficial
launcher surfaces (operator-supplied tokens); CSV still works for all of them.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_scheduler_started = False

#: Stores that can actually be re-synced live today. Derived from the handler
#: registry below — see _live_sync_handlers for why this must not be edited
#: on its own.
LIVE_SYNC_STORES = ('steam', 'gog', 'epic', 'amazon')


def live_sync_stores() -> tuple[str, ...]:
    """The always-live four plus whichever unofficial stores the operator
    opted into (INSP-42 / G5). Read at call time, like the opt-in itself."""
    from oneirodex.utils.store_ownership_common import unofficial_store_opt_in

    return LIVE_SYNC_STORES + tuple(sorted(unofficial_store_opt_in()))


def _live_sync_handlers() -> dict:
    """store id -> how to check its credential and how to sync it.

    Enrolling a store means adding an entry *here*, not appending to
    LIVE_SYNC_STORES. The loop used to select accounts by that tuple and then
    call ``sync_steam_owned_games`` for every row regardless of
    ``account.store``, so adding 'gog' to the tuple — the one apparent switch,
    and what this module's own docstring invited — would have run the Steam
    sync against GOG accounts.

    Imported inside the function and looked up through the module rather than
    bound at import: the names have to resolve at call time, both to avoid a
    circular import and so tests can monkeypatch them.
    """
    from oneirodex.utils import store_ownership

    handlers = {
        'steam': {
            'credential': store_ownership.get_steam_web_api_key,
            'sync': store_ownership.sync_steam_owned_games,
            'missing': 'no Steam Web API key configured',
        },
        'gog': {
            'credential': store_ownership.gog_live_ready,
            'sync': store_ownership.sync_gog_owned_games,
            'missing': 'no GOG refresh token configured',
        },
        'epic': {
            'credential': store_ownership.epic_live_ready,
            'sync': store_ownership.sync_epic_owned_games,
            'missing': 'no Epic device auth configured',
        },
        'amazon': {
            'credential': store_ownership.amazon_live_ready,
            'sync': store_ownership.sync_amazon_owned_games,
            'missing': 'no Amazon Nile/Heroic token configured',
        },
    }
    # INSP-42: the unofficial stores enrol only while the operator has opted
    # in (ENABLE_UNOFFICIAL_STORE_SYNC). Off by default -- decision gate G5.
    from oneirodex.utils.store_ownership_common import unofficial_store_opt_in

    opted = unofficial_store_opt_in()
    if 'xbox' in opted:
        handlers['xbox'] = {
            'credential': store_ownership.xbox_live_ready,
            'sync': store_ownership.sync_xbox_owned_games,
            'missing': 'no xbox-webapi token configured (or the package is not installed)',
        }
    if 'psn' in opted:
        handlers['psn'] = {
            'credential': store_ownership.psn_live_ready,
            'sync': store_ownership.sync_psn_owned_games,
            'missing': 'no PSN npsso configured (or psnawp is not installed)',
        }

    # LIVE_SYNC_STORES is now read only by callers and tests, so nothing would
    # catch it drifting from the registry that actually runs. A tuple claiming a
    # store the registry cannot sync is the same false advertisement that made
    # the old fallthrough possible, so fail loudly rather than quietly polling
    # nothing.
    if set(handlers) != set(live_sync_stores()):
        raise RuntimeError(
            'live_sync_stores() {} does not match the sync registry {} — '
            'enrol a store by adding a handler, not by editing the tuple.'
            .format(sorted(live_sync_stores()), sorted(handlers))
        )

    # And the *product* must not claim more than the poller can do. STORE_SYNC_MODE
    # is what the ownership UI reads to decide whether to present a register as
    # current or as a dated snapshot; a store marked 'live' there without a
    # handler here would go back to showing a stale list as though it were fresh,
    # which is the exact dishonesty this pairing exists to prevent.
    claimed_live = {
        store for store in store_ownership.STORE_SYNC_MODE
        if store_ownership.store_sync_mode(store) == 'live'
    }
    if claimed_live != set(handlers):
        raise RuntimeError(
            'STORE_SYNC_MODE advertises {} as live but the sync registry has {} — '
            'a store is only live once it has a handler.'
            .format(sorted(claimed_live), sorted(handlers))
        )

    return handlers


def _is_enabled(app) -> bool:
    return bool(app.config.get('ENABLE_OWNERSHIP_POLL', True))


def _poll_seconds(app) -> int:
    """Refresh interval, clamped.

    Ownership changes when someone buys something — hourly is already generous
    and the floor exists so a misconfiguration cannot hammer a third-party API
    on our users' keys.
    """
    try:
        hours = float(app.config.get('OWNERSHIP_POLL_HOURS') or 12)
    except (TypeError, ValueError):
        hours = 12.0
    hours = max(1.0, min(hours, 168.0))
    return int(hours * 3600)


def sync_all_linked_accounts() -> dict:
    """Re-sync every linked account that supports a live API.

    Failures are per-account: one member's revoked token or private profile
    must not stop everyone else's refresh, which is the usual way a batch job
    like this quietly stops working for the whole install.
    """
    from sqlalchemy import select

    from oneirodex import db
    from oneirodex.models import StoreAccount
    from oneirodex.utils import store_ownership
    from oneirodex.utils.store_sync_errors import AUTH_REASONS, SyncOutcomeError
    from oneirodex.utils.store_sync_jobs import is_stale, latest_jobs, run_store_sync

    if not store_ownership.is_ownership_sync_enabled():
        return {'skipped': 'ownership sync disabled by administrator'}

    handlers = _live_sync_handlers()

    # A store with no credential configured would fail identically on every
    # account; drop it once here rather than logging one failure per member.
    usable = {
        store: handler
        for store, handler in handlers.items()
        if handler['credential']()
    }
    if not usable:
        return {'skipped': '; '.join(h['missing'] for h in handlers.values())}

    accounts = db.session.execute(
        select(StoreAccount).filter(StoreAccount.store.in_(tuple(usable)))
    ).scalars().all()
    # Snapshot account facts up front: every job commits, which expires ORM rows.
    accounts = [
        (a.user_id, (a.store or '').lower(), a.external_account_id, getattr(a, 'credential', None), a.updated_at)
        for a in accounts
    ]
    # Same for the latest jobs: a disconnect during this cycle deletes its
    # store's job rows, and reading an expired, deleted row would raise.
    last_jobs = {
        key: (job.status, job.reason, job.finished_at, is_stale(job))
        for key, job in latest_jobs({user_id for user_id, *_ in accounts}).items()
    }

    synced = 0
    failed = 0
    waiting = 0
    for user_id, store, external_account_id, credential, updated_at in accounts:
        handler = usable.get(store)
        if handler is None:
            # Unreachable given the filter, and deliberately not a fallthrough:
            # syncing an unknown store with whichever function happened to be in
            # scope is exactly the bug this registry replaced.
            continue
        if store == 'steam' and not external_account_id:
            continue
        if store == 'gog' and not (credential or store_ownership.get_gog_api_token()):
            continue
        if store == 'epic' and not (credential or store_ownership.get_epic_api_token()):
            continue
        if store == 'amazon' and not (credential or store_ownership.get_amazon_api_token()):
            continue
        # A sign-in the provider already refused will be refused again; wait
        # for the member to reconnect instead of retrying it every cycle. A
        # sync still running (member button, another worker) is left alone.
        last_status, last_reason, last_finished, last_stale = last_jobs.get((user_id, store), (None,) * 4)
        if last_status == 'running' and not last_stale:
            waiting += 1
            continue
        if (last_status == 'failed' and last_reason in AUTH_REASONS
                and not (updated_at and last_finished and updated_at > last_finished)):
            waiting += 1
            continue
        try:
            outcome = run_store_sync(user_id, store, trigger='schedule', sync_fn=handler['sync'])
        except SyncOutcomeError:
            waiting += 1
            continue
        except Exception as exc:  # noqa: BLE001 -- one member's link must not end everyone's refresh
            db.session.rollback()
            failed += 1
            # Type only: a database error's text includes statement parameters.
            logger.warning('Ownership sync error for user %s (%s): %s', user_id, store, type(exc).__name__)
            continue
        if outcome['job'].status in ('succeeded', 'partial'):
            synced += 1
        else:
            failed += 1
            # Reason code only: exception text can carry request URLs (the
            # Steam server key) or SQL parameters (tokens).
            print(f"[OWNERSHIP] sync {outcome['job'].status} for user {user_id} ({store}): {outcome['reason']}")

    return {'accounts': len(accounts), 'synced': synced, 'failed': failed, 'waiting': waiting}


def start_ownership_scheduler(app):
    """Start the daemon that keeps linked accounts current (idempotent)."""
    global _scheduler_started
    if _scheduler_started:
        return
    if not _is_enabled(app):
        print('[OWNERSHIP] Disabled (ENABLE_OWNERSHIP_POLL=false)')
        return

    # Validate the registry *here*, at start, not on the first poll.
    #
    # The consistency checks in _live_sync_handlers() only ran inside
    # sync_all_linked_accounts(), which the loop wraps in a try/except that
    # prints and carries on. A mismatch therefore booted cleanly and then failed
    # silently every twelve hours — the exact shape of quiet breakage this
    # registry exists to prevent.
    #
    # Scoped to the poller rather than raising into app start: a mismatch is a
    # developer error, and taking a household's whole install down for it after
    # an upgrade would be a worse outcome than not polling.
    with app.app_context():
        try:
            _live_sync_handlers()
        except RuntimeError as exc:
            print(f'[OWNERSHIP] NOT started — sync registry is inconsistent: {exc}')
            return

    _scheduler_started = True
    interval = _poll_seconds(app)

    def _loop():
        # Let boot finish before making outbound calls, same as the other pollers.
        time.sleep(30)
        while True:
            try:
                with app.app_context():
                    stats = sync_all_linked_accounts()
                    if 'skipped' in stats:
                        print(f"[OWNERSHIP] Skipped: {stats['skipped']}")
                    else:
                        print(
                            f"[OWNERSHIP] Re-synced {stats['synced']}/{stats['accounts']}"
                            f" linked accounts ({stats['failed']} failed)"
                        )
            except Exception as exc:
                # A poller that dies takes ownership freshness with it silently.
                # Type only: a database error's text includes statement parameters.
                print(f'[OWNERSHIP] Poll error: {type(exc).__name__}')
            time.sleep(interval)

    threading.Thread(target=_loop, name='od-ownership-poll', daemon=True).start()
    print(f'[OWNERSHIP] Started (re-sync every {interval // 3600}h)')
