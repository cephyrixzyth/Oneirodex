"""In-app support tickets → GitHub Issues + admin alerts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import current_app, jsonify, make_response

from oneirodex.utils.api_response import api_error, api_ok
from flask_login import current_user, login_required
from sqlalchemy import func, select

from oneirodex import db
from oneirodex.models import SupportTicket
from oneirodex.schemas.support import CreateSupportTicketBody
from oneirodex.utils.auth import admin_required
from oneirodex.utils.validation import validate_body
from oneirodex.utils.github_issues import create_github_issue
from oneirodex.utils.support_reports import (
    preview_support_report, valid_support_preview, support_fields, support_external_payload,
)
from oneirodex.utils.notifications import notify_admins
from oneirodex.utils.rbac import normalize_role
from oneirodex.utils.api_tokens import require_browser_session

from . import apis_bp
from oneirodex.utils.rbac import is_admin

VALID_AREAS = frozenset({
    'auth', 'library', 'download', 'webretro', 'companion', 'acquire',
    'social', 'themes', 'admin', 'oidc', 'security', 'other',
})
VALID_SEV = frozenset({'P0', 'P1', 'P2', 'P3'})

# Bug report vs feature request — the two things the one Report form collects.
VALID_KINDS = frozenset({'issue', 'enhancement'})
_SUPPORT_TICKET_WINDOW = timedelta(hours=1)
_SUPPORT_TICKET_LIMIT = 5

# Compact caps — logs/symptoms optional; avoid huge blobs in UI payloads.
_BODY_MAX = 2000
_LOGS_MAX = 4000


@apis_bp.route('/support/tickets', methods=['POST'])
@login_required
@require_browser_session
@validate_body(CreateSupportTicketBody)
def support_ticket_create(body: CreateSupportTicketBody):
    values = body.model_dump()
    if body.sync_to_github:
        approval = valid_support_preview(current_user, values, current_app.secret_key)
        if not approval:
            return api_error('Preview this report and its destination again before sending to GitHub.', code='conflict')
        values['_approved_repository'] = approval['destination']
    now = datetime.now(timezone.utc)
    recent_count = db.session.scalar(
        select(func.count(SupportTicket.id)).where(
            SupportTicket.user_id == current_user.id,
            SupportTicket.created_at >= now - _SUPPORT_TICKET_WINDOW,
        )
    ) or 0
    if recent_count >= _SUPPORT_TICKET_LIMIT:
        return api_error(
            'Support report limit reached. Try again later.',
            code='rate_limited',
        )

    ticket = SupportTicket(
        **support_fields(values),
        user_id=current_user.id,
        role_at_submit=normalize_role(getattr(current_user, 'role', None)),
        status='open',
        github_sync='pending' if body.sync_to_github else 'local_only',
        created_at=now,
    )
    db.session.add(ticket)
    db.session.commit()

    # The kind leads the title and rides along as a label, so the distinction
    # survives into the issue tracker instead of stopping at our database.
    if body.sync_to_github:
        gh = create_github_issue(
            **support_external_payload(current_user, values),
        )
        if gh.get('ok'):
            ticket.github_sync = 'synced'
            ticket.github_issue_number = gh.get('number')
            ticket.github_issue_url = gh.get('url')
        elif gh.get('skipped'):
            ticket.github_sync = 'skipped'
        else:
            ticket.github_sync = 'error'
            current_app.logger.warning('GitHub issue sync failed: %s', gh.get('error'))
        db.session.commit()

    try:
        notify_admins(
            kind='support_ticket',
            title=f'Support: {ticket.title}',
            body=f'{ticket.severity} · {ticket.area} · by {current_user.name}',
            link='/admin/support',
            actor_user_id=current_user.id,
            payload={'ticket_id': ticket.id, 'github_url': ticket.github_issue_url},
            pref_flag='notify_support',
        )
    except Exception:
        pass

    return api_ok({'ticket': ticket.to_dict()}, status=201)


@apis_bp.route('/support/preview', methods=['POST'])
@login_required
@require_browser_session
@validate_body(CreateSupportTicketBody)
def support_report_preview(body: CreateSupportTicketBody):
    response = make_response(api_ok({'preview': preview_support_report(current_user, body.model_dump(), current_app.secret_key)}))
    response.headers['Cache-Control'] = 'no-store'
    return response


@apis_bp.route('/support/tickets', methods=['GET'])
@login_required
@require_browser_session
def support_tickets_list():
    q = select(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(100)
    if not is_admin(current_user):
        q = select(SupportTicket).where(
            SupportTicket.user_id == current_user.id,
        ).order_by(SupportTicket.created_at.desc()).limit(50)
    rows = db.session.execute(q).scalars().all()
    return jsonify({
        'tickets': [r.to_dict(compact=True) for r in rows],
        'empty': len(rows) == 0,
    })


@apis_bp.route('/support/tickets/<int:ticket_id>', methods=['GET'])
@login_required
@require_browser_session
def support_ticket_detail(ticket_id: int):
    ticket = db.session.get(SupportTicket, ticket_id)
    if not ticket:
        return api_error('Ticket not found', code='not_found')
    if not is_admin(current_user) and ticket.user_id != current_user.id:
        return api_error('That ticket belongs to someone else', code='forbidden')
    return jsonify({'ticket': ticket.to_dict()})


@apis_bp.route('/support/tickets/<int:ticket_id>/resolve', methods=['POST'])
@login_required
@admin_required
def support_ticket_resolve(ticket_id: int):
    ticket = db.session.get(SupportTicket, ticket_id)
    if not ticket:
        return api_error('Ticket not found', code='not_found')
    ticket.status = 'resolved'
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.resolved_by_user_id = current_user.id
    db.session.commit()
    return api_ok({'ticket': ticket.to_dict()})
