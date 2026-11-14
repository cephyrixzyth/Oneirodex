"""Durable support receipts, bounded explicit retries and read-only reconciliation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


class SupportRequestNotFound(ValueError):
    pass


def delivery_now():
    return datetime.now(timezone.utc)


def outgoing_fingerprint(payload):
    text = {'title': payload['title'], 'body': payload['body']}
    return hashlib.sha256(json.dumps(text, sort_keys=True).encode()).hexdigest()


def is_support_replay(session, ticket, body):
    """Only a new, explicitly approved retry may advance a terminal receipt."""
    from oneirodex.models import SupportDeliveryAttempt
    retry = body.get('retry_github') is True
    if ticket is None:
        if retry:
            raise SupportRequestConflict('Retry requires an existing report.')
        return False
    if not retry:
        return ticket.github_sync != 'pending'
    nonce = str(body.get('retry_id') or '')
    if not nonce:
        raise SupportRequestConflict('Preview the retry before sending.')
    attempt = session.get(SupportDeliveryAttempt, {'id': nonce, 'user_id': ticket.user_id})
    if attempt is not None:
        if attempt.ticket_id != ticket.id:
            raise SupportRequestConflict('This attempt reference belongs to another report.')
        return True
    if ticket.github_sync not in {'rejected', 'skipped'}:
        raise SupportRequestConflict('This delivery cannot be posted again. Check its existing receipt.')
    previous = session.get(SupportDeliveryAttempt, {'id': ticket.github_attempt_id, 'user_id': ticket.user_id}) if ticket.github_attempt_id else None
    if previous is None:
        raise SupportRequestConflict('This older delivery needs an administrator to check its provider record.')
    return False


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


def deliver_support_request(session, ticket, payload, sender, *, retry_id=None):
    """Reserve a distinct attempt before POST, under a short account/row lock."""
    from oneirodex.models import SupportTicket, SupportDeliveryAttempt, User
    from .github_issues import support_github_config, valid_support_repository
    ticket_id, user_id = ticket.id, ticket.user_id
    session.scalar(select(User.id).where(User.id == user_id).with_for_update())
    ticket = session.scalar(select(SupportTicket).where(
        SupportTicket.id == ticket_id, SupportTicket.user_id == user_id,
    ).with_for_update().execution_options(populate_existing=True))
    if ticket is None:
        session.rollback()
        raise SupportRequestConflict('The report no longer exists.')
    nonce = str(retry_id or ticket.request_id)
    existing = session.get(SupportDeliveryAttempt, {'id': nonce, 'user_id': user_id})
    if existing is not None:
        session.commit()
        if existing.ticket_id != ticket_id:
            raise SupportRequestConflict('This attempt reference belongs to another report.')
        return ticket
    allowed = {'rejected', 'skipped'} if retry_id else {'pending'}
    if ticket.github_sync not in allowed:
        session.commit()
        if retry_id:
            raise SupportRequestConflict('This delivery cannot be posted again. Check its existing receipt.')
        return ticket
    now = delivery_now()
    account_cooldown = session.scalar(select(func.max(SupportDeliveryAttempt.retry_after_at)).where(
        SupportDeliveryAttempt.user_id == user_id, SupportDeliveryAttempt.retry_after_at > now,
    ))
    if account_cooldown and (not ticket.github_retry_after_at or account_cooldown > ticket.github_retry_after_at):
        ticket.github_retry_after_at = account_cooldown
    if ticket.github_retry_after_at and ticket.github_retry_after_at > now:
        session.commit()
        return ticket
    cutoff = now - timedelta(hours=1)
    used = session.scalar(select(func.count()).select_from(SupportDeliveryAttempt).where(
        SupportDeliveryAttempt.user_id == user_id, SupportDeliveryAttempt.created_at > cutoff,
    )) or 0
    if used >= 5:
        oldest = session.scalar(select(func.min(SupportDeliveryAttempt.created_at)).where(
            SupportDeliveryAttempt.user_id == user_id, SupportDeliveryAttempt.created_at > cutoff,
        ))
        ticket.github_retry_after_at = oldest + timedelta(hours=1)
        session.commit()
        return ticket
    repo = payload.get('expected_repository') or support_github_config()[1]
    if not valid_support_repository(repo):
        session.rollback()
        raise SupportRequestConflict('Preview a valid support destination before sending.')
    session.add(SupportDeliveryAttempt(
        id=nonce, user_id=user_id, ticket_id=ticket_id, created_at=now,
        repository=repo, payload_sha256=outgoing_fingerprint(payload), outcome='sending',
    ))
    ticket.github_sync = 'sending'
    ticket.github_attempt_id = nonce
    ticket.github_repository = repo
    ticket.github_retry_after_at = None
    ticket.github_last_status = None
    session.commit()
    try:
        outcome = sender(**payload)
    except Exception:
        # A sender extension can fail after the remote accepted the request.
        outcome = {'ok': False, 'outcome': 'unknown'}
    state = ('synced' if outcome.get('ok') else 'skipped' if outcome.get('skipped')
             else 'rejected' if outcome.get('outcome') == 'rejected' else 'unknown')
    if state in {'unknown', 'rejected'}:
        logging.getLogger(__name__).warning('Support forwarding did not return a confirmed issue receipt')
    seconds = outcome.get('retry_after_seconds')
    retry_after = None
    if isinstance(seconds, int) and seconds > 0:
        try:
            retry_after = delivery_now() + timedelta(seconds=seconds)
        except OverflowError:
            retry_after = datetime.max.replace(tzinfo=timezone.utc)
    result = {'github_sync': state, 'github_last_status': outcome.get('http_status'),
              'github_retry_after_at': retry_after}
    attempt_result = {'outcome': state, 'http_status': outcome.get('http_status'), 'retry_after_at': retry_after}
    if state == 'synced':
        result.update(github_issue_number=outcome.get('number'), github_issue_url=outcome.get('url'))
        attempt_result.update(issue_number=outcome.get('number'), issue_url=outcome.get('url'))
    session.execute(update(SupportDeliveryAttempt).where(
        SupportDeliveryAttempt.id == nonce, SupportDeliveryAttempt.user_id == user_id,
        SupportDeliveryAttempt.outcome == 'sending',
    ).values(**attempt_result).execution_options(synchronize_session=False))
    session.execute(update(SupportTicket).where(
        SupportTicket.id == ticket_id, SupportTicket.user_id == user_id,
        SupportTicket.github_attempt_id == nonce, SupportTicket.github_sync == 'sending',
    ).values(**result).execution_options(synchronize_session=False))
    try:
        session.commit()
    except Exception:
        session.rollback()
        # The committed sending marker survives a failed/unknown result commit.
        # If the DB is unavailable, propagate the safe API failure; a later
        # request still finds the durable receipt and does not POST again.
        session.refresh(ticket)
    else:
        session.refresh(ticket)
    return ticket


def support_reconciliation_candidate(session, actor_id, ticket_id, *, admin=False):
    """Release every DB lock/transaction before the external read."""
    from oneirodex.models import SupportTicket, SupportDeliveryAttempt, SupportDeliveryCheckBudget, User
    query = select(SupportTicket).where(SupportTicket.id == ticket_id)
    if not admin:
        query = query.where(SupportTicket.user_id == actor_id)
    ticket = session.scalar(query.execution_options(populate_existing=True))
    if ticket is None:
        raise SupportRequestNotFound('Support report not found.')
    if ticket.github_sync in {'synced', 'reconciled'}:
        result = {'ticket': ticket.to_dict()}
        session.commit()
        return result
    if ticket.github_sync not in {'unknown', 'sending', 'error'} or not ticket.github_attempt_id:
        raise SupportRequestConflict('There is no verifiable uncertain delivery to check.')
    attempt = session.get(SupportDeliveryAttempt, {'id': ticket.github_attempt_id, 'user_id': ticket.user_id})
    if attempt is None or attempt.ticket_id != ticket.id:
        raise SupportRequestConflict('This older delivery needs an administrator to check its provider record.')
    result = {'ticket': None, 'ticket_id': ticket.id, 'owner_id': ticket.user_id,
              'attempt_id': attempt.id, 'repository': attempt.repository,
              'payload_sha256': attempt.payload_sha256}
    session.scalar(select(User.id).where(User.id == actor_id).with_for_update())
    now = delivery_now()
    budget = session.get(SupportDeliveryCheckBudget, actor_id)
    if budget is None:
        budget = SupportDeliveryCheckBudget(user_id=actor_id, window_started_at=now, count=0)
        session.add(budget)
    if budget.window_started_at + timedelta(hours=1) <= now:
        budget.window_started_at, budget.count = now, 0
    if budget.count >= 5:
        session.rollback()
        raise SupportRateLimited('Delivery check limit reached. Try again later.')
    budget.count += 1
    session.commit()
    return result


def finish_support_reconciliation(session, candidate, issue):
    from oneirodex.models import SupportTicket, SupportDeliveryAttempt
    if issue is None or outgoing_fingerprint(issue) != candidate['payload_sha256']:
        raise SupportRequestConflict('Could not confirm that issue for this report. No new issue was sent.')
    changed = session.execute(update(SupportDeliveryAttempt).where(
        SupportDeliveryAttempt.id == candidate['attempt_id'],
        SupportDeliveryAttempt.user_id == candidate['owner_id'],
        SupportDeliveryAttempt.ticket_id == candidate['ticket_id'],
        SupportDeliveryAttempt.payload_sha256 == candidate['payload_sha256'],
        SupportDeliveryAttempt.outcome.in_(['sending', 'unknown', 'error', 'rejected', 'skipped']),
    ).values(outcome='reconciled', issue_number=issue['number'], issue_url=issue['html_url'])
      .execution_options(synchronize_session=False)).rowcount
    if changed:
        linked = session.execute(update(SupportTicket).where(
            SupportTicket.id == candidate['ticket_id'], SupportTicket.user_id == candidate['owner_id'],
            SupportTicket.github_attempt_id == candidate['attempt_id'],
            SupportTicket.github_sync.in_(['sending', 'unknown', 'error', 'rejected', 'skipped']),
        ).values(github_sync='reconciled', github_issue_number=issue['number'], github_issue_url=issue['html_url'])
          .execution_options(synchronize_session=False)).rowcount
        if not linked:
            session.rollback()
        else:
            session.commit()
    else:
        session.rollback()
    ticket = session.scalar(select(SupportTicket).where(
        SupportTicket.id == candidate['ticket_id'], SupportTicket.user_id == candidate['owner_id'],
    ).execution_options(populate_existing=True))
    if ticket is None:
        raise SupportRequestNotFound('Support report not found.')
    return ticket.to_dict()
