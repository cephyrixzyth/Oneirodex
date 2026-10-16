"""FastAPI compatibility routes for the admin invite manager APIs."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminInvitesData:
    def list(self):
        from sqlalchemy import and_, func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import InviteToken, User

        users = db.session.execute(select(User).order_by(User.name.asc())).scalars().all()
        counts = db.session.execute(
            select(User.user_id, func.count(InviteToken.id).label('unused_count'))
            .select_from(User)
            .outerjoin(InviteToken, and_(
                InviteToken.creator_user_id == User.user_id,
                InviteToken.used.is_(False),
            ))
            .group_by(User.user_id)
        ).all()
        unused = {row.user_id: int(row.unused_count or 0) for row in counts}
        return {'users': [{
            'id': user.id, 'user_id': user.user_id, 'name': user.name,
            'email': user.email, 'role': user.role,
            'invite_quota': int(user.invite_quota or 0),
            'unused_invites': unused.get(user.user_id, 0),
        } for user in users]}

    def adjust_quota(self, body):
        from sqlalchemy import select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User

        user = db.session.execute(
            select(User).filter_by(user_id=str(body.user_id)).with_for_update()
        ).scalars().first()
        if user is None:
            return None
        user.invite_quota = int(user.invite_quota or 0) + body.invites_number
        db.session.commit()
        return {'user_id': user.user_id, 'invite_quota': user.invite_quota}

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db
        db.session.rollback()


def create_admin_invites_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminInvitesData()

    @router.api_route('/admin/api/invites', methods=['GET', 'HEAD'])
    @router.post('/admin/api/invites/quota')
    @router.post('/admin/manage_invites')
    async def admin_invites(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            legacy_form = request.url.path == '/admin/manage_invites'
            form_data = {}
            form_error = None
            if legacy_form:
                form_data, form_error = await _legacy_form(request)
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            from oneirodex.utils.role_catalog import normalize_role
            if form_error is not None:
                csrf_response = form_error
            elif request.method == 'POST' and auth.token is None:
                from .csrf_compat import csrf_error_response
                csrf_response = csrf_error_response(
                    request, auth.session_data, flask_app.config,
                    token=form_data.get(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')) if legacy_form else None,
                )
            else:
                csrf_response = None
            user = auth.user
            admin = (
                user is not None and bool(getattr(user, 'is_authenticated', True))
                and normalize_role(getattr(user, 'role', None) or '') == 'admin'
            )
            if csrf_response is not None:
                response = csrf_response
            elif user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif not admin:
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif auth.token is not None and not auth.has_scope('admin'):
                response = _error('This token does not have the admin scope', 'forbidden')
            else:
                try:
                    if request.method in ('GET', 'HEAD'):
                        response = JSONResponse(data.list())
                    elif legacy_form:
                        response = await _adjust_form(request, form_data, data, auth)
                    else:
                        result = await _adjust(request, data)
                        response = result
                except Exception:  # noqa: BLE001 — do not expose SQL diagnostics
                    data.rollback()
                    response = _error('Internal server error', 'internal')
            if auth.should_set_session_cookie or auth.session_data.get('_flashes'):
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method in ('GET', 'HEAD'):
                response.headers.setdefault('Cache-Control', 'no-store')
            if request.method == 'HEAD':
                response.body = b''
            return response

    return router


async def _adjust(request, data):
    import json
    from pydantic import ValidationError
    from oneirodex.schemas.invites import AdjustInviteQuotaBody
    from oneirodex.utils.validation import format_validation_errors

    try:
        payload = json.loads(await request.body() or b'{}')
        body = AdjustInviteQuotaBody.model_validate(payload)
    except (TypeError, ValueError, UnicodeDecodeError, ValidationError) as exc:
        detail = format_validation_errors(exc) if isinstance(exc, ValidationError) else 'Invalid JSON body.'
        return _error('Invalid request.', 'unprocessable', 422, detail=detail)
    result = data.adjust_quota(body)
    if result is None:
        return _error('User not found.', 'not_found')
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload(result), status_code=200)


async def _adjust_form(request, form, data, auth):
    from html import escape
    from pathlib import Path
    from .account_avatar_upload import _flash
    from pydantic import ValidationError
    from starlette.responses import HTMLResponse, RedirectResponse, Response
    from oneirodex.schemas.invites import AdjustInviteQuotaBody

    if int(request.headers.get('content-length') or '0') > 64 * 1024:
        return Response(status_code=413)
    user_id = (form.get('user_id') or '').strip()
    page_message = None
    page_category = 'success'
    if not user_id:
        _flash(auth.session_data, 'error', 'User ID is required.')
        return RedirectResponse('/admin/manage_invites', status_code=302)
    else:
        try:
            number = int(form.get('invites_number') or '0')
        except (TypeError, ValueError):
            _flash(auth.session_data, 'error', 'Invalid invite number provided. Please enter a valid number.')
            return RedirectResponse('/admin/manage_invites', status_code=302)
        else:
            try:
                body = AdjustInviteQuotaBody.model_validate({
                    'user_id': user_id, 'invites_number': number,
                })
            except ValidationError:
                message = (
                    'Invalid user ID format.' if not _valid_uuid(user_id)
                    else 'Invite number must be between -1000 and 1000.'
                )
                _flash(auth.session_data, 'error', message)
                return RedirectResponse('/admin/manage_invites', status_code=302)
            else:
                try:
                    result = data.adjust_quota(body)
                    if result is None:
                        page_message = 'User not found.'
                        page_category = 'danger'
                    else:
                        page_message = (
                            f"Invites updated successfully. User "
                            f"{getattr(auth.user, 'name', '')} now has "
                            f"{result['invite_quota']} invite quota."
                        )
                except Exception:
                    data.rollback()
                    return RedirectResponse('/admin/manage_invites', status_code=302)

    shell_path = (
        Path(__file__).resolve().parents[1]
        / 'static' / 'dist' / 'admin-pilot' / 'index.html'
    )
    try:
        shell = shell_path.read_text(encoding='utf-8')
    except OSError:
        shell = (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<title>Invites · Oneirodex Admin</title></head>'
            '<body><main><h1>Invites</h1><a href="/admin/manage_invites">Continue</a></main></body></html>'
        )
    if page_message:
        role = 'status' if page_category == 'success' else 'alert'
        notice = (
            f'<div class="container-flash-messages"><div '
            f'class="alert alert-{page_category}" role="{role}">'
            f'{escape(page_message)}</div></div>\n'
        )
        root_marker = '<div id="admin-app-root"'
        root_offset = shell.find(root_marker)
        if root_offset >= 0:
            shell = shell[:root_offset] + notice + shell[root_offset:]
    return HTMLResponse(shell, status_code=200, headers={'Cache-Control': 'no-store'})


async def _legacy_form(request):
    from urllib.parse import parse_qs
    from starlette.responses import Response

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 64 * 1024:
            return {}, Response(status_code=413)
    try:
        fields = parse_qs(bytes(body).decode('utf-8'), keep_blank_values=True)
    except UnicodeDecodeError:
        return {}, Response(status_code=400)
    return {name: values[-1] for name, values in fields.items() if values}, None


def _valid_uuid(value):
    from uuid import UUID
    try:
        UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def _error(message, code, status=None, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload
    payload, status = api_error_payload(message, code=code, status=status, detail=detail)
    return JSONResponse(payload, status_code=status)


def mount_admin_invites_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_invites_router(flask_app, **kwargs))
    return app
