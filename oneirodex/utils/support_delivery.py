"""Durable local support receipts and a one-attempt external delivery boundary."""
from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import logging
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .role_catalog import normalize_role
from .support_reports import support_fields


class SupportRequestConflict(ValueError):
    """The caller reused a request reference for different report contents."""


class SupportRateLimited(ValueError):
    pass


def support_request_hash(body: dict) -> str:
    values = {**support_fields(body), 'sync_to_github': body.get('sync_to_github') is True}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def find_support_request(session, user_id, body):
    from oneirodex.models import SupportTicket
    if not body.get('request_id'):
        return None
    ticket = session.scalar(select(SupportTicket).where(
        SupportTicket.user_id == user_id,
        SupportTicket.request_id == str(body['request_id']),
    ).execution_options(populate_existing=True))
    if ticket is not None and ticket.request_hash != support_request_hash(body):
        raise SupportRequestConflict('This report reference already belongs to different contents.')
    return ticket


def persist_support_request(session, user, body, now):
    """Serialize the local reservation per account; release before provider I/O."""
    from oneirodex.models import SupportTicket, User
    # This also serializes the five-new-reports limit across concurrent submits.
    session.scalar(select(User.id).where(User.id == user.id).with_for_update())
    existing = find_support_request(session, user.id, body)
    if existing is not None:
        session.commit()
        return existing, False
    count = session.scalar(select(func.count(SupportTicket.id)).where(
        SupportTicket.user_id == user.id,
        SupportTicket.created_at >= now - timedelta(hours=1),
    )) or 0
    if count >= 5:
        session.rollback()
        raise SupportRateLimited('Support report limit reached. Try again later.')
    ticket = SupportTicket(
        **support_fields(body), user_id=user.id,
        request_id=str(body.get('request_id') or uuid4()),
        request_hash=support_request_hash(body),
        role_at_submit=normalize_role(getattr(user, 'role', None)),
        status='open', github_sync='pending' if body.get('sync_to_github') is True else 'local_only',
        created_at=now,
    )
    session.add(ticket)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        # A database uniqueness guard also protects writers outside this helper.
        existing = find_support_request(session, user.id, body)
        if existing is None:
            raise
        return existing, False
    return ticket, True


def deliver_support_request(session, ticket, payload, sender):
    """Commit 'sending' before POST; a replay can never repeat an uncertain send."""
    from oneirodex.models import SupportTicket
    ticket_id = ticket.id
    claimed = session.execute(update(SupportTicket).where(
        SupportTicket.id == ticket_id,
        SupportTicket.github_sync == 'pending',
    ).values(github_sync='sending', github_attempt_id=ticket.request_id)).rowcount
    session.commit()
    if not claimed:
        session.refresh(ticket)
        return ticket
    try:
        outcome = sender(**payload)
    except Exception:
        # A sender extension can fail after the remote accepted the request.
        outcome = {'ok': False, 'outcome': 'unknown'}
    if outcome.get('ok'):
        ticket.github_sync = 'synced'
        ticket.github_issue_number = outcome.get('number')
        ticket.github_issue_url = outcome.get('url')
    elif outcome.get('skipped'):
        ticket.github_sync = 'skipped'
    else:
        ticket.github_sync = 'rejected' if outcome.get('outcome') == 'rejected' else 'unknown'
        logging.getLogger(__name__).warning('Support forwarding did not return a confirmed issue receipt')
    try:
        session.commit()
    except Exception:
        session.rollback()
        # The committed sending marker survives a failed/unknown result commit.
        # If the DB is unavailable, propagate the safe API failure; a later
        # request still finds the durable receipt and does not POST again.
        session.refresh(ticket)
    return ticket
