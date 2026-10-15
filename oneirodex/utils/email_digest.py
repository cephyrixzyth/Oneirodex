"""Batched email digest of unread notifications (Wave 15c)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import User, UserNotification, UserPreference
from oneirodex.utils.email_rendering import render_daily_digest
from oneirodex.utils.notifications import _pref_allows
from oneirodex.utils.smtp import send_email_quiet
from oneirodex.utils.runtime_config import get_runtime_config

_DIGEST_KINDS = frozenset({'mention', 'dm', 'free_game'})
_KIND_PREF = {
    'mention': 'notify_mentions',
    'dm': 'notify_chat',
    'free_game': 'notify_free_games',
}


def _interval_hours() -> float:
    try:
        hours = float((get_runtime_config() or {}).get('EMAIL_DIGEST_INTERVAL_HOURS') or 24)
    except (TypeError, ValueError):
        hours = 24.0
    return max(1.0, min(hours, 168.0))


def _absolute_link(path: str | None) -> str:
    if not path:
        return ''
    if path.startswith('http://') or path.startswith('https://'):
        return path
    try:
        from flask import has_request_context, request

        request_root = request.url_root if has_request_context() else None
    except ImportError:
        request_root = None
    if request_root:
        root = request_root.rstrip('/')
        if root:
            return f'{root}{path if path.startswith("/") else "/" + path}'
    return path


def _eligible_rows(user_id: int, since: datetime | None) -> list[UserNotification]:
    q = (
        select(UserNotification)
        .where(
            UserNotification.user_id == user_id,
            UserNotification.read_at.is_(None),
            UserNotification.kind.in_(tuple(_DIGEST_KINDS)),
        )
        .order_by(UserNotification.created_at.asc())
        .limit(40)
    )
    if since is not None:
        q = q.where(UserNotification.created_at > since)
    rows = db.session.execute(q).scalars().all()
    out: list[UserNotification] = []
    for row in rows:
        pref = _KIND_PREF.get(row.kind)
        if pref and not _pref_allows(user_id, pref, default=True):
            continue
        out.append(row)
    return out


def send_digest_for_user(user: User, prefs: UserPreference, *, now: datetime | None = None) -> bool:
    """Send one digest email if due. Returns True when an email was sent."""
    now = now or datetime.now(timezone.utc)
    if not bool(getattr(prefs, 'email_digest_daily', False)):
        return False
    email = (user.email or '').strip()
    if not email:
        return False
    if hasattr(user, 'is_email_verified') and not bool(user.is_email_verified):
        return False
    if not bool(getattr(user, 'state', True)):
        return False

    last = getattr(prefs, 'email_digest_last_sent_at', None)
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now - last < timedelta(hours=_interval_hours()):
            return False

    rows = _eligible_rows(user.id, last)
    if not rows:
        return False

    items: list[dict[str, Any]] = []
    for row in rows:
        items.append({
            'kind': row.kind,
            'title': row.title,
            'body': row.body or '',
            'link': _absolute_link(row.link or '/notifications'),
        })

    html = render_daily_digest(items, _absolute_link('/notifications'))

    subject = f'Oneirodex — {len(items)} unread notification{"s" if len(items) != 1 else ""}'
    if not send_email_quiet(email, subject, html):
        return False

    prefs.email_digest_last_sent_at = now
    db.session.commit()
    return True


def run_email_digest_batch(*, now: datetime | None = None) -> dict[str, int]:
    """Send digests for all opted-in users. Safe to call from scheduler or tests."""
    now = now or datetime.now(timezone.utc)
    prefs_rows = db.session.execute(
        select(UserPreference).where(UserPreference.email_digest_daily.is_(True)),
    ).scalars().all()

    considered = 0
    sent = 0
    skipped = 0
    for prefs in prefs_rows:
        considered += 1
        user = db.session.get(User, prefs.user_id)
        if user is None:
            skipped += 1
            continue
        try:
            if send_digest_for_user(user, prefs, now=now):
                sent += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return {'considered': considered, 'sent': sent, 'skipped': skipped}
