"""FastAPI compatibility routes for the admin email whitelist."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .oidc_status import _login_redirect, _set_session_cookie
from .request_auth import request_auth_context


class AdminWhitelistData:
    def list(self):
        from sqlalchemy import func, select
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import User, Whitelist

        entries = db.session.execute(select(Whitelist).order_by(Whitelist.email)).scalars().all()
        emails = [entry.email.lower() for entry in entries]
        registered = set(db.session.execute(
            select(func.lower(User.email)).where(func.lower(User.email).in_(emails))
        ).scalars().all()) if emails else set()
        return {'entries': [{
            'id': entry.id, 'email': entry.email,
            'is_registered': entry.email.lower() in registered,
        } for entry in entries]}

    def add(self, body, actor):
        from sqlalchemy.exc import IntegrityError
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Whitelist
        from oneirodex.utils.event_logging import log_system_event

        entry = Whitelist(email=body.email)
        try:
            db.session.add(entry)
            db.session.commit()
            log_system_event(
                f'Admin {actor.name} added email to whitelist: {body.email}',
                event_type='audit', event_level='information', audit_user=actor.id,
            )
            return {'id': entry.id, 'email': entry.email}, None
        except IntegrityError:
            db.session.rollback()
            log_system_event(
                f'Admin {actor.name} attempted to add duplicate email to whitelist: {body.email}',
                event_type='audit', event_level='warning', audit_user=actor.id,
            )
            return None, ('The email is already in the whitelist.', 'conflict', None)
        except Exception:  # noqa: BLE001 — do not expose persistence diagnostics
            db.session.rollback()
            log_system_event(
                'Error adding email to whitelist', event_type='error',
                event_level='error', audit_user=actor.id,
            )
            return None, ('Unable to add the email to the whitelist.', 'internal', None)

    def delete(self, whitelist_id, actor):
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.models import Whitelist
        from oneirodex.utils.event_logging import log_system_event

        if whitelist_id <= 0:
            return None, ('Invalid whitelist ID', 'bad_request', None)
        entry = db.session.get(Whitelist, whitelist_id)
        if entry is None:
            return None, ('Not found', 'not_found', 404)
        try:
            email = entry.email
            db.session.delete(entry)
            log_system_event(
                f'Admin {actor.name} deleted whitelist entry: {email}',
                event_type='audit', event_level='information', audit_user=actor.id,
            )
            db.session.commit()
            return {'message': 'Entry deleted successfully'}, None
        except Exception:  # noqa: BLE001 — do not expose persistence diagnostics
            db.session.rollback()
            log_system_event(
                f'Error deleting whitelist entry {whitelist_id}',
                event_type='error', event_level='error', audit_user=actor.id,
            )
            return None, ('An error occurred while deleting the entry', 'internal', None)

    def rollback(self):
        from oneirodex.runtime_native.db_session import native_db as db
        db.session.rollback()


def create_admin_whitelist_router(
    flask_app, *, find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None], commit_token_touch: Callable[[Any], None],
    load_user_id=None, login_manager=None, data_access=None, database_scope=None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or AdminWhitelistData()

    @router.api_route('/admin/api/whitelist', methods=['GET', 'HEAD', 'POST'])
    @router.delete('/admin/whitelist/{whitelist_id:int}')
    async def admin_whitelist(request: Request, whitelist_id: int | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if request.method in ('POST', 'DELETE') and auth.token is None:
                from .csrf_compat import csrf_error_response
                csrf_response = csrf_error_response(request, auth.session_data, flask_app.config)
            else:
                csrf_response = None
            from oneirodex.utils.role_catalog import normalize_role
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
                        response = _ok(data.list())
                    elif request.method == 'POST':
                        body, invalid = await _body(request)
                        if invalid is not None:
                            response = invalid
                        else:
                            payload, error = data.add(body, user)
                            response = _result(payload, error, status=201)
                    else:
                        payload, error = data.delete(whitelist_id or 0, user)
                        if error and error[1] == 'not_found' and not _wants_json_error(request):
                            from werkzeug.exceptions import NotFound
                            legacy = NotFound().get_response()
                            response = Response(
                                content=legacy.get_data(),
                                status_code=legacy.status_code,
                                headers=dict(legacy.headers),
                            )
                        else:
                            response = _result(payload, error)
                except Exception:  # noqa: BLE001 — do not expose persistence diagnostics
                    data.rollback()
                    response = _error('Internal server error', 'internal')
            if auth.should_set_session_cookie:
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method in ('GET', 'HEAD'):
                response.headers.setdefault('Cache-Control', 'no-store')
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.post('/admin/whitelist')
    async def legacy_whitelist_form(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            form, body_error = await _legacy_form(request)
            response = body_error
            if response is None:
                from .csrf_compat import csrf_error_response
                response = csrf_error_response(
                    request, auth.session_data, flask_app.config,
                    token=form.get(str(flask_app.config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')),
                )
            from oneirodex.utils.role_catalog import normalize_role
            if response is None and auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif response is None and normalize_role(getattr(auth.user, 'role', None) or '') != 'admin':
                response = _login_redirect(
                    flask_app, request, login_manager, auth,
                    message='You must be an admin to access this page.',
                    category='danger', include_next=False,
                )
            elif response is None and auth.token is not None and not auth.has_scope('admin'):
                response = _error('This token does not have the admin scope', 'forbidden')
            elif response is None:
                from .account_avatar_upload import _flash
                from oneirodex.schemas.whitelist import AddWhitelistBody
                from pydantic import ValidationError
                from email_validator import EmailNotValidError, validate_email
                raw_email = form.get('email') or ''
                invalid_form_error = None
                try:
                    # The legacy WTForms Email validator checks the submitted
                    # value before the route strips and lowercases it. Validate
                    # that raw value first so whitespace/control characters
                    # cannot be silently accepted by the normalized API schema.
                    validate_email(raw_email, check_deliverability=False)
                except EmailNotValidError:
                    invalid_form_error = (
                        'This field is required.' if not raw_email.strip()
                        else 'Invalid email address.'
                    )
                else:
                    if len(raw_email.strip()) > 120:
                        invalid_form_error = 'Email address is too long (maximum 120 characters)'
                    else:
                        try:
                            body = AddWhitelistBody.model_validate({'email': raw_email})
                        except ValidationError:
                            invalid_form_error = 'Invalid email address.'
                        else:
                            payload, error = data.add(body, auth.user)
                            if error is None:
                                _flash(auth.session_data, 'success', 'The email was successfully added to the whitelist!')
                            elif error[1] == 'conflict':
                                _flash(auth.session_data, 'danger', 'The email is already in the whitelist!')
                            else:
                                _flash(auth.session_data, 'danger', 'An error occurred while adding the email to the whitelist')
                if invalid_form_error:
                    _flash(auth.session_data, 'danger', invalid_form_error)
                from .response_compat import flask_redirect_response
                response = flask_redirect_response('/admin/whitelist')
            if auth.should_set_session_cookie or auth.session_data.get('_flashes'):
                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    return router


async def _body(request):
    import json
    from pydantic import ValidationError
    from oneirodex.schemas.whitelist import AddWhitelistBody
    from oneirodex.utils.validation import format_validation_errors

    try:
        raw = json.loads(await request.body() or b'{}')
        body = AddWhitelistBody.model_validate(raw)
        return body, None
    except ValidationError as exc:
        return None, _error(
            'Invalid request.', 'unprocessable', 422,
            detail=format_validation_errors(exc),
        )
    except (TypeError, ValueError, UnicodeDecodeError):
        return None, _error('Invalid request.', 'unprocessable', 422, detail='Invalid JSON body.')


async def _legacy_form(request):
    from urllib.parse import parse_qs

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


def _wants_json_error(request):
    """Mirror the legacy Flask error handler's XHR/content-negotiation test."""
    from werkzeug.datastructures import MIMEAccept
    from werkzeug.http import parse_accept_header

    accept = parse_accept_header(request.headers.get('accept', ''), MIMEAccept)
    return (
        request.url.path.startswith('/api/')
        or accept.best == 'application/json'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )


def _ok(payload):
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload(payload))


def _result(payload, error, *, status=200):
    if error is not None:
        return _error(error[0], error[1], error[2])
    from oneirodex.utils.api_contract import api_ok_payload
    return JSONResponse(api_ok_payload(payload), status_code=status)


def _error(message, code, status=None, *, detail=None):
    from oneirodex.utils.api_contract import api_error_payload
    payload, status = api_error_payload(message, code=code, status=status, detail=detail)
    return JSONResponse(payload, status_code=status)


def mount_admin_whitelist_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_admin_whitelist_router(flask_app, **kwargs))
    return app
