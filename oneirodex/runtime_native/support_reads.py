"""Native read-only support ticket routes with owner/admin visibility."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse

from .request_auth import request_auth_context


class SupportReadsData:
    """Database adapter for support ticket reads."""

    def list_tickets(self, user, *, admin: bool):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SupportTicket

        query = select(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(100)
        if not admin:
            query = select(SupportTicket).where(
                SupportTicket.user_id == user.id,
            ).order_by(SupportTicket.created_at.desc()).limit(50)
        return db.session.execute(query).scalars().all()

    def ticket(self, ticket_id: int):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import SupportTicket

        return db.session.get(SupportTicket, ticket_id)


def create_support_reads_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    options = dict(
        flask_app=flask_app,
        data=data_access if data_access is not None else SupportReadsData(),
        find_user=find_user,
        find_token=find_token,
        commit_token_touch=commit_token_touch,
        load_user_id=load_user_id,
        login_manager=login_manager,
        database_scope=database_scope,
    )

    @router.api_route('/api/support/tickets', methods=['GET', 'HEAD'])
    async def support_tickets(request: Request):
        return await _run(request, **options, ticket_id=None)

    @router.api_route('/api/support/tickets/{ticket_id:int}', methods=['GET', 'HEAD'])
    async def support_ticket(request: Request, ticket_id: int):
        return await _run(request, **options, ticket_id=ticket_id)

    return router


def mount_support_reads_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_support_reads_router(flask_app, **kwargs))
    return app


async def _run(
    request, *, flask_app, data, find_user, find_token, commit_token_touch,
    load_user_id, login_manager, database_scope, ticket_id,
):
    scope = database_scope(flask_app) if database_scope else nullcontext()
    with scope:
        auth = request_auth_context(
            request, flask_app.config,
            find_user=find_user, find_token=find_token,
            commit_token_touch=commit_token_touch,
            load_user_id=load_user_id, login_manager=login_manager,
        )
        if auth.user is None:
            from .oidc_status import _login_redirect

            response = _login_redirect(
                flask_app, request, login_manager, auth,
                message=getattr(login_manager, 'login_message', None),
                category=getattr(login_manager, 'login_message_category', 'message'),
                include_next=True,
            )
        elif auth.token is not None:
            response = _error(403, 'forbidden', 'Sign in with your site account to view support reports')
        else:
            from oneirodex.utils.role_catalog import normalize_role

            admin = normalize_role(getattr(auth.user, 'role', None)) == 'admin'
            if ticket_id is None:
                rows = data.list_tickets(auth.user, admin=admin)
                response = JSONResponse({
                    'tickets': [row.to_dict(compact=True) for row in rows],
                    'empty': len(rows) == 0,
                })
            else:
                row = data.ticket(ticket_id)
                if row is None:
                    response = _error(404, 'not_found', 'Ticket not found')
                elif not admin and row.user_id != auth.user.id:
                    response = _error(403, 'forbidden', 'That ticket belongs to someone else')
                else:
                    response = JSONResponse({'ticket': row.to_dict()})
        if auth.should_set_session_cookie:
            from .oidc_status import _set_session_cookie

            _set_session_cookie(response, flask_app, auth)
        from oneirodex.utils.security_headers import security_header_values

        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response


def _error(status, code, message):
    from oneirodex.utils.api_contract import api_error_payload

    payload, resolved = api_error_payload(message, code=code, status=status)
    return JSONResponse(payload, status_code=resolved)
