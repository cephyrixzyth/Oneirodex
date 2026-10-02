"""In-app support tickets → GitHub Issues + admin alerts."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app, jsonify

from oneirodex.utils.api_response import api_error, api_ok
from flask_login import current_user, login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import SupportTicket
from oneirodex.schemas.support import CreateSupportTicketBody
from oneirodex.utils.auth import admin_required
from oneirodex.utils.validation import validate_body
from oneirodex.utils.github_issues import build_issue_body, create_github_issue
from oneirodex.utils.notifications import notify_admins
from oneirodex.utils.rbac import normalize_role

from . import apis_bp
from oneirodex.utils.rbac import is_admin

VALID_AREAS = frozenset({
    'auth', 'library', 'download', 'webretro', 'companion', 'acquire',
    'social', 'themes', 'admin', 'oidc', 'security', 'other',
})
VALID_SEV = frozenset({'P0', 'P1', 'P2', 'P3'})

# Bug report vs feature request — the two things the one Report form collects.
VALID_KINDS = frozenset({'issue', 'enhancement'})

# Compact caps — logs/symptoms optional; avoid huge blobs in UI payloads.
_BODY_MAX = 2000
_LOGS_MAX = 4000


@apis_bp.route('/support/tickets', methods=['POST'])
@login_required
@validate_body(CreateSupportTicketBody)
def support_ticket_create(body: CreateSupportTicketBody):
    title = body.title[:200]
    # Symptom/body optional for redesigned Report UI (title alone is enough).
    ticket_body = (body.body or body.symptom or '').strip()[:_BODY_MAX]
    area = (body.area or 'other').strip().lower()
    if area not in VALID_AREAS:
        area = 'other'
    # A request for something new is not a defect, and filing it as one both
    # misleads triage and makes the product look broken. Unknown values fall
    # back to 'issue' rather than 404ing a report someone took time to write.
    kind = (body.kind or 'issue').strip().lower()
    if kind not in VALID_KINDS:
        kind = 'issue'
    severity = (body.severity or 'P2').strip().upper()
    if severity not in VALID_SEV:
        severity = 'P2'
    logs_raw = (body.logs or '').strip()[:_LOGS_MAX]
    ticket = SupportTicket(
        user_id=current_user.id,
        title=title,
        body=ticket_body or '',
        area=area,
        kind=kind,
        severity=severity,
        role_at_submit=normalize_role(getattr(current_user, 'role', None)),
        deploy_hint=(body.deploy_hint or body.deploy or '')[:64] or None,
        client_hint=(body.client_hint or body.client or '')[:120] or None,
        url_hint=(body.url_hint or body.url or '')[:512] or None,
        logs=logs_raw or None,
        status='open',
        github_sync='pending',
    )
    db.session.add(ticket)
    db.session.commit()

    # The kind leads the title and rides along as a label, so the distinction
    # survives into the issue tracker instead of stopping at our database.
    gh = create_github_issue(
        title=f'[{ticket.kind}] {ticket.severity} {ticket.area}: {ticket.title}',
        body=build_issue_body(ticket.to_dict()),
        labels=['support', ticket.kind, ticket.severity.lower(), ticket.area],
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


@apis_bp.route('/support/tickets', methods=['GET'])
@login_required
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
