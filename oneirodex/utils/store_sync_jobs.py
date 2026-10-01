"""Persisted live ownership syncs with honest progress and cancellation (LIB-04).

Every live sync — a member's button, the background poller or an administrator
retry — runs through :func:`run_store_sync`, which records one
:class:`StoreSyncJob` row. The row is what the connection status reads, so a
token that expired overnight shows up as *reconnect needed* instead of vanishing
into a server log.

Cancellation is cooperative and only offered where it is real. GOG, Epic and
Amazon read several provider pages or chunks and call :func:`checkpoint` between
them; a cancel request is honoured at the next checkpoint. Steam, Xbox and
PlayStation make one provider call that cannot be interrupted, so their jobs are
created ``cancellable=False`` and the cancel route refuses them.

Adapters fetch everything first and write the register afterwards, so a
cancelled or failed sync saves nothing. The one deliberate exception is a
rotated provider token, which is committed as soon as it arrives because the
previous token may already be invalid.

A job whose heartbeat stops for :data:`STALE_AFTER` is taken over (marked
*interrupted*) by the next sync or link change for that member and store. The
original worker may still be alive, so every commit made while a job runs is
fenced: it re-reads the job, locking the row, and refuses to commit once the
job is no longer running. A worker that lost its slot therefore cannot write
titles back after a disconnect, or over a newer sync.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from oneirodex import db
from oneirodex.models import StoreSyncJob
from oneirodex.utils.store_sync_errors import (
    StoreSyncError, SyncOutcomeError, classify_sync_exception, reason_payload,
)

__all__ = [
    'LIVE_SYNC_ADAPTERS', 'CANCELLABLE_STORES', 'STALE_AFTER', 'SyncCancelled',
    'checkpoint', 'mark_partial', 'mark_warning', 'run_store_sync', 'request_cancel',
    'latest_jobs', 'running_job', 'job_dict', 'is_stale', 'iso_utc', 'utcnow',
    'exclusive_link_change', 'LINK_TRIGGERS',
]

LIVE_SYNC_ADAPTERS = ('steam', 'gog', 'epic', 'amazon', 'xbox', 'psn')
CANCELLABLE_STORES = frozenset({'gog', 'epic', 'amazon'})
#: A running job whose heartbeat is older than this was lost (restart, killed
#: worker). Checkpoints refresh the heartbeat; the longest single provider call
#: is bounded by the 30 second outbound timeout.
STALE_AFTER = timedelta(minutes=10)
#: Finished jobs kept per member and store. Status needs only the latest; a few
#: more let an administrator see whether a failure is new or recurring.
KEEP_JOBS = 20

PROVIDER_NAMES = {
    'steam': 'Steam', 'gog': 'GOG', 'epic': 'Epic Games', 'amazon': 'Amazon Games',
    'xbox': 'Xbox', 'psn': 'PlayStation',
}


class SyncCancelled(Exception):
    """Raised at a checkpoint once a cancel request is seen."""


@dataclass
class _JobContext:
    job_id: int
    cancellable: bool
    partial_reason: str | None = None
    warning_reason: str | None = None


_current: ContextVar[_JobContext | None] = ContextVar('store_sync_job', default=None)


class SyncSlotLost(StoreSyncError):
    """This worker's job was taken over (stale) or removed (disconnect)."""

    def __init__(self):
        super().__init__('Sync was taken over before it could save', 'interrupted')


@event.listens_for(Session, 'before_commit')
def _fence_commit(session):
    """Refuse a commit from a sync whose job is no longer running.

    Only commits made while :func:`run_store_sync` runs its adapter (the
    context variable is set) are checked. ``FOR UPDATE`` makes a concurrent
    takeover wait for this commit, or this commit see the takeover.
    """
    ctx = _current.get()
    if ctx is None:
        return
    status = session.execute(
        select(StoreSyncJob.status).where(StoreSyncJob.id == ctx.job_id).with_for_update()
    ).scalar()
    if status != 'running':
        raise SyncSlotLost()


def utcnow() -> datetime:
    """Naive UTC, matching how the DateTime columns round-trip."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec='seconds') + 'Z'


def is_stale(job: StoreSyncJob, now: datetime | None = None) -> bool:
    heartbeat = job.heartbeat_at
    if heartbeat is not None and heartbeat.tzinfo is not None:
        heartbeat = heartbeat.astimezone(timezone.utc).replace(tzinfo=None)
    return job.status == 'running' and (heartbeat is None or (now or utcnow()) - heartbeat > STALE_AFTER)


def checkpoint(*, pages: int = 0, items: int = 0) -> None:
    """Record progress and honour a pending cancel. A no-op outside a job.

    Adapters call this only while fetching, before any register write, so the
    commit here never publishes a half-written register.
    """
    ctx = _current.get()
    if ctx is None:
        return
    # Defensive: never let a progress commit publish register rows an adapter
    # has staged. Adapters do not stage writes before their last checkpoint,
    # but if one ever does, progress waits for the job's final commit instead.
    pending = bool(db.session.new or db.session.dirty or db.session.deleted)
    db.session.execute(update(StoreSyncJob).where(StoreSyncJob.id == ctx.job_id).values(
        pages=StoreSyncJob.pages + pages,
        items_seen=StoreSyncJob.items_seen + items,
        heartbeat_at=utcnow(),
    ).execution_options(synchronize_session=False))
    if not pending:
        db.session.commit()
    requested = db.session.execute(
        select(StoreSyncJob.cancel_requested).where(StoreSyncJob.id == ctx.job_id)
    ).scalar()
    if requested and ctx.cancellable:
        raise SyncCancelled()


def mark_partial(reason: str) -> None:
    """The sync finished but its list is incomplete (first reason wins)."""
    ctx = _current.get()
    if ctx is not None and ctx.partial_reason is None:
        ctx.partial_reason = reason


def mark_warning(reason: str) -> None:
    """The sync finished, but the member should know something (e.g. an empty,
    possibly private, library)."""
    ctx = _current.get()
    if ctx is not None and ctx.warning_reason is None:
        ctx.warning_reason = reason


def _expire_stale(user_id: int, store: str) -> None:
    now = utcnow()
    db.session.execute(update(StoreSyncJob).where(
        StoreSyncJob.user_id == user_id, StoreSyncJob.store == store,
        StoreSyncJob.status == 'running', StoreSyncJob.heartbeat_at < now - STALE_AFTER,
    ).values(status='failed', reason='interrupted', finished_at=now))
    db.session.commit()


def running_job(user_id: int, store: str) -> StoreSyncJob | None:
    job = db.session.execute(select(StoreSyncJob).where(
        StoreSyncJob.user_id == user_id, StoreSyncJob.store == store,
        StoreSyncJob.status == 'running',
    ).order_by(StoreSyncJob.id.desc()).limit(1)).scalar_one_or_none()
    return None if job is None or is_stale(job) else job


#: Triggers that hold the running slot for a link change, not a sync.
LINK_TRIGGERS = frozenset({'connect', 'disconnect'})


def _start(user_id: int, store: str, trigger: str, actor_id: int | None) -> StoreSyncJob:
    _expire_stale(user_id, store)
    now = utcnow()
    job = StoreSyncJob(
        user_id=user_id, store=store, trigger=trigger, actor_id=actor_id,
        status='running',
        cancellable=store in CANCELLABLE_STORES and trigger not in LINK_TRIGGERS,
        cancel_requested=False, pages=0, items_seen=0,
        started_at=now, heartbeat_at=now,
    )
    db.session.add(job)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        holder = running_job(user_id, store)
        busy = 'store_busy' if holder is not None and holder.trigger in LINK_TRIGGERS else 'sync_in_progress'
        raise SyncOutcomeError(busy, job=holder if busy == 'sync_in_progress' else None) from None
    return job


def exclusive_link_change(user_id: int, store: str, trigger: str, change, *, clear_history: bool = False):
    """Run a connect or disconnect while holding the member's running slot.

    A sync and a link change for the same member and store can then never
    overlap: a sync that is running makes this raise ``sync_in_progress``, and
    a sync started meanwhile is refused the same way. Without it a disconnect
    could pass its check just before a scheduled sync read the account, and
    that sync would write the cleared titles back. The marker row is removed
    afterwards; ``clear_history`` also drops the store's past jobs (disconnect),
    so a later link does not inherit the old one's results.
    """
    marker = _start(user_id, store, trigger, user_id)
    marker_id = marker.id
    try:
        return change()
    finally:
        db.session.rollback()
        condition = [StoreSyncJob.user_id == user_id, StoreSyncJob.store == store]
        if not clear_history:
            condition.append(StoreSyncJob.id == marker_id)
        db.session.execute(delete(StoreSyncJob).where(*condition))
        db.session.commit()


def _finish(job_id: int, status: str, reason: str | None, result: dict | None = None,
            started: StoreSyncJob | None = None) -> StoreSyncJob:
    values = {'status': status, 'reason': reason, 'finished_at': utcnow(), 'heartbeat_at': utcnow()}
    if result is not None:
        for key in ('synced', 'matched'):
            value = result.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                values[key] = value
    finished = db.session.execute(update(StoreSyncJob).where(
        StoreSyncJob.id == job_id, StoreSyncJob.status == 'running',
    ).values(**values))
    if finished.rowcount == 0:
        # Taken over while it ran: another sync or a link change expired it as
        # interrupted, and a disconnect may have removed it. Leave that record.
        db.session.rollback()
        job = db.session.get(StoreSyncJob, job_id, populate_existing=True)
        if job is not None:
            return job
        # Removed by a disconnect: an unsaved stand-in with what is known.
        return StoreSyncJob(
            id=job_id, user_id=started.user_id if started else None, store=started.store if started else None,
            trigger=started.trigger if started else None, started_at=started.started_at if started else None,
            status='failed', reason='interrupted', cancellable=False, cancel_requested=False,
            pages=0, items_seen=0, finished_at=values['finished_at'],
        )
    job = db.session.get(StoreSyncJob, job_id, populate_existing=True)
    keep = select(StoreSyncJob.id).where(
        StoreSyncJob.user_id == job.user_id, StoreSyncJob.store == job.store,
    ).order_by(StoreSyncJob.id.desc()).limit(KEEP_JOBS)
    db.session.execute(delete(StoreSyncJob).where(
        StoreSyncJob.user_id == job.user_id, StoreSyncJob.store == job.store,
        StoreSyncJob.status != 'running', StoreSyncJob.id.not_in(keep.scalar_subquery()),
    ))
    db.session.commit()
    return job


def _default_sync_fn(store: str):
    # Resolved at call time through the module so callers and tests that patch
    # ``store_ownership.sync_<store>_owned_games`` are honoured.
    from oneirodex.utils import store_ownership
    return getattr(store_ownership, f'sync_{store}_owned_games')


def run_store_sync(user_id: int, store: str, *, trigger: str, actor_id: int | None = None, sync_fn=None) -> dict:
    """Run one live sync as a recorded job.

    Returns ``{'job': StoreSyncJob, 'result': dict | None, 'reason': str | None}``;
    ``reason`` is a catalogue code whenever the job did not succeed cleanly.
    Raises :class:`SyncOutcomeError` (``sync_in_progress``) without starting when
    another sync for the same member and store is running.
    """
    if store not in LIVE_SYNC_ADAPTERS:
        raise ValueError(f'No live sync adapter for {store}')
    fn = sync_fn or _default_sync_fn(store)
    job = _start(user_id, store, trigger, actor_id)
    job_id = job.id
    # Plain copy: the row can be deleted (disconnect) before the sync finishes.
    started = StoreSyncJob(user_id=user_id, store=store, trigger=trigger, started_at=job.started_at)
    ctx = _JobContext(job_id=job_id, cancellable=job.cancellable)
    token = _current.set(ctx)
    result = None
    try:
        result = fn(user_id)
    except SyncCancelled:
        status, reason = 'cancelled', 'cancelled'
    except Exception as exc:  # noqa: BLE001 -- classified; text never leaves this frame
        status, reason = 'failed', classify_sync_exception(exc)
    else:
        result = result if isinstance(result, dict) else {}
        status, reason = ('partial', ctx.partial_reason) if ctx.partial_reason else ('succeeded', ctx.warning_reason)
    finally:
        # Reset before _finish: its own commit is not an adapter write to fence.
        _current.reset(token)
    if status in ('cancelled', 'failed'):
        db.session.rollback()
        result = None
    finished = _finish(job_id, status, reason, result, started)
    if finished.status != status:
        # Taken over after this worker's last commit: report what the record
        # says (interrupted), not a success, and never a reasonless failure.
        return {'job': finished, 'result': None, 'reason': finished.reason or 'interrupted'}
    return {'job': finished, 'result': result, 'reason': reason}


def request_cancel(user_id: int, store: str) -> StoreSyncJob:
    job = running_job(user_id, store)
    if job is None:
        raise SyncOutcomeError('nothing_to_cancel')
    if not job.cancellable:
        raise SyncOutcomeError('not_cancellable', job=job)
    db.session.execute(update(StoreSyncJob).where(
        StoreSyncJob.id == job.id, StoreSyncJob.status == 'running',
    ).values(cancel_requested=True))
    db.session.commit()
    return db.session.get(StoreSyncJob, job.id, populate_existing=True)


def latest_jobs(user_ids=None) -> dict[tuple[int, str], StoreSyncJob]:
    """Newest job per (member, store); optionally limited to some members."""
    newest = select(StoreSyncJob.user_id, StoreSyncJob.store, db.func.max(StoreSyncJob.id).label('id'))
    if user_ids is not None:
        newest = newest.where(StoreSyncJob.user_id.in_(list(user_ids)))
    newest = newest.group_by(StoreSyncJob.user_id, StoreSyncJob.store).subquery()
    rows = db.session.execute(select(StoreSyncJob).join(newest, StoreSyncJob.id == newest.c.id)).scalars().all()
    return {(job.user_id, job.store): job for job in rows}


def job_dict(job: StoreSyncJob | None, now: datetime | None = None) -> dict | None:
    """Member-safe job view. No actor, credential or upstream detail."""
    if job is None:
        return None
    stale = is_stale(job, now)
    status, reason = ('failed', 'interrupted') if stale else (job.status, job.reason)
    name = PROVIDER_NAMES.get(job.store, job.store)
    return {
        'id': job.id,
        'store': job.store,
        'trigger': job.trigger,
        'status': status,
        'outcome': reason_payload(reason, name) if reason else None,
        'cancellable': bool(job.cancellable),
        'cancel_requested': bool(job.cancel_requested),
        'progress': {'pages': job.pages or 0, 'items_seen': job.items_seen or 0},
        'synced': job.synced,
        'matched': job.matched,
        'started_at': iso_utc(job.started_at),
        'heartbeat_at': iso_utc(job.heartbeat_at),
        'finished_at': iso_utc(job.finished_at),
    }
