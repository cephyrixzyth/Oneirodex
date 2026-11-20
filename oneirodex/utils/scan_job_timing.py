"""Honest elapsed / ETA helpers for ScanJob list and Ops payloads.

``ScanJob`` has no separate ``started_at`` / ``created_at`` column. Run start is
``last_run`` (set when a job becomes Running, or enqueue time while Queued).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# No progress bump for this long while Running/Stopping → stall (ETA null).
STALL_SECONDS = 120

_ACTIVE = frozenset({'Running', 'Stopping'})
_TERMINAL = frozenset({'Completed', 'Failed', 'Cancelled'})
_WAITING = frozenset({'Queued', 'Scheduled'})

SCAN_JOB_STATUSES = frozenset({
    'Scheduled', 'Queued', 'Running', 'Stopping', 'Completed', 'Failed', 'Cancelled',
})


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_duration_label(seconds: Optional[int]) -> Optional[str]:
    """Compact human label (e.g. ``2m 14s``). Null in → null out."""
    if seconds is None:
        return None
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return None
    if total < 0:
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f'{hours}h {minutes}m {secs}s'
    if minutes:
        return f'{minutes}m {secs}s'
    return f'{secs}s'


def folders_processed(job) -> int:
    return int(job.folders_success or 0) + int(job.folders_failed or 0)


def compute_scan_job_timing(job, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Return timing fields for one ScanJob (server-computed, honest).

    Fields:
      started_at       — ISO of ``last_run`` (run start; Queued = enqueue time). Null if unset.
      created_at       — always null (no create column; do not invent).
      folders_processed
      elapsed_seconds  — start→now while active/waiting; start→last_progress when terminal
      eta_seconds      — remaining / throughput; null when unknown / queued / stalled / done
      stalled          — True when Running/Stopping with no recent progress bump
      elapsed_label / eta_label — optional human hints
    """
    now = _ensure_utc(now) or datetime.now(timezone.utc)
    started = _ensure_utc(getattr(job, 'last_run', None))
    last_update = _ensure_utc(getattr(job, 'last_progress_update', None))
    finished = _ensure_utc(getattr(job, 'finished_at', None))
    status = getattr(job, 'status', None) or ''
    total = int(getattr(job, 'total_folders', 0) or 0)
    processed = folders_processed(job)

    started_at = started.isoformat() if started else None

    elapsed_seconds: Optional[int] = None
    if started is not None:
        if status in _TERMINAL:
            end = finished or last_update or started
            elapsed_seconds = max(0, int((end - started).total_seconds()))
        else:
            # Running / Stopping / Queued / Scheduled — live clock from last_run
            elapsed_seconds = max(0, int((now - started).total_seconds()))

    stalled = False
    if status in _ACTIVE:
        anchor = last_update or started
        if anchor is not None:
            idle = int((now - anchor).total_seconds())
            if idle >= STALL_SECONDS:
                stalled = True
        # Zero progress and no bump yet: not stalled until STALL_SECONDS from start
        elif started is not None:
            if int((now - started).total_seconds()) >= STALL_SECONDS:
                stalled = True

    eta_seconds: Optional[int] = None
    if (
        status in _ACTIVE
        and not stalled
        and elapsed_seconds is not None
        and elapsed_seconds > 0
        and processed > 0
        and total > processed
    ):
        rate = processed / float(elapsed_seconds)  # folders per second
        if rate > 0:
            remaining = total - processed
            # Floor to whole seconds; avoid fake sub-second precision
            eta_seconds = max(0, int(remaining / rate))

    if status in _WAITING or status in _TERMINAL:
        eta_seconds = None

    if status in _TERMINAL:
        finished = finished or last_update
    else:
        finished = None

    return {
        'started_at': started_at,
        'finished_at': finished.isoformat() if finished else None,
        'created_at': None,  # ScanJob has no create column — honest null
        'folders_processed': processed,
        'elapsed_seconds': elapsed_seconds,
        'eta_seconds': eta_seconds,
        'stalled': stalled,
        'elapsed_label': format_duration_label(elapsed_seconds),
        'eta_label': format_duration_label(eta_seconds),
    }


_UNMATCHED_REASON_LABELS = {
    None: 'No confident match',
    '': 'No confident match',
    'no_confident_match': 'No confident match',
    'update_package_folder': 'Update package, not a game',
    'igdb_unavailable': 'IGDB unavailable (retried next scan)',
}


def unmatched_reason_label(reason: Optional[str]) -> str:
    """Plain words for an unmatched folder's ``match_reason``."""
    if reason in _UNMATCHED_REASON_LABELS:
        return _UNMATCHED_REASON_LABELS[reason]
    return str(reason).replace('_', ' ').strip().capitalize()


def parse_scan_job_status_filter(raw: Optional[str]) -> list[str]:
    """Parse ``status=`` query (comma list). Unknown tokens dropped. Empty → no filter."""
    if not raw or not str(raw).strip():
        return []
    wanted = []
    seen = set()
    for part in str(raw).split(','):
        token = part.strip()
        if not token:
            continue
        # Case-insensitive match to canonical enum casing
        match = next((s for s in SCAN_JOB_STATUSES if s.lower() == token.lower()), None)
        if match and match not in seen:
            seen.add(match)
            wanted.append(match)
    return wanted
