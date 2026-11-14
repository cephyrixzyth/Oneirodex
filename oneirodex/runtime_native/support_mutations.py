"""Native ticket create/resolve actions with persistence and notification adapters."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from pydantic import ValidationError
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

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
    def reconciliation_candidate(self, user_id, ticket_id, *, admin=False):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.support_delivery import support_reconciliation_candidate
        return support_reconciliation_candidate(db.session, user_id, ticket_id, admin=admin)

    def finish_reconciliation(self, candidate, issue):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.support_delivery import finish_support_reconciliation
        return finish_support_reconciliation(db.session, candidate, issue)

    def request_receipt(self, user_id, body):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.support_delivery import find_support_request, is_support_replay
        ticket = find_support_request(db.session, user_id, body)
        replay = is_support_replay(db.session, ticket, body)
        return (ticket.to_dict(), replay) if ticket is not None else None

    def recent_count(self, user_id, cutoff):
        from sqlalchemy import func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SupportTicket
        return db.session.scalar(select(func.count(SupportTicket.id)).where(
            SupportTicket.user_id == user_id, SupportTicket.created_at >= cutoff,
        )) or 0

    def create(self, user, body, now):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.github_issues import create_github_issue
        from oneirodex.utils.support_reports import support_external_payload
        from oneirodex.utils.support_delivery import persist_support_request, deliver_support_request
        from oneirodex.utils.notifications import notify_admins

        ticket, created = persist_support_request(db.session, user, body, now)
        if body.get('sync_to_github') is True:
            ticket = deliver_support_request(
                db.session, ticket, support_external_payload(user, body), create_github_issue,
                retry_id=body.get('retry_id') if body.get('retry_github') is True else None,
            )
        try:
            if created:
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

    @router.post('/api/support/preview')
    async def preview_ticket(request: Request):
        return await _mutate(request, **opts, ticket_id=None, preview=True)

    @router.post('/api/support/tickets/{ticket_id:int}/reconcile')
    async def reconcile_ticket(ticket_id: int, request: Request):
        return await _mutate(request, **opts, ticket_id=ticket_id, reconcile=True)

    @router.post('/api/support/tickets/{ticket_id:int}/resolve')
    async def resolve_ticket(ticket_id: int, request: Request):
        return await _mutate(request, **opts, ticket_id=ticket_id)

    return router


def mount_support_mutation_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_support_mutation_router(flask_app, **kwargs))
    return app


async def _mutate(request, *, flask_app, data, find_user, find_token,
                  commit_token_touch, load_user_id, login_manager,
                  database_scope, ticket_id, preview=False, reconcile=False):
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
        elif auth.token is not None and (ticket_id is None or reconcile):
            payload, status = api_error_payload('Sign in with your site account to manage support reports', code='forbidden')
            response = JSONResponse(payload, status_code=status)
        elif reconcile:
            from oneirodex.schemas.support import ReconcileSupportDeliveryBody
            from oneirodex.utils.github_issues import read_support_issue
            from oneirodex.utils.support_delivery import SupportRequestConflict, SupportRequestNotFound, SupportRateLimited
            try:
                model = ReconcileSupportDeliveryBody.model_validate(await _read_json(request))
                candidate = data.reconciliation_candidate(
                    auth.user.id, ticket_id,
                    admin=normalize_role(getattr(auth.user, 'role', None) or '') == 'admin',
                )
                result = candidate['ticket']
                if result is None:
                    issue = await run_in_threadpool(read_support_issue, repository=candidate['repository'], issue_number=model.issue_number)
                    result = data.finish_reconciliation(candidate, issue)
                response = JSONResponse(api_ok_payload({'ticket': result}))
            except (SupportRequestConflict, SupportRequestNotFound, SupportRateLimited) as exc:
                from oneirodex.runtime_native.db_session import native_db as db
                db.session.rollback()
                code = ('not_found' if isinstance(exc, SupportRequestNotFound)
                        else 'rate_limited' if isinstance(exc, SupportRateLimited) else 'conflict')
                payload, status = api_error_payload(str(exc), code=code)
                response = JSONResponse(payload, status_code=status)
            except ValidationError as exc:
                from oneirodex.utils.validation import format_validation_errors
                payload, status = api_error_payload('Invalid request.', code='unprocessable', detail=format_validation_errors(exc))
                response = JSONResponse(payload, status_code=status)
            except Exception:
                from oneirodex.runtime_native.db_session import native_db as db
                db.session.rollback()
                logging.getLogger(__name__).warning('Support delivery check failed')
                payload, status = api_error_payload('Could not check support delivery.', code='internal')
                response = JSONResponse(payload, status_code=status)
        elif ticket_id is None:
            from oneirodex.utils.support_delivery import SupportRequestConflict, SupportRateLimited
            body = await _read_json(request)
            try:
                from oneirodex.schemas.support import CreateSupportTicketBody
                from oneirodex.utils.support_reports import preview_support_report, valid_support_preview
                model = CreateSupportTicketBody.model_validate(body if body is not None else {})
                values = model.model_dump()
                receipt = data.request_receipt(auth.user.id, values) if not preview else None
                existing, replay = receipt if receipt is not None else (None, False)
                approval = valid_support_preview(auth.user, values, flask_app.config['SECRET_KEY']) if model.sync_to_github and not preview else None
                if preview:
                    result = preview_support_report(auth.user, values, flask_app.config['SECRET_KEY'])
                    response = JSONResponse(api_ok_payload({'preview': result}))
                elif replay:
                    response = JSONResponse(api_ok_payload({'ticket': existing}), status_code=201)
                elif model.sync_to_github and not approval:
                    payload, status = api_error_payload('Preview this report and its destination again before sending to GitHub.', code='conflict')
                    response = JSONResponse(payload, status_code=status)
                elif existing is None and data.recent_count(auth.user.id, datetime.now(timezone.utc) - _WINDOW) >= _RATE_LIMIT:
                    payload, status = api_error_payload('Support report limit reached. Try again later.', code='rate_limited')
                    response = JSONResponse(payload, status_code=status)
                else:
                    if approval:
                        values['_approved_repository'] = approval['destination']
                    result = data.create(auth.user, values, datetime.now(timezone.utc))
                    response = JSONResponse(api_ok_payload({'ticket': result}), status_code=201)
            except (SupportRequestConflict, SupportRateLimited) as exc:
                code = 'rate_limited' if isinstance(exc, SupportRateLimited) else 'conflict'
                payload, status = api_error_payload(str(exc), code=code)
                response = JSONResponse(payload, status_code=status)
            except ValidationError as exc:
                from oneirodex.utils.validation import format_validation_errors
                payload, status = api_error_payload('Invalid request.', code='unprocessable', detail=format_validation_errors(exc))
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
        return value
    except (ValueError, UnicodeDecodeError):
        return None
