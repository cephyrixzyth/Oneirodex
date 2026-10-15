"""Native ticket create/resolve actions with persistence and notification adapters."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context

_WINDOW = timedelta(hours=1)
_RATE_LIMIT = 5
_BODY_MAX = 2000
_LOGS_MAX = 4000
_AREAS = frozenset({'auth', 'library', 'download', 'webretro', 'companion', 'acquire', 'social', 'themes', 'admin', 'oidc', 'security', 'other'})
_KINDS = frozenset({'issue', 'enhancement'})
_SEVERITIES = frozenset({'P0', 'P1', 'P2', 'P3'})


class SupportMutationData:
    def recent_count(self, user_id, cutoff):
        from sqlalchemy import func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SupportTicket
        return db.session.scalar(select(func.count(SupportTicket.id)).where(
            SupportTicket.user_id == user_id, SupportTicket.created_at >= cutoff,
        )) or 0

    def create(self, user, body, now):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SupportTicket
        from oneirodex.utils.role_catalog import normalize_role
        from oneirodex.utils.github_issues import build_issue_body, create_github_issue
        from oneirodex.utils.notifications import notify_admins

        title = body['title'][:200]
        ticket_body = (body.get('body') or body.get('symptom') or '').strip()[:_BODY_MAX]
        area = (body.get('area') or 'other').strip().lower()
        if area not in _AREAS:
            area = 'other'
        kind = (body.get('kind') or 'issue').strip().lower()
        if kind not in _KINDS:
            kind = 'issue'
        severity = (body.get('severity') or 'P2').strip().upper()
        if severity not in _SEVERITIES:
            severity = 'P2'
        ticket = SupportTicket(
            user_id=user.id, title=title, body=ticket_body, area=area, kind=kind,
            severity=severity, role_at_submit=normalize_role(getattr(user, 'role', None)),
            deploy_hint=(body.get('deploy_hint') or body.get('deploy') or '')[:64] or None,
            client_hint=(body.get('client_hint') or body.get('client') or '')[:120] or None,
            url_hint=(body.get('url_hint') or body.get('url') or '')[:512] or None,
            logs=(body.get('logs') or '').strip()[:_LOGS_MAX] or None,
            status='open', github_sync='pending', created_at=now,
        )
        db.session.add(ticket)
        db.session.commit()
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
            logging.getLogger(__name__).warning('GitHub issue sync failed')
        db.session.commit()
        try:
            notify_admins(
                kind='support_ticket', title=f'Support: {ticket.title}',
                body=f'{ticket.severity} · {ticket.area} · by {getattr(user, "name", "member")}',
                link='/admin/support', actor_user_id=user.id,
                payload={'ticket_id': ticket.id, 'github_url': ticket.github_issue_url},
                pref_flag='notify_support',
            )
        except Exception:
            pass
        return ticket.to_dict()

    def resolve(self, ticket_id, admin_id, now):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SupportTicket
        ticket = db.session.get(SupportTicket, ticket_id)
        if ticket is None:
            return None
        ticket.status = 'resolved'
        ticket.resolved_at = now
        ticket.resolved_by_user_id = admin_id
        db.session.commit()
        return ticket.to_dict()


def create_support_mutation_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None, data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    opts = dict(flask_app=flask_app, data=data_access or SupportMutationData(),
                find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager, database_scope=database_scope)

    @router.post('/api/support/tickets')
    async def create_ticket(request: Request):
        return await _mutate(request, **opts, ticket_id=None)

    @router.post('/api/support/tickets/{ticket_id:int}/resolve')
    async def resolve_ticket(ticket_id: int, request: Request):
        return await _mutate(request, **opts, ticket_id=ticket_id)

    return router


def mount_support_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_support_mutation_router(flask_app, **kwargs))
    return app


async def _mutate(request, *, flask_app, data, find_user, find_token,
                  commit_token_touch, load_user_id, login_manager,
                  database_scope, ticket_id):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
        session = load_session_cookie(
            request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
            max_age=_lifetime_seconds(flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)),
            fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
        )
        csrf = csrf_error_response(request, session, flask_app.config)
        auth = None
        if csrf is None:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        from oneirodex.utils.role_catalog import normalize_role
        if csrf is not None:
            response = csrf
        elif auth.user is None:
            response = _login_redirect(flask_app, request, login_manager, auth,
                message=getattr(login_manager, 'login_message', None),
                category=getattr(login_manager, 'login_message_category', 'message'), include_next=True)
        elif auth.token is not None:
            payload, status = api_error_payload('Sign in with your site account to manage support reports', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        elif ticket_id is None:
            if (data.recent_count(auth.user.id, datetime.now(timezone.utc) - _WINDOW) >= _RATE_LIMIT):
                payload, status = api_error_payload('Support report limit reached. Try again later.', code='rate_limited')
                response = JSONResponse(payload, status_code=status)
            else:
                body = await _read_json(request)
                try:
                    from oneirodex.schemas.support import CreateSupportTicketBody
                    if body is None:
                        raise ValueError('A valid JSON object is required.')
                    model = CreateSupportTicketBody.model_validate(body)
                    result = data.create(auth.user, model.model_dump(), datetime.now(timezone.utc))
                    response = JSONResponse(api_ok_payload({'ticket': result}), status_code=201)
                except (ValidationError, ValueError):
                    payload, status = api_error_payload('Support report could not be validated.', code='bad_request')
                    response = JSONResponse(payload, status_code=status)
                except Exception:
                    from oneirodex.runtime_native.db_session import native_db as db
                    db.session.rollback()
                    logging.getLogger(__name__).warning('Support ticket create failed')
                    payload, status = api_error_payload('Could not create support report.', code='internal')
                    response = JSONResponse(payload, status_code=status)
        elif normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
            payload, status = api_error_payload('You must be an admin to access this page.', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        elif auth.token is not None and not auth.has_scope('admin'):
            payload, status = api_error_payload('This token does not have the admin scope', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        else:
            result = data.resolve(ticket_id, auth.user.id, datetime.now(timezone.utc))
            if result is None:
                payload, status = api_error_payload('Ticket not found', code='not_found')
                response = JSONResponse(payload, status_code=status)
            else:
                response = JSONResponse(api_ok_payload({'ticket': result}))
        if auth is not None and auth.should_set_session_cookie:
            _set_session_cookie(response, flask_app, auth)
    from oneirodex.utils.security_headers import security_header_values
    response.headers.setdefault('Cache-Control', 'no-store')
    for key, value in security_header_values(flask_app.config).items():
        response.headers.setdefault(key, value)
    return response


async def _read_json(request):
    import json
    try:
        if int(request.headers.get('content-length') or '0') > 16 * 1024:
            return None
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16 * 1024:
                return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None
